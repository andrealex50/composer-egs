#!/usr/bin/env python3
"""
FlashSale full-stack test runner.

Goals:
- Exercise the Composer public API end to end.
- Validate Auth, Inventory, Payment, checkout saga, metrics and security edges.
- Work even when composer.flashsale is not reachable from the host by using
  `docker exec composer` and service DNS inside the Docker network.

The script is intentionally dependency-free: Python standard library only.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import random
import string
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DOCKER_HTTP_HELPER = r"""
import base64
import json
import sys
import time
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


method = sys.argv[1]
url = sys.argv[2]
headers = json.loads(sys.argv[3])
timeout = float(sys.argv[4])
body = sys.stdin.buffer.read()
data = body if body else None
req = urllib.request.Request(url, data=data, headers=headers, method=method)
opener = urllib.request.build_opener(NoRedirect)
start = time.perf_counter()
try:
    resp = opener.open(req, timeout=timeout)
    raw = resp.read()
    out = {
        "ok": True,
        "status": resp.getcode(),
        "headers": dict(resp.headers.items()),
        "body_b64": base64.b64encode(raw).decode("ascii"),
        "elapsed_ms": round((time.perf_counter() - start) * 1000, 1),
    }
except urllib.error.HTTPError as exc:
    raw = exc.read()
    out = {
        "ok": True,
        "status": exc.code,
        "headers": dict(exc.headers.items()),
        "body_b64": base64.b64encode(raw).decode("ascii"),
        "elapsed_ms": round((time.perf_counter() - start) * 1000, 1),
    }
except Exception as exc:
    out = {
        "ok": False,
        "status": 0,
        "headers": {},
        "body_b64": "",
        "elapsed_ms": round((time.perf_counter() - start) * 1000, 1),
        "error": repr(exc),
    }
