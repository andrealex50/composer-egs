import os
import time
import uuid

import httpx
import urllib.parse
from fastapi import FastAPI, HTTPException, Header, Request, Response, status
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration via environment variables
# ---------------------------------------------------------------------------
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://auth-service:8000")
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://inventory-service:8000")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://payment-service:8000")
PAYMENT_PUBLIC_URL = os.getenv("PAYMENT_PUBLIC_URL", "http://localhost:8002")
INVENTORY_API_KEY = os.getenv("INVENTORY_API_KEY", "your-secret-api-key")
PAYMENT_API_KEY = os.getenv("PAYMENT_API_KEY", "your-secret-api-key")
INTERNAL_SERVICE_KEY = os.getenv("INTERNAL_SERVICE_KEY", "internal-dev-key-2024")
COMPOSER_CORS_ORIGINS = os.getenv(
    "COMPOSER_CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5500,http://127.0.0.1:5500",
)
COMPOSER_BROWSER_RETURN_TO_ORIGINS = os.getenv(
    "COMPOSER_BROWSER_RETURN_TO_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
)
BROWSER_HANDOFF_TTL_SECONDS = max(30, int(os.getenv("BROWSER_HANDOFF_TTL_SECONDS", "120")))
EVENT_MUTATIONS_REQUIRE_ADMIN = os.getenv("EVENT_MUTATIONS_REQUIRE_ADMIN", "false").lower() in {"1", "true", "yes"}
EVENT_ADMIN_ROLES = {
    role.strip().lower()
    for role in os.getenv("EVENT_ADMIN_ROLES", "admin").split(",")
    if role.strip()
}
TRACE_HEADER_NAMES = ("X-Request-ID", "X-Correlation-ID")
_BROWSER_HANDOFF_CODES: dict[str, dict] = {}


def _parse_origins(origins: str) -> list[str]:
    return [item.strip().rstrip("/") for item in origins.split(",") if item.strip()]