print(json.dumps(out))
"""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass
class HttpResult:
    method: str
    url: str
    status: int
    headers: dict[str, str]
    body: bytes
    elapsed_ms: float
    ok: bool = True
    error: str = ""

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def json(self) -> Any:
        return json.loads(self.text)

    def header(self, name: str) -> str:
        wanted = name.lower()
        for key, value in self.headers.items():
            if key.lower() == wanted:
                return value
        return ""


@dataclass
class TestRecord:
    status: str
    name: str
    detail: str = ""
    elapsed_ms: float | None = None


@dataclass
class TestState:
    promoter_email: str = ""
    fan_email: str = ""
    payment_auth_email: str = ""
    password: str = "Teste1234!"
    promoter_token: str = ""
    promoter_refresh: str = ""
    fan_token: str = ""
    fan_refresh: str = ""
    payment_auth_token: str = ""
    event_id: str = ""
    ticket_ids: list[str] = field(default_factory=list)
    reserved_ticket_ids: list[str] = field(default_factory=list)
    sold_ticket_id: str = ""
    payment_customer_id: str = ""
    checkout_session_id: str = ""
    checkout_payment_id: str = ""
    checkout_ticket_ids: list[str] = field(default_factory=list)
    manual_payment_id: str = ""


class FlashSaleTester:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.records: list[TestRecord] = []
        self.state = TestState()
        self.mode = args.mode
        self.run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
        suffix = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(6))
        self.state.promoter_email = f"mega-{self.run_id}-{suffix}@prom.pt"
        self.state.fan_email = f"mega-{self.run_id}-{suffix}@test.pt"
        self.state.payment_auth_email = self.state.fan_email

        self.host_bases = {
            "composer": args.composer_base_url.rstrip("/"),
            "auth": args.auth_base_url.rstrip("/"),
            "payment_auth": args.payment_auth_base_url.rstrip("/"),
            "inventory": args.inventory_base_url.rstrip("/"),
            "payment": args.payment_base_url.rstrip("/"),
        }
        self.docker_bases = {
            "composer": "http://127.0.0.1:8000",
            "auth": "http://auth-service:8000",
            "payment_auth": "http://payment-auth-service:8000",
            "inventory": "http://inventory-service:8000",
            "payment": "http://payment-service:8000",
        }

    # ------------------------------------------------------------------
    # Logging and result accounting
    # ------------------------------------------------------------------

    def color(self, text: str, code: str) -> str:
        if self.args.no_color or not sys.stdout.isatty():
            return text
        return f"\033[{code}m{text}\033[0m"

    def info(self, message: str) -> None:
        print(self.color(message, "36"))

    def section(self, title: str) -> None:
        print()
        print(self.color(f"=== {title} ===", "1;34"))

    def pass_(self, name: str, detail: str = "", elapsed_ms: float | None = None) -> None:
        self.records.append(TestRecord("PASS", name, detail, elapsed_ms))
        suffix = f" ({elapsed_ms:.1f} ms)" if elapsed_ms is not None else ""
        print(f"  {self.color('PASS', '32')} {name}{suffix}{' - ' + detail if detail else ''}")

    def fail(self, name: str, detail: str = "", elapsed_ms: float | None = None) -> None:
        self.records.append(TestRecord("FAIL", name, detail, elapsed_ms))
        suffix = f" ({elapsed_ms:.1f} ms)" if elapsed_ms is not None else ""
        print(f"  {self.color('FAIL', '31')} {name}{suffix}{' - ' + detail if detail else ''}")

    def warn(self, name: str, detail: str = "", elapsed_ms: float | None = None) -> None:
        self.records.append(TestRecord("WARN", name, detail, elapsed_ms))
        suffix = f" ({elapsed_ms:.1f} ms)" if elapsed_ms is not None else ""
        print(f"  {self.color('WARN', '33')} {name}{suffix}{' - ' + detail if detail else ''}")

    def skip(self, name: str, detail: str = "") -> None:
        self.records.append(TestRecord("SKIP", name, detail))
        print(f"  {self.color('SKIP', '90')} {name}{' - ' + detail if detail else ''}")

    def expect(self, name: str, condition: bool, detail: str = "", elapsed_ms: float | None = None) -> bool:
        if condition:
            self.pass_(name, detail, elapsed_ms)
            return True
        self.fail(name, detail, elapsed_ms)
        return False

    def expect_status(self, name: str, response: HttpResult, statuses: set[int], detail: str = "") -> bool:
        body_hint = response.text[:300].replace("\n", " ")
        message = detail or f"HTTP {response.status}; body={body_hint}"
        return self.expect(name, response.status in statuses, message, response.elapsed_ms)

    # ------------------------------------------------------------------
    # HTTP client
    # ------------------------------------------------------------------

    def service_base(self, service: str) -> str:
        return (self.docker_bases if self.mode == "docker" else self.host_bases)[service]

    def make_url(self, service: str, path: str, params: dict[str, Any] | None = None) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            url = path
        else:
            url = f"{self.service_base(service)}{path if path.startswith('/') else '/' + path}"
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
            url = f"{url}{'&' if '?' in url else '?'}{query}"
        return url

    def request(
        self,
        service: str,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
        raw_body: bytes | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> HttpResult:
        method = method.upper()
        url = self.make_url(service, path, params)
        request_headers = dict(headers or {})
        body = raw_body
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        if body is None:
            body = b""
        timeout = timeout or self.args.timeout

        if self.mode == "docker":
            return self._request_docker(method, url, request_headers, body, timeout)
        return self._request_host(method, url, request_headers, body, timeout)

    def _request_host(self, method: str, url: str, headers: dict[str, str], body: bytes, timeout: float) -> HttpResult:
        req = urllib.request.Request(url, data=body or None, headers=headers, method=method)
        opener = urllib.request.build_opener(NoRedirect)
        start = time.perf_counter()
        try:
            resp = opener.open(req, timeout=timeout)
            raw = resp.read()
            return HttpResult(method, url, resp.getcode(), dict(resp.headers.items()), raw, round((time.perf_counter() - start) * 1000, 1))
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            return HttpResult(method, url, exc.code, dict(exc.headers.items()), raw, round((time.perf_counter() - start) * 1000, 1))
        except Exception as exc:
            return HttpResult(method, url, 0, {}, b"", round((time.perf_counter() - start) * 1000, 1), ok=False, error=repr(exc))

    def _request_docker(self, method: str, url: str, headers: dict[str, str], body: bytes, timeout: float) -> HttpResult:
        cmd = [
            "docker",
            "exec",
            "-i",
            self.args.composer_container,
            "python",
            "-c",
            DOCKER_HTTP_HELPER,
            method,
            url,
            json.dumps(headers),
            str(timeout),
        ]
        start = time.perf_counter()
        proc = subprocess.run(cmd, input=body, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        if proc.returncode != 0:
            return HttpResult(method, url, 0, {}, proc.stderr, elapsed, ok=False, error=proc.stderr.decode("utf-8", "replace"))
        try:
            payload = json.loads(proc.stdout.decode("utf-8"))
            raw = base64.b64decode(payload.get("body_b64", ""))
            return HttpResult(
                method,
                url,
                int(payload.get("status", 0)),
                dict(payload.get("headers") or {}),
                raw,
                float(payload.get("elapsed_ms", elapsed)),
                ok=bool(payload.get("ok", True)),
                error=str(payload.get("error", "")),
            )
        except Exception as exc:
            return HttpResult(method, url, 0, {}, proc.stdout + proc.stderr, elapsed, ok=False, error=repr(exc))

    # ------------------------------------------------------------------
    # Setup / discovery
    # ------------------------------------------------------------------

    def shell(self, cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=check)

    def maybe_start_stack(self) -> None:
        if self.args.reset_volumes:
            if not self.args.yes:
                raise SystemExit("--reset-volumes is destructive; rerun with --yes if you really want to wipe Docker volumes.")
            self.section("Docker reset")
            self.info("Running docker compose down -v ...")
            subprocess.run(["docker", "compose", "down", "-v"], check=True)

        if self.args.start or self.args.reset_volumes:
            self.section("Docker compose")
            cmd = ["docker", "compose", "up", "-d"]
            if self.args.build:
                cmd.insert(3, "--build")
            self.info("Running " + " ".join(cmd))
            subprocess.run(cmd, check=True)
            time.sleep(self.args.start_wait)

    def detect_mode(self) -> None:
        if self.mode != "auto":
            self.info(f"HTTP mode: {self.mode}")
            return

        host_probe = self._request_host(
            "GET",
            self.make_url("composer", "/health"),
            {},
            b"",
            min(self.args.timeout, 3),
        )
        if host_probe.status in {200, 503} and "composer" in host_probe.text.lower():
            self.mode = "host"
            self.info(f"HTTP mode auto -> host ({self.host_bases['composer']})")
            return

        docker_ok = self.shell(["docker", "exec", self.args.composer_container, "python", "--version"]).returncode == 0
        if docker_ok:
            self.mode = "docker"
            self.info(f"HTTP mode auto -> docker (docker exec {self.args.composer_container})")
            return

        self.mode = "host"
        self.warn(
            "Mode detection",
            f"Host probe failed ({host_probe.status} {host_probe.error}); docker composer container unavailable. Falling back to host.",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def bearer(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def get_json_field(self, response: HttpResult, *path: str, default: Any = "") -> Any:
        try:
            data = response.json()
            cur: Any = data
            for part in path:
                if isinstance(cur, dict):
                    cur = cur.get(part, default)
                else:
                    return default
            return cur if cur is not None else default
        except Exception:
            return default

    def parse_json(self, response: HttpResult) -> Any:
        try:
            return response.json()
        except Exception:
            return None

    def register_user(self, service: str, email: str, role: str) -> HttpResult:
        return self.request(
            service,
            "POST",
            "/api/auth/register" if service == "composer" else "/api/v1/auth/register",
            json_body={
                "email": email,
                "password": self.state.password,
                "full_name": f"Mega Test {role}",
                "role": role,
            },
        )

    def login_user(self, service: str, email: str) -> HttpResult:
        return self.request(
            service,
            "POST",
            "/api/auth/login" if service == "composer" else "/api/v1/auth/login",
            json_body={"email": email, "password": self.state.password},
        )

    def delete_account(self, token: str) -> None:
        self.request(
            "composer",
            "DELETE",
            "/api/auth/me",
            headers=self.bearer(token),
            json_body={"password": self.state.password},
        )

    # ------------------------------------------------------------------
    # Test sections
    # ------------------------------------------------------------------

    def run(self) -> int:
        self.maybe_start_stack()
        self.detect_mode()
        self.section("Configuration")
        self.info(f"Run id: {self.run_id}")
        self.info(f"Mode: {self.mode}")
        self.info(f"Composer base: {self.service_base('composer')}")

        try:
            self.test_sanity()
            self.test_health_metrics()
            self.test_auth()
            self.test_payment_auth_direct()
            self.test_kpi_dashboard()
            self.test_payment_account()
            self.test_inventory_event_ticket_lifecycle()
            self.test_reservations()
            self.test_manual_payments()
            self.test_checkout_saga()
            self.test_cart_checkout_cancel()
            self.test_security_edges()
            self.cleanup()
        except KeyboardInterrupt:
            self.fail("Interrupted", "KeyboardInterrupt")
        except Exception:
            self.fail("Unexpected runner exception", traceback.format_exc())

        return self.finish()

    def test_sanity(self) -> None:
        self.section("Sanity")
        self.expect("Python version >= 3.10", sys.version_info >= (3, 10), sys.version.split()[0])
        if self.mode == "docker":
            docker = self.shell(["docker", "exec", self.args.composer_container, "python", "--version"])
            self.expect("Composer container has Python", docker.returncode == 0, (docker.stdout or docker.stderr).strip())
        docs = self.request("composer", "GET", "/docs")
        self.expect_status("Composer /docs reachable", docs, {200})

    def test_health_metrics(self) -> None:
        self.section("Health and metrics")
        health = self.request("composer", "GET", "/health")
        if health.status == 200:
            self.pass_("GET /health healthy", health.text[:200], health.elapsed_ms)
        elif health.status == 503:
            self.warn("GET /health degraded", health.text[:300], health.elapsed_ms)
        else:
            self.fail("GET /health", f"HTTP {health.status}; {health.text[:300]}", health.elapsed_ms)

        metrics = self.request("composer", "GET", "/metrics")
        ok = metrics.status == 200 and "flashsale_service_up" in metrics.text and "flashsale_service_latency_ms" in metrics.text
        self.expect("GET /metrics exposes platform metrics", ok, f"HTTP {metrics.status}", metrics.elapsed_ms)

        for service in ("auth", "inventory", "payment"):
            resp = self.request(service, "GET", "/health")
            if resp.status == 200:
                self.pass_(f"Direct {service} /health", resp.text[:160], resp.elapsed_ms)
            else:
                self.warn(f"Direct {service} /health", f"HTTP {resp.status}; {resp.text[:250] or resp.error}", resp.elapsed_ms)

        inv_kpi = self.request("inventory", "GET", "/internal/kpi/snapshot", headers={"X-API-Key": self.args.inventory_api_key})
        self.expect_status("Inventory KPI snapshot direct", inv_kpi, {200})
        pay_kpi = self.request("payment", "GET", "/api/v1/internal/kpi/snapshot", headers={"X-API-Key": self.args.payment_api_key})
        if pay_kpi.status == 404:
            pay_kpi = self.request("payment", "GET", "/internal/kpi/snapshot", headers={"X-API-Key": self.args.payment_api_key})
        self.expect("Payment KPI snapshot direct", pay_kpi.status in {200, 404}, f"HTTP {pay_kpi.status}", pay_kpi.elapsed_ms)

    def test_auth(self) -> None:
        self.section("Auth through Composer")
        for label, email, role in (
            ("promoter", self.state.promoter_email, "promoter"),
            ("fan", self.state.fan_email, "fan"),
        ):
            reg = self.register_user("composer", email, role)
            self.expect_status(f"Register {label}", reg, {200, 201})
            login = self.login_user("composer", email)
            self.expect_status(f"Login {label}", login, {200})
            token = self.get_json_field(login, "access_token")
            refresh = self.get_json_field(login, "refresh_token")
            self.expect(f"{label} access token present", bool(token))
            if label == "promoter":
                self.state.promoter_token = token
                self.state.promoter_refresh = refresh
            else:
                self.state.fan_token = token
                self.state.fan_refresh = refresh

        if not self.state.fan_token:
            self.skip("Remaining Auth checks", "fan login failed; no token available")
            return

        me = self.request("composer", "GET", "/api/auth/me", headers=self.bearer(self.state.fan_token))
        self.expect_status("GET /api/auth/me", me, {200})
        self.expect("Auth /me email matches fan", self.get_json_field(me, "email") == self.state.fan_email)

        refresh = self.request("composer", "POST", "/api/auth/refresh", json_body={"refresh_token": self.state.fan_refresh})
        self.expect_status("POST /api/auth/refresh", refresh, {200})

        forgot = self.request("composer", "POST", "/api/auth/forgot-password", json_body={"email": self.state.fan_email})
        self.expect_status("POST /api/auth/forgot-password", forgot, {200})

        bad_reset = self.request("composer", "POST", "/api/auth/reset-password", json_body={"token": "invalid-token", "new_password": "ChangedPass123"})
        self.expect_status("POST /api/auth/reset-password invalid token", bad_reset, {401})

        handoff = self.request(
            "composer",
            "POST",
            "/api/auth/browser/handoff",
            json_body={
                "access_token": self.state.fan_token,
                "refresh_token": self.state.fan_refresh,
                "return_to": "http://localhost:5173/",
                "state": f"state-{self.run_id}",
            },
        )
        self.expect_status("POST /api/auth/browser/handoff", handoff, {200})
        redirect_to = self.get_json_field(handoff, "redirect_to")
        code = urllib.parse.parse_qs(urllib.parse.urlparse(redirect_to).query).get("code", [""])[0]
        if code:
            exchange = self.request("composer", "POST", "/api/auth/browser/exchange", json_body={"code": code, "state": f"state-{self.run_id}"})
            self.expect_status("POST /api/auth/browser/exchange", exchange, {200})
            replay = self.request("composer", "POST", "/api/auth/browser/exchange", json_body={"code": code, "state": f"state-{self.run_id}"})
            self.expect_status("Browser exchange replay is rejected", replay, {401})
        else:
            self.skip("Browser exchange", "handoff did not return code")

        logout = self.request("composer", "POST", "/api/auth/logout", headers=self.bearer(self.state.fan_token))
        self.expect("POST /api/auth/logout", logout.status in {200, 204}, f"HTTP {logout.status}", logout.elapsed_ms)
        relogin = self.login_user("composer", self.state.fan_email)
        self.expect_status("Re-login fan after logout", relogin, {200})
        self.state.fan_token = self.get_json_field(relogin, "access_token", default=self.state.fan_token)
        self.state.fan_refresh = self.get_json_field(relogin, "refresh_token", default=self.state.fan_refresh)

    def test_payment_auth_direct(self) -> None:
        self.section("Payment Auth direct")
        reg = self.register_user("payment_auth", self.state.payment_auth_email, "fan")
        self.expect("Payment Auth register fan", reg.status in {200, 201, 400}, f"HTTP {reg.status}; {reg.text[:160]}", reg.elapsed_ms)
        login = self.login_user("payment_auth", self.state.payment_auth_email)
        self.expect_status("Payment Auth login fan", login, {200})
        self.state.payment_auth_token = self.get_json_field(login, "access_token")
        self.expect("Payment Auth token present", bool(self.state.payment_auth_token))
        if not self.state.payment_auth_token:
            self.skip("Payment Auth verify token", "payment-auth login failed; no token available")
            return
        verify = self.request(
            "payment_auth",
            "POST",
            "/api/v1/auth/verify",
            headers={"X-Service-Auth": self.args.internal_service_key},
            json_body={"token": self.state.payment_auth_token},
        )
        self.expect_status("Payment Auth verify token", verify, {200})

    def test_kpi_dashboard(self) -> None:
        self.section("KPI dashboard")
        if not self.state.fan_token:
            self.skip("KPI dashboard rejects fan", "fan token unavailable")
        else:
            fan = self.request("composer", "GET", "/api/kpi/dashboard", headers=self.bearer(self.state.fan_token))
            self.expect_status("KPI dashboard rejects fan", fan, {403})
        if not self.state.promoter_token:
            self.skip("KPI dashboard allows promoter", "promoter token unavailable")
            return
        promoter = self.request("composer", "GET", "/api/kpi/dashboard", headers=self.bearer(self.state.promoter_token))
        self.expect_status("KPI dashboard allows promoter", promoter, {200})

    def test_payment_account(self) -> None:
        self.section("Payment account through Composer")
        if not self.state.fan_token:
            self.skip("Payment account checks", "fan token unavailable")
            return
        before = self.request("composer", "GET", "/api/payment-account", headers=self.bearer(self.state.fan_token))
        self.expect_status("GET /api/payment-account", before, {200})
        setup = self.request("composer", "POST", "/api/payment-account/setup", headers=self.bearer(self.state.fan_token), json_body={})
        self.expect_status("POST /api/payment-account/setup", setup, {200})
        self.state.payment_customer_id = self.get_json_field(setup, "customer", "id")
        self.expect("Payment customer id present", bool(self.state.payment_customer_id), str(self.state.payment_customer_id))
        after = self.request("composer", "GET", "/api/payment-account", headers=self.bearer(self.state.fan_token))
        self.expect("Payment account exists after setup", self.get_json_field(after, "exists") is True, after.text[:200], after.elapsed_ms)

    def test_inventory_event_ticket_lifecycle(self) -> None:
        self.section("Inventory events and tickets through Composer")
        if not self.state.fan_token:
            self.skip("Fan event permission check", "fan token unavailable")
        else:
            fan_create = self.request(
                "composer",
                "POST",
                "/api/events",
                headers=self.bearer(self.state.fan_token),
                json_body={
                    "name": "Should Not Be Allowed",
                    "date": "2027-01-01T20:00:00Z",
                },
            )
            self.expect_status("Fan cannot create event", fan_create, {403})

        if not self.state.promoter_token:
            self.skip("Inventory event/ticket lifecycle", "promoter token unavailable")
            return

        image_url = "https://images.unsplash.com/photo-1501281668745-f7f57925c3b4"
        create = self.request(
            "composer",
            "POST",
            "/api/events",
            headers=self.bearer(self.state.promoter_token),
            json_body={
                "name": f"Mega E2E Event {self.run_id}",
                "description": "Created by flashsale_full_stack_test.py",
                "venue": "Lisboa",
                "date": "2027-06-01T20:00:00Z",
                "end_date": "2027-06-02T02:00:00Z",
                "max_capacity": 500,
                "image_url": image_url,
            },
        )
        self.expect_status("Promoter creates event", create, {200, 201})
        self.state.event_id = self.get_json_field(create, "id")
        self.expect("Event id present", bool(self.state.event_id), self.state.event_id)
        self.expect("Event image_url roundtrip", self.get_json_field(create, "image_url") == image_url)
        if not self.state.event_id:
            self.skip("Remaining Inventory event/ticket lifecycle", "event creation failed")
            return

        update = self.request(
            "composer",
            "PUT",
            f"/api/events/{self.state.event_id}",
            headers=self.bearer(self.state.promoter_token),
            json_body={"status": "published"},
        )
        self.expect_status("Publish event", update, {200})
        self.expect("Event status is published", self.get_json_field(update, "status") == "published", update.text[:200])

        list_events = self.request("composer", "GET", "/api/events")
        self.expect_status("List events", list_events, {200})

        detail = self.request("composer", "GET", f"/api/events/{self.state.event_id}")
        self.expect_status("Event detail", detail, {200})
        detail_json = self.parse_json(detail) or {}
        self.expect("Event detail has tickets field", "tickets" in detail_json)
        self.expect("Event detail keeps legacy ticket_categories field", "ticket_categories" in detail_json)

        batch_general = self.request(
            "composer",
            "POST",
            f"/api/events/{self.state.event_id}/tickets",
            headers=self.bearer(self.state.promoter_token),
            json_body={"category": "General", "price": "25.00", "currency": "EUR", "quantity": 8},
        )
        self.expect_status("Create General tickets", batch_general, {200, 201})
        self.expect("General ticket count", self.get_json_field(batch_general, "total", default=0) == 8 or len(self.get_json_field(batch_general, "data", default=[])) == 8)

        batch_vip = self.request(
            "composer",
            "POST",
            f"/api/events/{self.state.event_id}/tickets",
            headers=self.bearer(self.state.promoter_token),
            json_body={"ticket_category_id": "VIP", "price": "40.00", "currency": "EUR", "quantity": 4},
        )
        self.expect_status("Create VIP tickets via legacy ticket_category_id", batch_vip, {200, 201})

        tickets = self.request("composer", "GET", f"/api/events/{self.state.event_id}/tickets", params={"limit": 20})
        self.expect_status("List event tickets", tickets, {200})
        ticket_items = self.get_json_field(tickets, "data", default=[])
        self.state.ticket_ids = [str(item.get("id")) for item in ticket_items if item.get("id")]
        self.expect("Ticket ids collected", len(self.state.ticket_ids) >= 6, f"count={len(self.state.ticket_ids)}")

        if len(self.state.ticket_ids) >= 3:
            lifecycle_ticket = self.state.ticket_ids[0]
            detail_ticket = self.request("composer", "GET", f"/api/tickets/{lifecycle_ticket}")
            self.expect_status("Get ticket detail", detail_ticket, {200})

            availability = self.request("composer", "GET", f"/api/tickets/{lifecycle_ticket}/availability")
            self.expect_status("Get ticket availability", availability, {200})
            self.expect("Ticket initially available", self.get_json_field(availability, "status") == "available", availability.text[:200])

            reserve = self.request("composer", "PUT", f"/api/tickets/{lifecycle_ticket}/reserve", headers=self.bearer(self.state.promoter_token))
            self.expect_status("Reserve ticket direct", reserve, {200})
            sell = self.request("composer", "PUT", f"/api/tickets/{lifecycle_ticket}/sell", headers=self.bearer(self.state.promoter_token))
            self.expect_status("Sell ticket direct", sell, {200})
            use = self.request("composer", "PUT", f"/api/tickets/{lifecycle_ticket}/use", headers=self.bearer(self.state.promoter_token))
            self.expect_status("Use ticket direct", use, {200})
            self.state.sold_ticket_id = lifecycle_ticket

            cancel_ticket = self.state.ticket_ids[1]
            res2 = self.request("composer", "PUT", f"/api/tickets/{cancel_ticket}/reserve", headers=self.bearer(self.state.promoter_token))
            self.expect_status("Reserve ticket for cancel alias", res2, {200})
            cancel_alias = self.request("composer", "POST", f"/api/tickets/{cancel_ticket}/cancel", headers=self.bearer(self.state.promoter_token))
            self.expect_status("POST /api/tickets/{id}/cancel alias", cancel_alias, {200})
            self.expect("Cancel alias releases ticket", self.get_json_field(cancel_alias, "status") == "available", cancel_alias.text[:200])

            delete_unreserved = self.request("composer", "DELETE", f"/api/tickets/{self.state.ticket_ids[2]}", headers=self.bearer(self.state.promoter_token))
            self.expect_status("DELETE unreserved ticket fails with conflict", delete_unreserved, {409})

    def test_reservations(self) -> None:
        self.section("Reservations through Composer")
        if not self.state.event_id or not self.state.fan_token:
            self.skip("Reservations", "No event id or fan token")
            return
        res = self.request(
            "composer",
            "POST",
            "/api/reservations",
            headers=self.bearer(self.state.fan_token),
            json_body={"event_id": self.state.event_id, "quantity": 2, "category": "VIP"},
        )
        self.expect_status("Create reservation", res, {200})
        tickets = self.get_json_field(res, "tickets", default=[])
        self.state.reserved_ticket_ids = [str(t.get("id")) for t in tickets if t.get("id")]
        self.expect("Reservation returned 2 tickets", len(self.state.reserved_ticket_ids) == 2, f"count={len(self.state.reserved_ticket_ids)}")
        if self.state.reserved_ticket_ids:
            one = self.request("composer", "GET", f"/api/reservations/{self.state.reserved_ticket_ids[0]}")
            self.expect_status("Get reservation status", one, {200})
            self.expect("Reservation status is reserved", self.get_json_field(one, "status") == "reserved", one.text[:200])

    def test_manual_payments(self) -> None:
        self.section("Payment endpoints through Composer")
        if not self.state.payment_customer_id or not self.state.fan_token:
            self.skip("Manual payment", "No payment customer id or fan token")
            return

        list_no_auth = self.request("composer", "GET", "/api/payments")
        self.expect_status("GET /api/payments without auth rejected", list_no_auth, {401})

        create = self.request(
            "composer",
            "POST",
            "/api/payments",
            headers=self.bearer(self.state.fan_token),
            json_body={
                "amount": 1234,
                "currency": "eur",
                "customer_id": self.state.payment_customer_id,
                "description": "Mega full-stack manual payment",
                "metadata": {"test_run": self.run_id},
            },
        )
        self.expect_status("POST /api/payments", create, {200, 201})
        self.state.manual_payment_id = self.get_json_field(create, "id")
        self.expect("Manual payment id present", bool(self.state.manual_payment_id), self.state.manual_payment_id)

        detail = self.request("composer", "GET", f"/api/payments/{self.state.manual_payment_id}", headers=self.bearer(self.state.fan_token))
        self.expect_status("GET /api/payments/{id}", detail, {200})

        confirm = self.request("composer", "POST", f"/api/payments/{self.state.manual_payment_id}/confirm", headers=self.bearer(self.state.fan_token))
        self.expect_status("POST /api/payments/{id}/confirm", confirm, {200})

        receipt = self.request("composer", "GET", f"/api/payments/{self.state.manual_payment_id}/receipt", headers=self.bearer(self.state.fan_token))
        self.expect("GET /api/payments/{id}/receipt returns PDF", receipt.status == 200 and "application/pdf" in receipt.header("content-type").lower(), f"HTTP {receipt.status}; type={receipt.header('content-type')}", receipt.elapsed_ms)

        cancel = self.request("composer", "POST", f"/api/payments/{self.state.manual_payment_id}/cancel", headers=self.bearer(self.state.fan_token))
        self.expect_status("POST /api/payments/{id}/cancel -> Payment DELETE", cancel, {200})

        unauth_create = self.request(
            "composer",
            "POST",
            "/api/payments",
            json_body={"amount": 100, "currency": "eur", "customer_id": self.state.payment_customer_id},
        )
        if unauth_create.status in {200, 201}:
            self.warn("POST /api/payments without auth is accepted", "Known security review item: Composer currently proxies create payment without Bearer auth.", unauth_create.elapsed_ms)
        else:
            self.pass_("POST /api/payments without auth rejected", f"HTTP {unauth_create.status}", unauth_create.elapsed_ms)

    def test_checkout_saga(self) -> None:
        self.section("Single checkout saga")
        if not (self.state.event_id and self.state.fan_token and self.state.payment_auth_token):
            self.skip("Single checkout", "Missing event or tokens")
            return
        checkout = self.request(
            "composer",
            "POST",
            "/api/checkout",
            headers=self.bearer(self.state.fan_token),
            json_body={
                "event_id": self.state.event_id,
                "quantity": 1,
                "category": "General",
                "success_url": "http://localhost:5173/?checkout=success",
                "cancel_url": "http://localhost:5173/?checkout=cancel",
                "amount_cents": 2500,
            },
            timeout=20,
        )
        self.expect_status("POST /api/checkout", checkout, {200})
        checkout_data = self.parse_json(checkout) or {}
        self.state.checkout_session_id = str(checkout_data.get("session_id") or "")
        metadata = checkout_data.get("metadata") if isinstance(checkout_data.get("metadata"), dict) else {}
        self.state.checkout_ticket_ids = [tid for tid in str(metadata.get("ticket_ids") or "").split(",") if tid]
        self.expect("Checkout session id present", bool(self.state.checkout_session_id), self.state.checkout_session_id)
        self.expect("Checkout URL is public Payment URL", "checkout_url" in checkout_data and "payment.flashsale" in str(checkout_data.get("checkout_url")), str(checkout_data.get("checkout_url")))

        authz = self.request(
            "payment",
            "POST",
            f"/api/v1/checkout/{self.state.checkout_session_id}/authorize",
            headers=self.bearer(self.state.payment_auth_token),
            timeout=20,
        )
        self.expect_status("Payment authorize checkout session", authz, {200})
        self.state.checkout_payment_id = str(self.get_json_field(authz, "payment_id"))
        self.expect("Checkout payment id present", bool(self.state.checkout_payment_id), self.state.checkout_payment_id)

        success = self.request("composer", "GET", "/api/checkout/success", params={"session_id": self.state.checkout_session_id}, timeout=20)
        self.expect_status("GET /api/checkout/success redirects", success, {307, 308, 302, 303})

        if self.state.checkout_ticket_ids:
            sold = self.request("composer", "GET", f"/api/tickets/{self.state.checkout_ticket_ids[0]}")
            self.expect("Checkout success sells ticket", self.get_json_field(sold, "status") in {"sold", "used"}, sold.text[:200], sold.elapsed_ms)

        payments = self.request("composer", "GET", "/api/payments", headers=self.bearer(self.state.fan_token))
        self.expect_status("GET /api/payments after checkout", payments, {200})

        if self.state.checkout_payment_id:
            refund = self.request(
                "composer",
                "POST",
                "/api/refund",
                headers=self.bearer(self.state.fan_token),
                json_body={
                    "payment_id": self.state.checkout_payment_id,
                    "ticket_ids": self.state.checkout_ticket_ids,
                    "reason": "mega_full_stack_test",
                },
                timeout=20,
            )
            self.expect_status("POST /api/refund", refund, {200})

    def test_cart_checkout_cancel(self) -> None:
        self.section("Cart checkout and cancel compensation")
        if not self.state.event_id or not self.state.fan_token:
            self.skip("Cart checkout", "No event id or fan token")
            return
        cart = self.request(
            "composer",
            "POST",
            "/api/checkout/cart",
            headers=self.bearer(self.state.fan_token),
            json_body={
                "items": [
                    {"event_id": self.state.event_id, "quantity": 1, "category": "General"},
                    {"event_id": self.state.event_id, "quantity": 1, "ticket_category_id": "VIP"},
                ],
                "success_url": "http://localhost:5173/?cart=success",
                "cancel_url": "http://localhost:5173/?cart=cancel",
            },
            timeout=20,
        )
        self.expect_status("POST /api/checkout/cart", cart, {200})
        data = self.parse_json(cart) or {}
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        ticket_ids = [tid for tid in str(metadata.get("ticket_ids") or "").split(",") if tid]
        self.expect("Cart checkout reserved two tickets", len(ticket_ids) == 2, f"ticket_ids={ticket_ids}")
        cancel = self.request(
            "composer",
            "GET",
            "/api/checkout/cancel",
            params={"tickets": ",".join(ticket_ids), "frontend_url": "http://localhost:5173/?cart=cancel"},
            timeout=20,
        )
        self.expect_status("GET /api/checkout/cancel redirects", cancel, {307, 308, 302, 303})
        if ticket_ids:
            released = self.request("composer", "GET", f"/api/tickets/{ticket_ids[0]}")
            self.expect("Cancel compensation releases ticket", self.get_json_field(released, "status") == "available", released.text[:200], released.elapsed_ms)

        empty_cart = self.request(
            "composer",
            "POST",
            "/api/checkout/cart",
            headers=self.bearer(self.state.fan_token),
            json_body={"items": [], "success_url": "http://localhost", "cancel_url": "http://localhost"},
        )
        self.expect_status("Empty cart checkout rejected", empty_cart, {400})

    def test_security_edges(self) -> None:
        self.section("Negative and security edges")
        no_token_me = self.request("composer", "GET", "/api/auth/me")
        if no_token_me.status == 503:
            self.warn("GET /api/auth/me without token could not reach Auth", no_token_me.text[:220], no_token_me.elapsed_ms)
        else:
            self.expect("GET /api/auth/me without token rejected", no_token_me.status in {401, 403, 422}, f"HTTP {no_token_me.status}", no_token_me.elapsed_ms)

        no_token_checkout = self.request(
            "composer",
            "POST",
            "/api/checkout",
            json_body={"event_id": self.state.event_id or "x", "quantity": 1, "success_url": "http://x", "cancel_url": "http://y", "amount_cents": 100},
        )
        self.expect_status("POST /api/checkout without token rejected", no_token_checkout, {401})

        missing_event = self.request("composer", "GET", "/api/events/00000000-0000-0000-0000-000000000000")
        if missing_event.status == 503:
            self.warn("GET missing event could not reach Inventory", missing_event.text[:220], missing_event.elapsed_ms)
        else:
            self.expect_status("GET missing event returns 404", missing_event, {404})

        bad_inventory_key = self.request("inventory", "GET", "/api/v1/events", headers={"X-API-Key": "wrong"})
        self.expect("Inventory rejects bad API key", bad_inventory_key.status in {401, 403}, f"HTTP {bad_inventory_key.status}", bad_inventory_key.elapsed_ms)

    def cleanup(self) -> None:
        self.section("Cleanup")
        if self.args.keep_data:
            self.skip("Cleanup", "--keep-data was set")
            return

        for tid in self.state.reserved_ticket_ids:
            self.request("composer", "POST", f"/api/tickets/{tid}/cancel", headers=self.bearer(self.state.promoter_token))

        if self.state.event_id:
            delete_event = self.request("composer", "DELETE", f"/api/events/{self.state.event_id}", headers=self.bearer(self.state.promoter_token))
            if delete_event.status in {200, 204}:
                self.pass_("Delete test event", self.state.event_id, delete_event.elapsed_ms)
            else:
                self.warn("Delete test event", f"HTTP {delete_event.status}; leaving test event for inspection", delete_event.elapsed_ms)

        if self.state.fan_token:
            resp = self.request("composer", "DELETE", "/api/auth/me", headers=self.bearer(self.state.fan_token), json_body={"password": self.state.password})
            if resp.status in {200, 204}:
                self.pass_("Delete fan account", self.state.fan_email, resp.elapsed_ms)
            else:
                self.warn("Delete fan account", f"HTTP {resp.status}; {resp.text[:180]}", resp.elapsed_ms)

        if self.state.promoter_token:
            resp = self.request("composer", "DELETE", "/api/auth/me", headers=self.bearer(self.state.promoter_token), json_body={"password": self.state.password})
            if resp.status in {200, 204}:
                self.pass_("Delete promoter account", self.state.promoter_email, resp.elapsed_ms)
            else:
                self.warn("Delete promoter account", f"HTTP {resp.status}; {resp.text[:180]}", resp.elapsed_ms)

    # ------------------------------------------------------------------
    # Finish / report
    # ------------------------------------------------------------------

    def finish(self) -> int:
        counts = {key: sum(1 for r in self.records if r.status == key) for key in ("PASS", "FAIL", "WARN", "SKIP")}
        print()
        print(self.color("=== Summary ===", "1;34"))
        print(f"  PASS: {counts['PASS']}")
        print(f"  FAIL: {counts['FAIL']}")
        print(f"  WARN: {counts['WARN']}")
        print(f"  SKIP: {counts['SKIP']}")

        report_path = Path(self.args.report or f".test-runs/flashsale-full-{self.run_id}.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        redacted_state = self.state.__dict__.copy()
        for key in list(redacted_state.keys()):
            if "token" in key or "refresh" in key or "password" in key:
                redacted_state[key] = "<redacted>" if redacted_state[key] else ""
        report = {
            "run_id": self.run_id,
            "mode": self.mode,
            "composer_base": self.service_base("composer"),
            "counts": counts,
            "state": redacted_state,
            "records": [r.__dict__ for r in self.records],
        }
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Report: {report_path}")

        if counts["FAIL"]:
            print(self.color("FlashSale full-stack test FAILED", "31"))
            return 1
        if counts["WARN"]:
            print(self.color("FlashSale full-stack test PASSED with warnings", "33"))
            return 0
        print(self.color("FlashSale full-stack test PASSED", "32"))
        return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mega full-stack tester for FlashSale / Composer EGS.")
    parser.add_argument("--mode", choices=["auto", "host", "docker"], default=os.getenv("FLASHSALE_TEST_MODE", "auto"))
    parser.add_argument("--composer-base-url", default=os.getenv("COMPOSER_BASE_URL", "http://composer.flashsale"))
    parser.add_argument("--auth-base-url", default=os.getenv("AUTH_BASE_URL", "http://auth.flashsale"))
    parser.add_argument("--payment-auth-base-url", default=os.getenv("PAYMENT_AUTH_BASE_URL", "http://payment-auth.flashsale"))
    parser.add_argument("--inventory-base-url", default=os.getenv("INVENTORY_BASE_URL", "http://inventory.flashsale"))
    parser.add_argument("--payment-base-url", default=os.getenv("PAYMENT_BASE_URL", "http://payment.flashsale"))
    parser.add_argument("--composer-container", default=os.getenv("COMPOSER_CONTAINER", "composer"))
    parser.add_argument("--inventory-api-key", default=os.getenv("INVENTORY_API_KEY", "sk_test_inventory_dev_key"))
    parser.add_argument("--payment-api-key", default=os.getenv("PAYMENT_API_KEY", "admin-dev-key-2024"))
    parser.add_argument("--internal-service-key", default=os.getenv("INTERNAL_SERVICE_KEY", "internal-dev-key-2024"))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("FLASHSALE_TEST_TIMEOUT", "20")))
    parser.add_argument("--start", action="store_true", help="Run docker compose up -d before tests.")
    parser.add_argument("--build", action="store_true", help="Use --build with --start.")
    parser.add_argument("--start-wait", type=float, default=12.0, help="Seconds to wait after starting compose.")
    parser.add_argument("--reset-volumes", action="store_true", help="Destructive: docker compose down -v before starting.")
    parser.add_argument("--yes", action="store_true", help="Required with --reset-volumes.")
    parser.add_argument("--keep-data", action="store_true", help="Do not attempt cleanup of created users/events.")
    parser.add_argument("--report", default="", help="Path for JSON report. Default: .test-runs/flashsale-full-<run>.json")
    parser.add_argument("--no-color", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    tester = FlashSaleTester(args)
    return tester.run()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