def _normalize_origin(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


ALLOWED_BROWSER_RETURN_TO_ORIGINS = {
    origin
    for origin in (
        _normalize_origin(item)
        for item in _parse_origins(COMPOSER_BROWSER_RETURN_TO_ORIGINS)
    )
    if origin
}

app = FastAPI(
    title="FlashSale — Composer / API Gateway",
    description=(
        "Orquestrador central da arquitetura SOA FlashSale. "
        "Agrega Auth, Inventory e Payment num único ponto de entrada."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — necessário para o frontend React
app.add_middleware(
    CORSMiddleware,
    allow_origins=_parse_origins(COMPOSER_CORS_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Helper — proxy genérico reutilizável
# ---------------------------------------------------------------------------

async def proxy(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    json: dict | None = None,
    body: bytes | None = None,
    params: dict | None = None,
    timeout: float = 10.0,
    service_label: str = "serviço",
    request: Request | None = None,
) -> dict | bytes:
    """Faz proxy de um pedido para um serviço interno e devolve a resposta."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.request(
                method, url,
                headers=_with_trace_headers(headers, request),
                json=json,
                content=body,
                params=params,
            )
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail=f"{service_label} indisponível")
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail=f"{service_label} timeout")
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail=f"{service_label} erro: {exc}")

        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text or f"Erro {resp.status_code}"
            raise HTTPException(status_code=resp.status_code, detail=detail)

        # Receipt endpoint devolve PDF (binário)
        content_type = resp.headers.get("content-type", "")
        if "application/pdf" in content_type:
            return resp.content

        # Resposta vazia (ex: 204 No Content)
        if not resp.content:
            return {}

        try:
            return resp.json()
        except Exception:
            return {"raw": resp.text}


def _auth_headers(authorization: str | None) -> dict:
    """Headers com o token do utilizador para o Auth Service."""
    h: dict = {}
    if authorization:
        h["Authorization"] = authorization
    return h


def _with_trace_headers(headers: dict | None = None, request: Request | None = None) -> dict:
    merged = dict(headers or {})
    if request is not None:
        for header_name in TRACE_HEADER_NAMES:
            header_value = request.headers.get(header_name)
            if header_value:
                merged[header_name] = header_value
    return merged


def _extract_bearer_token(authorization: str | None) -> str | None:
    """Extrai o token Bearer do header Authorization."""
    if not authorization:
        return None
    if not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    return token or None


def _normalize_email(value: str | None) -> str:
    return str(value or "").strip().lower()


def _cleanup_browser_handoff_codes() -> None:
    now = time.time()
    expired_codes = [
        code
        for code, payload in _BROWSER_HANDOFF_CODES.items()
        if payload.get("expires_at", 0) <= now
    ]
    for code in expired_codes:
        _BROWSER_HANDOFF_CODES.pop(code, None)


def _validate_browser_return_to(return_to: str) -> str:
    parsed = urllib.parse.urlparse(return_to)
    origin = _normalize_origin(return_to)
    if not origin or origin not in ALLOWED_BROWSER_RETURN_TO_ORIGINS:
        raise HTTPException(status_code=400, detail="return_to não permitido")
    if parsed.fragment:
        raise HTTPException(status_code=400, detail="return_to inválido")
    cleaned = parsed._replace(params="", fragment="")
    return urllib.parse.urlunparse(cleaned)


def _append_query_params(url: str, params: dict[str, str]) -> str:
    parsed = urllib.parse.urlparse(url)
    merged_query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    merged_query.update(params)
    return urllib.parse.urlunparse(
        parsed._replace(query=urllib.parse.urlencode(merged_query))
    )


async def _verify_user_token(token: str, request: Request | None = None) -> dict:
    """Valida token no Auth Service e devolve claims essenciais."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{AUTH_SERVICE_URL}/api/v1/auth/verify",
            headers=_with_trace_headers({"X-Service-Auth": INTERNAL_SERVICE_KEY}, request),
            json={"token": token},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Não autorizado")
    payload = resp.json()
    if not payload.get("valid"):
        raise HTTPException(status_code=401, detail="Token inválido")
    return payload


async def _ensure_event_admin_if_required(authorization: str | None, request: Request | None = None) -> dict | None:
    """Valida role admin para mutações de eventos quando a política está ativa."""
    token = _extract_bearer_token(authorization)
    if not EVENT_MUTATIONS_REQUIRE_ADMIN:
        if not token:
            return None
        try:
            return await _verify_user_token(token, request)
        except HTTPException:
            # Em modo compatível, não bloqueia mutação se token inválido/ausente.
            return None

    if not token:
        raise HTTPException(status_code=401, detail="Token em falta para mutações de eventos")

    claims = await _verify_user_token(token, request)
    role = str(claims.get("role") or "").lower()
    if role not in EVENT_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Apenas admins podem alterar eventos")
    return claims


def _inv_headers(
    authorization: str | None = None,
    *,
    auth_claims: dict | None = None,
    idempotency_key: str | None = None,
    request: Request | None = None,
) -> dict:
    """Headers para Inventory: API key + contexto opcional do utilizador."""
    h: dict = {"X-API-Key": INVENTORY_API_KEY}
    if authorization:
        h["Authorization"] = authorization
    if idempotency_key:
        h["Idempotency-Key"] = idempotency_key
    if auth_claims:
        if auth_claims.get("user_id"):
            h["X-User-Id"] = str(auth_claims["user_id"])
        if auth_claims.get("role"):
            h["X-User-Role"] = str(auth_claims["role"])
        if auth_claims.get("email"):
            h["X-User-Email"] = str(auth_claims["email"])
    return _with_trace_headers(h, request)


def _pay_headers(idempotency_key: str | None = None, request: Request | None = None) -> dict:
    """Headers de autenticação para o Payment Service."""
    h: dict = {"X-API-Key": PAYMENT_API_KEY}
    if idempotency_key:
        h["Idempotency-Key"] = idempotency_key
    return _with_trace_headers(h, request)


async def _get_authenticated_claims(authorization: str | None, request: Request | None = None) -> dict:
    """Garante autenticação e devolve claims normalizados do utilizador."""
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Token em falta")
    claims = await _verify_user_token(token, request)
    email = _normalize_email(claims.get("email"))
    if not email:
        raise HTTPException(status_code=401, detail="Token inválido")
    claims["_normalized_email"] = email
    return claims


async def _get_authenticated_user_profile(authorization: str | None, request: Request | None = None) -> dict:
    """Obtém claims e perfil do Auth Service para o utilizador autenticado."""
    claims = await _get_authenticated_claims(authorization, request)
    profile = await proxy(
        "GET",
        f"{AUTH_SERVICE_URL}/api/v1/auth/me",
        headers=_auth_headers(authorization),
        service_label="Auth Service",
        request=request,
    )
    profile["_normalized_email"] = claims["_normalized_email"]
    profile.setdefault("email", claims.get("email"))
    profile.setdefault("role", claims.get("role"))
    profile.setdefault("id", claims.get("user_id"))
    return profile


async def _find_payment_customer_by_email(email: str, request: Request | None = None) -> dict | None:
    """Resolve customer do Payment Service por email (match case-insensitive)."""
    payload = await proxy(
        "GET",
        f"{PAYMENT_SERVICE_URL}/api/v1/customers",
        headers=_pay_headers(request=request),
        params={"email": email, "limit": 20, "offset": 0},
        service_label="Payment Service",
        request=request,
    )
    items = payload.get("items", []) if isinstance(payload, dict) else []
    for item in items:
        item_email = str(item.get("email") or "").strip().lower()
        if item_email == email:
            return item
    return items[0] if items else None


def _build_payment_customer_payload(profile: dict) -> dict:
    """Cria payload idempotente para provisionar customer local no Payment Service."""
    metadata = {
        "source": "composer",
        "auth_user_id": str(profile.get("id") or ""),
        "auth_role": str(profile.get("role") or ""),
    }
    metadata = {key: value for key, value in metadata.items() if value}

    payload = {
        "email": profile.get("email"),
        "name": profile.get("full_name") or None,
        "metadata": metadata or None,
    }
    return {key: value for key, value in payload.items() if value is not None}


async def _cancel_reserved_ticket(
    client: httpx.AsyncClient,
    ticket_id: str,
    inv_headers: dict,
    *,
    service_label: str,
) -> bool:
    """Cancela reserva de bilhete e valida resposta para evitar falhas silenciosas."""
    resp = await client.delete(
        f"{INVENTORY_SERVICE_URL}/api/v1/tickets/{ticket_id}",
        headers=inv_headers,
    )
    if resp.status_code in (200, 201):
        return True
    if resp.status_code in (404, 409):
        return False
    raise HTTPException(status_code=502, detail=f"{service_label}: erro ao cancelar ticket {ticket_id}")


# ---------------------------------------------------------------------------
# Schemas de entrada para orquestrações compostas
# ---------------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    event_id: str
    quantity: int = 1
    ticket_category_id: Optional[str] = None
    success_url: str
    cancel_url: str
    amount_cents: int


class RefundRequest(BaseModel):
    payment_id: str
    ticket_ids: list[str] = []
    reason: Optional[str] = "requested_by_customer"


class BrowserHandoffRequest(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    return_to: str
    state: str


class BrowserHandoffExchangeRequest(BaseModel):
    code: str
    state: str


# ═══════════════════════════════════════════════════════════════════════════
# 1. AUTH  —  /api/auth/*
#    Backend: AUTH_SERVICE /api/v1/auth/*
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/auth/register", summary="Registar novo utilizador", tags=["Auth"])
async def auth_register(request: Request):
    body = await request.json()
    return await proxy("POST", f"{AUTH_SERVICE_URL}/api/v1/auth/register",
                        json=body, service_label="Auth Service", request=request)


@app.post("/api/auth/login", summary="Login (JWT)", tags=["Auth"])
async def auth_login(request: Request):
    body = await request.json()
    return await proxy("POST", f"{AUTH_SERVICE_URL}/api/v1/auth/login",
                        json=body, service_label="Auth Service", request=request)


@app.post("/api/auth/refresh", summary="Renovar access token", tags=["Auth"])
async def auth_refresh(request: Request):
    body = await request.json()
    return await proxy("POST", f"{AUTH_SERVICE_URL}/api/v1/auth/refresh",
                        json=body, service_label="Auth Service", request=request)


@app.get("/api/auth/me", summary="Perfil do utilizador autenticado", tags=["Auth"])
async def auth_me(request: Request, authorization: Optional[str] = Header(None)):
    return await proxy("GET", f"{AUTH_SERVICE_URL}/api/v1/auth/me",
                        headers=_auth_headers(authorization),
                        service_label="Auth Service",
                        request=request)


@app.post("/api/auth/logout", summary="Logout", tags=["Auth"])
async def auth_logout(request: Request, authorization: Optional[str] = Header(None)):
    return await proxy("POST", f"{AUTH_SERVICE_URL}/api/v1/auth/logout",
                        headers=_auth_headers(authorization),
                        service_label="Auth Service",
                        request=request)


@app.post("/api/auth/forgot-password", summary="Solicitar reset de password", tags=["Auth"])
async def auth_forgot_password(request: Request):
    body = await request.json()
    return await proxy(
        "POST",
        f"{AUTH_SERVICE_URL}/api/v1/auth/forgot-password",
        json=body,
        service_label="Auth Service",
        request=request,
    )


@app.post("/api/auth/reset-password", summary="Aplicar nova password com token", tags=["Auth"])
async def auth_reset_password(request: Request):
    body = await request.json()
    return await proxy(
        "POST",
        f"{AUTH_SERVICE_URL}/api/v1/auth/reset-password",
        json=body,
        service_label="Auth Service",
        request=request,
    )


@app.delete("/api/auth/me", summary="Eliminar conta autenticada", tags=["Auth"])
async def auth_delete_me(request: Request, authorization: Optional[str] = Header(None)):
    body = await request.json()
    return await proxy(
        "DELETE",
        f"{AUTH_SERVICE_URL}/api/v1/auth/me",
        headers=_auth_headers(authorization),
        json=body,
        service_label="Auth Service",
        request=request,
    )


@app.post("/api/auth/browser/handoff", summary="Criar handoff one-time para login browser", tags=["Auth"])
async def auth_browser_handoff(payload: BrowserHandoffRequest, request: Request):
    access_token = payload.access_token.strip()
    state = payload.state.strip()
    if not access_token:
        raise HTTPException(status_code=422, detail="access_token é obrigatório")
    if not state or len(state) > 256:
        raise HTTPException(status_code=422, detail="state inválido")

    claims = await _verify_user_token(access_token, request)
    return_to = _validate_browser_return_to(payload.return_to.strip())

    _cleanup_browser_handoff_codes()
    code = uuid.uuid4().hex
    _BROWSER_HANDOFF_CODES[code] = {
        "access_token": access_token,
        "refresh_token": payload.refresh_token.strip() if payload.refresh_token else None,
        "state": state,
        "return_to": return_to,
        "expires_at": time.time() + BROWSER_HANDOFF_TTL_SECONDS,
        "user": {
            "user_id": claims.get("user_id"),
            "email": claims.get("email"),
            "role": claims.get("role"),
        },
    }
    redirect_to = _append_query_params(
        return_to,
        {
            "auth_callback": "1",
            "code": code,
            "state": state,
        },
    )
    return {
        "redirect_to": redirect_to,
        "expires_in_seconds": BROWSER_HANDOFF_TTL_SECONDS,
    }


@app.post("/api/auth/browser/exchange", summary="Trocar código one-time por sessão local", tags=["Auth"])
async def auth_browser_exchange(payload: BrowserHandoffExchangeRequest, request: Request):
    code = payload.code.strip()
    state = payload.state.strip()
    if not code or not state:
        raise HTTPException(status_code=422, detail="code e state são obrigatórios")

    _cleanup_browser_handoff_codes()
    handoff = _BROWSER_HANDOFF_CODES.pop(code, None)
    if not handoff:
        raise HTTPException(status_code=401, detail="Código de login inválido ou expirado")
    if handoff.get("state") != state:
        raise HTTPException(status_code=401, detail="State inválido")

    claims = await _verify_user_token(handoff["access_token"], request)
    return {
        "access_token": handoff["access_token"],
        "refresh_token": handoff.get("refresh_token"),
        "user": {
            "user_id": claims.get("user_id"),
            "email": claims.get("email"),
            "role": claims.get("role"),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# 2. EVENTS  —  /api/events
#    Backend: INVENTORY_SERVICE /api/v1/events
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/events", summary="Listar eventos", tags=["Events"])
async def list_events(request: Request):
    # Passa todos os query params para o Inventory (skip, limit, status, search, etc.)
    return await proxy("GET", f"{INVENTORY_SERVICE_URL}/api/v1/events",
                        headers=_inv_headers(request=request),
                        params=dict(request.query_params),
                        service_label="Inventory Service",
                        request=request)


@app.post("/api/events", summary="Criar evento", tags=["Events"])
async def create_event(request: Request, authorization: Optional[str] = Header(None)):
    body = await request.json()
    claims = await _ensure_event_admin_if_required(authorization, request)
    return await proxy("POST", f"{INVENTORY_SERVICE_URL}/api/v1/events",
                        headers=_inv_headers(authorization, auth_claims=claims, idempotency_key=str(uuid.uuid4()), request=request),
                        json=body, service_label="Inventory Service", request=request)


@app.get("/api/events/{event_id}", summary="Detalhes do evento", tags=["Events"])
async def get_event(event_id: str, request: Request):
    # Composer bonus: junta as categorias de bilhetes ao evento
    event_data = await proxy("GET", f"{INVENTORY_SERVICE_URL}/api/v1/events/{event_id}",
                              headers=_inv_headers(request=request),
                              service_label="Inventory Service",
                              request=request)

    try:
        tickets = await proxy("GET", f"{INVENTORY_SERVICE_URL}/api/v1/events/{event_id}/tickets",
                               headers=_inv_headers(request=request),
                               service_label="Inventory Service",
                               request=request)
        if isinstance(tickets, dict):
            event_data["ticket_categories"] = tickets.get("data", [])
    except HTTPException:
        pass

    return event_data


@app.put("/api/events/{event_id}", summary="Atualizar evento", tags=["Events"])
async def update_event(event_id: str, request: Request, authorization: Optional[str] = Header(None)):
    body = await request.json()
    claims = await _ensure_event_admin_if_required(authorization, request)
    return await proxy("PUT", f"{INVENTORY_SERVICE_URL}/api/v1/events/{event_id}",
                        headers=_inv_headers(authorization, auth_claims=claims, idempotency_key=str(uuid.uuid4()), request=request),
                        json=body, service_label="Inventory Service", request=request)


@app.delete("/api/events/{event_id}", summary="Apagar evento", tags=["Events"])
async def delete_event(event_id: str, request: Request, authorization: Optional[str] = Header(None)):
    claims = await _ensure_event_admin_if_required(authorization, request)
    return await proxy("DELETE", f"{INVENTORY_SERVICE_URL}/api/v1/events/{event_id}",
                        headers=_inv_headers(authorization, auth_claims=claims, idempotency_key=str(uuid.uuid4()), request=request),
                        service_label="Inventory Service",
                        request=request)


# ═══════════════════════════════════════════════════════════════════════════
# 3. TICKETS  —  /api/events/{id}/tickets  &  /api/tickets/{id}
#    Backend: INVENTORY_SERVICE /api/v1/events/{id}/tickets
#             INVENTORY_SERVICE /api/v1/tickets/{id}
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/events/{event_id}/tickets", summary="Criar bilhetes (batch)", tags=["Tickets"])
async def create_tickets(event_id: str, request: Request, authorization: Optional[str] = Header(None)):
    body = await request.json()
    claims = await _ensure_event_admin_if_required(authorization, request)
    return await proxy("POST", f"{INVENTORY_SERVICE_URL}/api/v1/events/{event_id}/tickets",
                        headers=_inv_headers(authorization, auth_claims=claims, idempotency_key=str(uuid.uuid4()), request=request),
                        json=body, service_label="Inventory Service", request=request)


@app.get("/api/events/{event_id}/tickets", summary="Listar bilhetes de um evento", tags=["Tickets"])
async def list_event_tickets(event_id: str, request: Request):
    return await proxy("GET", f"{INVENTORY_SERVICE_URL}/api/v1/events/{event_id}/tickets",
                        headers=_inv_headers(request=request),
                        params=dict(request.query_params),
                        service_label="Inventory Service",
                        request=request)


@app.get("/api/tickets/{ticket_id}/availability", summary="Disponibilidade do bilhete", tags=["Tickets"])
async def ticket_availability(ticket_id: str, request: Request):
    """Proxy para GET /api/v1/tickets/{ticket_id} — devolve o estado atual do bilhete."""
    return await proxy("GET", f"{INVENTORY_SERVICE_URL}/api/v1/tickets/{ticket_id}",
                        headers=_inv_headers(request=request),
                        service_label="Inventory Service",
                        request=request)


# ═══════════════════════════════════════════════════════════════════════════
# 4. RESERVATIONS  —  /api/reservations
#    Backend: Inventory NÃO tem /reservations. Reservas = operações sobre tickets:
#      - Criar reserva   → GET /api/v1/events/{event_id}/tickets + PUT /api/v1/tickets/{ticket_id}/reserve
#      - Confirmar       → PUT /api/v1/tickets/{ticket_id}/sell
#      - Cancelar        → DELETE /api/v1/tickets/{ticket_id}
#      - Ver reserva      → GET  /api/v1/tickets/{ticket_id}  (status=reserved)
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/reservations", summary="Reservar bilhetes", tags=["Reservations"])
async def create_reservation(request: Request, authorization: Optional[str] = Header(None)):
    body = await request.json()
    event_id = body.get("event_id")
    quantity = body.get("quantity", 1)
    if not event_id:
        raise HTTPException(status_code=422, detail="event_id é obrigatório")

    inv_headers = _inv_headers(authorization, idempotency_key=str(uuid.uuid4()), request=request)

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Procurar bilhetes disponíveis
        res = await client.get(
            f"{INVENTORY_SERVICE_URL}/api/v1/events/{event_id}/tickets",
            params={"status": "available", "limit": max(100, quantity * 2)},
            headers=inv_headers
        )
        if res.status_code != 200:
            raise HTTPException(status_code=500, detail="Erro no Inventory Service")
        
        available = res.json().get("data", [])
        
        if body.get("ticket_category_id"):
            cat_id = body["ticket_category_id"]
            available = [t for t in available if t.get("ticket_category_id") == cat_id]
            
        if len(available) < quantity:
            raise HTTPException(status_code=409, detail="Não existem bilhetes suficientes")
        
        reserved_tickets = []
        for t in available[:quantity]:
            r = await client.put(f"{INVENTORY_SERVICE_URL}/api/v1/tickets/{t['id']}/reserve", headers=inv_headers)
            if r.status_code == 200:
                reserved_tickets.append(r.json())
        
        if len(reserved_tickets) < quantity:
            for rt in reserved_tickets:
                await _cancel_reserved_ticket(
                    client,
                    rt["id"],
                    inv_headers,
                    service_label="Inventory Service",
                )
            raise HTTPException(status_code=409, detail="Concorrência: Falha ao reservar")
            
        return {"tickets": reserved_tickets}


@app.get("/api/reservations/{ticket_id}", summary="Ver estado da reserva", tags=["Reservations"])
async def get_reservation(ticket_id: str, request: Request):
    """Proxy para GET /api/v1/tickets/{ticket_id} — devolve o bilhete (inclui status de reserva)."""
    return await proxy("GET", f"{INVENTORY_SERVICE_URL}/api/v1/tickets/{ticket_id}",
                        headers=_inv_headers(request=request),
                        service_label="Inventory Service",
                        request=request)


# ═══════════════════════════════════════════════════════════════════════════
# 5. PAYMENTS  —  /api/payments
#    Backend: PAYMENT_SERVICE /api/v1/payments
#    Nota: confirm usa PUT, cancel usa DELETE (no backend)
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/payments", summary="Listar pagamentos", tags=["Payments"])
async def list_payments(request: Request, authorization: Optional[str] = Header(None)):
    claims = await _get_authenticated_claims(authorization, request)
    customer = await _find_payment_customer_by_email(claims["_normalized_email"], request)
    params = dict(request.query_params)
    limit = int(params.get("limit", 20)) if str(params.get("limit", "")).isdigit() else 20
    offset = int(params.get("offset", 0)) if str(params.get("offset", "")).isdigit() else 0

    # Fetch a page from Payment Service and filter it by ownership rules:
    # 1) payments owned by current local payment customer
    # 2) payments initiated by this authenticated Composer identity
    upstream_limit = max(100, limit + offset)
    params.pop("customer_id", None)
    params["limit"] = upstream_limit
    params["offset"] = 0

    payload = await proxy(
        "GET",
        f"{PAYMENT_SERVICE_URL}/api/v1/payments",
        headers=_pay_headers(request=request),
        params=params,
        service_label="Payment Service",
        request=request,
    )

    customer_id = str(customer.get("id")) if customer and customer.get("id") else None
    auth_user_id = str(claims.get("user_id") or "")

    items = payload.get("items", []) if isinstance(payload, dict) else []
    filtered = []
    for item in items:
        item_customer_id = str(item.get("customer_id") or "")
        item_meta = item.get("metadata") or {}
        initiator_id = str(item_meta.get("composer_initiator_auth_user_id") or "")
        if (customer_id and item_customer_id == customer_id) or (auth_user_id and initiator_id == auth_user_id):
            filtered.append(item)

    paged_items = filtered[offset: offset + limit]
    total = len(filtered)
    return {
        "items": paged_items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": (offset + limit) < total,
    }


@app.get("/api/payment-account", summary="Verificar conta local no Payment Service", tags=["Payments"])
async def get_payment_account(request: Request, authorization: Optional[str] = Header(None)):
    profile = await _get_authenticated_user_profile(authorization, request)
    customer = await _find_payment_customer_by_email(profile["_normalized_email"], request)
    return {
        "exists": bool(customer and customer.get("id")),
        "customer": customer,
        "identity_email": profile.get("email"),
    }


@app.post("/api/payment-account/setup", summary="Criar conta local no Payment Service", tags=["Payments"])
async def setup_payment_account(request: Request, authorization: Optional[str] = Header(None)):
    profile = await _get_authenticated_user_profile(authorization, request)
    existing_customer = await _find_payment_customer_by_email(profile["_normalized_email"], request)
    if existing_customer and existing_customer.get("id"):
        return {
            "created": False,
            "customer": existing_customer,
            "message": "A conta local do Payment Service já existe para este email.",
        }

    customer = await proxy(
        "POST",
        f"{PAYMENT_SERVICE_URL}/api/v1/customers",
        headers=_pay_headers(str(uuid.uuid4()), request=request),
        json=_build_payment_customer_payload(profile),
        service_label="Payment Service",
        request=request,
    )
    return {
        "created": True,
        "customer": customer,
        "message": "Conta local do Payment Service criada com sucesso.",
    }


@app.post("/api/payments", summary="Criar pagamento", tags=["Payments"])
async def create_payment(request: Request):
    body = await request.json()
    return await proxy("POST", f"{PAYMENT_SERVICE_URL}/api/v1/payments",
                        headers=_pay_headers(str(uuid.uuid4()), request=request),
                        json=body, service_label="Payment Service", request=request)


@app.get("/api/payments/{payment_id}", summary="Detalhes do pagamento", tags=["Payments"])
async def get_payment(payment_id: str, request: Request, authorization: Optional[str] = Header(None)):
    claims = await _get_authenticated_claims(authorization, request)
    customer = await _find_payment_customer_by_email(claims["_normalized_email"], request)
    if not customer or not customer.get("id"):
        raise HTTPException(status_code=404, detail="Pagamento não encontrado")

    data = await proxy(
        "GET",
        f"{PAYMENT_SERVICE_URL}/api/v1/payments/{payment_id}",
        headers=_pay_headers(request=request),
        service_label="Payment Service",
        request=request,
    )
    if str(data.get("customer_id") or "") != str(customer["id"]):
        raise HTTPException(status_code=404, detail="Pagamento não encontrado")
    return data


@app.post("/api/payments/{payment_id}/confirm", summary="Confirmar pagamento", tags=["Payments"])
async def confirm_payment(payment_id: str, request: Request):
    # Payment Service usa PUT /payments/{id}/confirm
    return await proxy("PUT", f"{PAYMENT_SERVICE_URL}/api/v1/payments/{payment_id}/confirm",
                        headers=_pay_headers(request=request),
                        service_label="Payment Service",
                        request=request)


@app.post("/api/payments/{payment_id}/cancel", summary="Cancelar pagamento", tags=["Payments"])
async def cancel_payment(payment_id: str, request: Request):
    # Payment Service usa DELETE /payments/{id} para cancelar/refund
    return await proxy("DELETE", f"{PAYMENT_SERVICE_URL}/api/v1/payments/{payment_id}",
                        headers=_pay_headers(request=request),
                        service_label="Payment Service",
                        request=request)


@app.get("/api/payments/{payment_id}/receipt", summary="Descarregar recibo (PDF)", tags=["Payments"])
async def download_receipt(payment_id: str, request: Request, authorization: Optional[str] = Header(None)):
    claims = await _get_authenticated_claims(authorization, request)
    customer = await _find_payment_customer_by_email(claims["_normalized_email"], request)
    if not customer or not customer.get("id"):
        raise HTTPException(status_code=404, detail="Pagamento não encontrado")

    payment = await proxy(
        "GET",
        f"{PAYMENT_SERVICE_URL}/api/v1/payments/{payment_id}",
        headers=_pay_headers(request=request),
        service_label="Payment Service",
        request=request,
    )
    if str(payment.get("customer_id") or "") != str(customer["id"]):
        raise HTTPException(status_code=404, detail="Pagamento não encontrado")

    data = await proxy(
        "GET",
        f"{PAYMENT_SERVICE_URL}/api/v1/payments/{payment_id}/receipt",
        headers=_pay_headers(request=request),
        service_label="Payment Service",
        request=request,
    )
    if isinstance(data, bytes):
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="receipt-{payment_id}.pdf"'},
        )
    return data


# ═══════════════════════════════════════════════════════════════════════════
# 6. CHECKOUT  —  Orquestração Saga (Fluxo Hosted Checkout)
#    Fase 1: POST /api/checkout → Reserva → Cria Sessão Hosted
#    Fase 2 (Sucesso): GET /api/checkout/success → Confirma bilhetes
#    Fase 2 (Cancel):  GET /api/checkout/cancel  → SAGA Compensation (Cancela bilhetes)
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/checkout", summary="Iniciar Checkout (reserva + redirecionamento)", tags=["Orchestration"])
async def checkout(request: Request, order: CheckoutRequest, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Token em falta")
    if not _extract_bearer_token(authorization):
        raise HTTPException(status_code=401, detail="Token inválido")

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Obter dados do utilizador do Auth Service
        user_data = await _get_authenticated_user_profile(authorization, request)
        user_email = user_data["_normalized_email"]
        if not user_email:
            raise HTTPException(status_code=401, detail="Sessão inválida: email em falta")

        # 2. Reservar bilhetes no Inventory Service
        inv_headers = _inv_headers(authorization, idempotency_key=str(uuid.uuid4()), request=request)
        
        res = await client.get(
            f"{INVENTORY_SERVICE_URL}/api/v1/events/{order.event_id}/tickets",
            params={"status": "available", "limit": max(100, order.quantity * 2)},
            headers=inv_headers
        )
        if res.status_code != 200:
            raise HTTPException(status_code=500, detail="Erro Inventory")
            
        available = res.json().get("data", [])
        if order.ticket_category_id:
            available = [t for t in available if t.get("ticket_category_id") == order.ticket_category_id]
            
        if len(available) < order.quantity:
            raise HTTPException(status_code=409, detail="Esgotado ou indisponível.")
            
        reserved_tickets = []
        for t in available[:order.quantity]:
            r = await client.put(f"{INVENTORY_SERVICE_URL}/api/v1/tickets/{t['id']}/reserve", headers=inv_headers)
            if r.status_code == 200:
                reserved_tickets.append(r.json())
                
        if len(reserved_tickets) < order.quantity:
            for rt in reserved_tickets:
                await _cancel_reserved_ticket(
                    client,
                    rt["id"],
                    inv_headers,
                    service_label="Inventory Service",
                )
            raise HTTPException(status_code=409, detail="Falha concorrência.")
        ticket_ids = [t["id"] for t in reserved_tickets]
        ticket_ids_str = ",".join(ticket_ids)

        # 3. Preparar Callbacks do Composer
        base_url = str(request.base_url).rstrip("/")
        # O Payment appendará ?session_id=...
        composer_success = f"{base_url}/api/checkout/success"
        
        frontend_cancel_encoded = urllib.parse.quote(order.cancel_url)
        composer_cancel = f"{base_url}/api/checkout/cancel?tickets={ticket_ids_str}&frontend_url={frontend_cancel_encoded}"

        # 4. Criar Hosted Checkout Session no Payment Service
        pay_payload = {
            "line_items": [
                {
                    "name": f"Event {order.event_id} Tickets",
                    "quantity": order.quantity,
                    "price": int(order.amount_cents / order.quantity) if order.quantity > 0 else order.amount_cents
                }
            ],
            "currency": "eur",
            "success_url": composer_success,
            "cancel_url": composer_cancel,
            "metadata": {
                "ticket_ids": ticket_ids_str,
                "frontend_success_url": order.success_url,
                "frontend_cancel_url": order.cancel_url,
                "composer_initiator_email": user_data.get("email"),
                "composer_initiator_auth_user_id": user_data.get("id"),
            }
        }
        
        pay_resp = await client.post(
            f"{PAYMENT_SERVICE_URL}/api/v1/checkout",
            json=pay_payload,
            headers=_pay_headers(str(uuid.uuid4()), request=request),
        )
        
        if pay_resp.status_code not in (200, 201):
            # Rollback SAGA
            for tid in ticket_ids:
                await _cancel_reserved_ticket(
                    client,
                    tid,
                    inv_headers,
                    service_label="Inventory Service",
                )
            raise HTTPException(status_code=400, detail="Erro ao criar checkout session")

        payload = pay_resp.json()
        checkout_url = payload.get("checkout_url")
        if isinstance(checkout_url, str) and checkout_url.startswith(PAYMENT_SERVICE_URL):
            checkout_url = checkout_url.replace(PAYMENT_SERVICE_URL, PAYMENT_PUBLIC_URL, 1)

        if isinstance(checkout_url, str) and checkout_url:
            payload["checkout_url"] = _append_query_params(checkout_url, {"force_auth": "1"})

        return payload


@app.get("/api/checkout/success", summary="Callback de Sucesso do Checkout SAGA", tags=["Orchestration"])
async def checkout_success(session_id: str):
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Obter a Checkout Session para ler metadata
        sess_resp = await client.get(
            f"{PAYMENT_SERVICE_URL}/api/v1/checkout/{session_id}",
            headers=_pay_headers()
        )
        if sess_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Sessão não válida")
        
        sess_data = sess_resp.json()
        meta = sess_data.get("metadata", {})
        ticket_ids_str = meta.get("ticket_ids", "")
        ticket_ids = [t for t in ticket_ids_str.split(",") if t] if ticket_ids_str else []
        front_url = meta.get("frontend_success_url", "/")

        payment_status = sess_data.get("payment_status")

        if payment_status == "paid":
            # Confirmar bilhetes — SAGA: se falhar, cancela os que já confirmámos
            inv_headers = _inv_headers()
            confirmed = []
            failed = False
            for tid in ticket_ids:
                confirm_resp = await client.put(
                    f"{INVENTORY_SERVICE_URL}/api/v1/tickets/{tid}/sell",
                    headers=inv_headers
                )
                if confirm_resp.status_code in (200, 201):
                    confirmed.append(tid)
                else:
                    # Idempotency/dup callbacks: if ticket is already finalized,
                    # treat it as success instead of forcing a cancel redirect.
                    ticket_resp = await client.get(
                        f"{INVENTORY_SERVICE_URL}/api/v1/tickets/{tid}",
                        headers=inv_headers,
                    )
                    if ticket_resp.status_code == 200:
                        ticket_data = ticket_resp.json()
                        ticket_status = str(ticket_data.get("status") or "").lower()
                        if ticket_status in ("sold", "confirmed", "used"):
                            confirmed.append(tid)
                            continue

                    failed = True
                    break

            if failed:
                # Compensação: cancelar os já confirmados
                for tid in confirmed:
                    await _cancel_reserved_ticket(
                        client,
                        tid,
                        inv_headers,
                        service_label="Inventory Service",
                    )
                # Redirecionar para cancel URL se disponível
                cancel_url = meta.get("frontend_cancel_url", front_url)
                return RedirectResponse(url=cancel_url, status_code=307)
        else:
            # Pagamento não completado — cancelar reservas
            inv_headers = _inv_headers()
            for tid in ticket_ids:
                await _cancel_reserved_ticket(
                    client,
                    tid,
                    inv_headers,
                    service_label="Inventory Service",
                )

        return RedirectResponse(url=front_url, status_code=307)


@app.get("/api/checkout/cancel", summary="Callback de Cancelamento do Checkout SAGA", tags=["Orchestration"])
async def checkout_cancel(tickets: str = "", frontend_url: str = "/"):
    # O utilizador fechou a janela ou cancelou o pagamento
    async with httpx.AsyncClient(timeout=15.0) as client:
        ticket_ids = [t for t in tickets.split(",") if t] if tickets else []
        inv_headers = _inv_headers()
        for tid in ticket_ids:
            await _cancel_reserved_ticket(
                client,
                tid,
                inv_headers,
                service_label="Inventory Service",
            )
    return RedirectResponse(url=frontend_url, status_code=307)


# ═══════════════════════════════════════════════════════════════════════════
# 7. REFUND  —  Orquestração de Reembolso
#    1. Auth verify → 2. Payment cancel/refund via DELETE /payments/{id} → 3. Inventory cancel tickets
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/refund", summary="Reembolso completo (devolve + cancela)", tags=["Orchestration"])
async def process_refund(request: Request, req: RefundRequest, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Token em falta")
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Token inválido")

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Verificar token
        claims = await _verify_user_token(token, request)
        if not claims.get("valid"):
            raise HTTPException(status_code=401, detail="Não autorizado")

        # 2. Cancelar/reembolsar pagamento no Payment Service
        #    Rota real: DELETE /api/v1/payments/{payment_id}
        #    O Payment decide se cancela (pending) ou faz refund (paid).
        ref_resp = await client.delete(
            f"{PAYMENT_SERVICE_URL}/api/v1/payments/{req.payment_id}",
            headers=_pay_headers(str(uuid.uuid4()), request=request),
        )
        if ref_resp.status_code not in (200, 201):
            raise HTTPException(status_code=400, detail="Erro ao processar reembolso.")

        # 3. Cancelar bilhetes no Inventory
        #    Rota real: DELETE /api/v1/tickets/{ticket_id}
        inv_headers = _inv_headers(authorization, idempotency_key=str(uuid.uuid4()), request=request)
        for tid in req.ticket_ids:
            await _cancel_reserved_ticket(
                client,
                tid,
                inv_headers,
                service_label="Inventory Service",
            )

        return {
            "status": "reembolsado",
            "payment_id": req.payment_id,
            "payment_status": ref_resp.json().get("status"),
            "cancelled_tickets": req.ticket_ids,
        }


# ═══════════════════════════════════════════════════════════════════════════
# 8. HEALTH CHECK  —  GET /health
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/health", summary="Estado do sistema", tags=["Health"])
async def health_check():
    """Verifica a conectividade com todos os serviços downstream."""
    report = {
        "composer": "online",
        "auth": "unknown",
        "inventory": "unknown",
        "payment": "unknown",
    }

    async with httpx.AsyncClient(timeout=3.0) as client:
        for svc, url in [
            ("auth", f"{AUTH_SERVICE_URL}/health"),
            ("inventory", f"{INVENTORY_SERVICE_URL}/health"),
            ("payment", f"{PAYMENT_SERVICE_URL}/health"),
        ]:
            try:
                r = await client.get(url)
                report[svc] = "online" if r.status_code == 200 else "degraded"
            except Exception:
                report[svc] = "offline"

    all_online = all(v == "online" for v in report.values())
    overall = "healthy" if all_online else "degraded"
    status_code = 200 if all_online else 503

    return Response(
        content=__import__("json").dumps({"status": overall, "services": report}),
        media_type="application/json",
        status_code=status_code,
    )
