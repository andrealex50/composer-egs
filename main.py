import os
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
AUTH_SSO_CLIENT_ID = os.getenv("AUTH_SSO_CLIENT_ID", "flash-sale")
AUTH_BROWSER_URL = os.getenv("AUTH_BROWSER_URL", "http://localhost:8001")
EVENT_MUTATIONS_REQUIRE_ADMIN = os.getenv("EVENT_MUTATIONS_REQUIRE_ADMIN", "false").lower() in {"1", "true", "yes"}
EVENT_ADMIN_ROLES = {
    role.strip().lower()
    for role in os.getenv("EVENT_ADMIN_ROLES", "admin").split(",")
    if role.strip()
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
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],       # restringir em produção
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
) -> dict | bytes:
    """Faz proxy de um pedido para um serviço interno e devolve a resposta."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.request(
                method, url,
                headers=headers,
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


def _extract_bearer_token(authorization: str | None) -> str | None:
    """Extrai o token Bearer do header Authorization."""
    if not authorization:
        return None
    if not authorization.startswith("Bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    return token or None


async def _verify_user_token(token: str) -> dict:
    """Valida token no Auth Service e devolve claims essenciais."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{AUTH_SERVICE_URL}/api/v1/auth/verify",
            headers={"X-Service-Auth": INTERNAL_SERVICE_KEY},
            json={"token": token},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Não autorizado")
    payload = resp.json()
    if not payload.get("valid"):
        raise HTTPException(status_code=401, detail="Token inválido")
    return payload


async def _ensure_event_admin_if_required(authorization: str | None) -> dict | None:
    """Valida role admin para mutações de eventos quando a política está ativa."""
    token = _extract_bearer_token(authorization)
    if not EVENT_MUTATIONS_REQUIRE_ADMIN:
        if not token:
            return None
        try:
            return await _verify_user_token(token)
        except HTTPException:
            # Em modo compatível, não bloqueia mutação se token inválido/ausente.
            return None

    if not token:
        raise HTTPException(status_code=401, detail="Token em falta para mutações de eventos")

    claims = await _verify_user_token(token)
    role = str(claims.get("role") or "").lower()
    if role not in EVENT_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Apenas admins podem alterar eventos")
    return claims


def _inv_headers(
    authorization: str | None = None,
    *,
    auth_claims: dict | None = None,
    idempotency_key: str | None = None,
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
    return h


def _pay_headers(idempotency_key: str | None = None) -> dict:
    """Headers de autenticação para o Payment Service."""
    h: dict = {"X-API-Key": PAYMENT_API_KEY}
    if idempotency_key:
        h["Idempotency-Key"] = idempotency_key
    return h


async def _get_authenticated_claims(authorization: str | None) -> dict:
    """Garante autenticação e devolve claims normalizados do utilizador."""
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Token em falta")
    claims = await _verify_user_token(token)
    email = str(claims.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Token inválido")
    claims["_normalized_email"] = email
    return claims


async def _find_payment_customer_by_email(email: str) -> dict | None:
    """Resolve customer do Payment Service por email (match case-insensitive)."""
    payload = await proxy(
        "GET",
        f"{PAYMENT_SERVICE_URL}/api/v1/customers",
        headers=_pay_headers(),
        params={"email": email, "limit": 20, "offset": 0},
        service_label="Payment Service",
    )
    items = payload.get("items", []) if isinstance(payload, dict) else []
    for item in items:
        item_email = str(item.get("email") or "").strip().lower()
        if item_email == email:
            return item
    return items[0] if items else None


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


# ═══════════════════════════════════════════════════════════════════════════
# 1. AUTH  —  /api/auth/*
#    Backend: AUTH_SERVICE /api/v1/auth/*
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/auth/register", summary="Registar novo utilizador", tags=["Auth"])
async def auth_register(request: Request):
    body = await request.json()
    return await proxy("POST", f"{AUTH_SERVICE_URL}/api/v1/auth/register",
                        json=body, service_label="Auth Service")


@app.post("/api/auth/login", summary="Login (JWT)", tags=["Auth"])
async def auth_login(request: Request):
    body = await request.json()
    return await proxy("POST", f"{AUTH_SERVICE_URL}/api/v1/auth/login",
                        json=body, service_label="Auth Service")


@app.post("/api/auth/refresh", summary="Renovar access token", tags=["Auth"])
async def auth_refresh(request: Request):
    body = await request.json()
    return await proxy("POST", f"{AUTH_SERVICE_URL}/api/v1/auth/refresh",
                        json=body, service_label="Auth Service")


@app.get("/api/auth/me", summary="Perfil do utilizador autenticado", tags=["Auth"])
async def auth_me(authorization: Optional[str] = Header(None)):
    return await proxy("GET", f"{AUTH_SERVICE_URL}/api/v1/auth/me",
                        headers=_auth_headers(authorization),
                        service_label="Auth Service")


@app.post("/api/auth/logout", summary="Logout", tags=["Auth"])
async def auth_logout(authorization: Optional[str] = Header(None)):
    return await proxy("POST", f"{AUTH_SERVICE_URL}/api/v1/auth/logout",
                        headers=_auth_headers(authorization),
                        service_label="Auth Service")


@app.get("/api/auth/sso/authorize-url", summary="Obter URL de SSO login/register", tags=["Auth"])
async def auth_sso_authorize_url(
    request: Request,
    mode: str = "login",
    redirect_uri: Optional[str] = None,
    state: Optional[str] = None,
):
    if mode not in {"login", "register"}:
        raise HTTPException(status_code=422, detail="mode deve ser 'login' ou 'register'")

    base_frontend_url = str(request.base_url).rstrip("/")
    target_redirect = redirect_uri or f"{base_frontend_url}/"
    nonce = state or uuid.uuid4().hex

    route = "login" if mode == "login" else "register"
    params = urllib.parse.urlencode({
        "client_id": AUTH_SSO_CLIENT_ID,
        "redirect_uri": target_redirect,
        "state": nonce,
    })

    return {
        "authorization_url": f"{AUTH_BROWSER_URL}/ui/{route}?{params}",
        "state": nonce,
        "client_id": AUTH_SSO_CLIENT_ID,
        "mode": mode,
    }


@app.post("/api/auth/exchange-code", summary="Trocar auth code por tokens", tags=["Auth"])
async def auth_exchange_code(request: Request):
    body = await request.json()
    code = body.get("code")
    client_id = body.get("client_id") or AUTH_SSO_CLIENT_ID

    if not code:
        raise HTTPException(status_code=422, detail="code é obrigatório")

    payload = {"code": code, "client_id": client_id}
    return await proxy(
        "POST",
        f"{AUTH_SERVICE_URL}/api/v1/auth/exchange-code",
        json=payload,
        service_label="Auth Service",
    )


# ═══════════════════════════════════════════════════════════════════════════
# 2. EVENTS  —  /api/events
#    Backend: INVENTORY_SERVICE /api/v1/events
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/events", summary="Listar eventos", tags=["Events"])
async def list_events(request: Request):
    # Passa todos os query params para o Inventory (skip, limit, status, search, etc.)
    return await proxy("GET", f"{INVENTORY_SERVICE_URL}/api/v1/events",
                        headers=_inv_headers(),
                        params=dict(request.query_params),
                        service_label="Inventory Service")


@app.post("/api/events", summary="Criar evento", tags=["Events"])
async def create_event(request: Request, authorization: Optional[str] = Header(None)):
    body = await request.json()
    claims = await _ensure_event_admin_if_required(authorization)
    return await proxy("POST", f"{INVENTORY_SERVICE_URL}/api/v1/events",
                        headers=_inv_headers(authorization, auth_claims=claims, idempotency_key=str(uuid.uuid4())),
                        json=body, service_label="Inventory Service")


@app.get("/api/events/{event_id}", summary="Detalhes do evento", tags=["Events"])
async def get_event(event_id: str):
    # Composer bonus: junta as categorias de bilhetes ao evento
    event_data = await proxy("GET", f"{INVENTORY_SERVICE_URL}/api/v1/events/{event_id}",
                              headers=_inv_headers(),
                              service_label="Inventory Service")

    try:
        tickets = await proxy("GET", f"{INVENTORY_SERVICE_URL}/api/v1/events/{event_id}/tickets",
                               headers=_inv_headers(),
                               service_label="Inventory Service")
        if isinstance(tickets, dict):
            event_data["ticket_categories"] = tickets.get("data", [])
    except HTTPException:
        pass

    return event_data


@app.put("/api/events/{event_id}", summary="Atualizar evento", tags=["Events"])
async def update_event(event_id: str, request: Request, authorization: Optional[str] = Header(None)):
    body = await request.json()
    claims = await _ensure_event_admin_if_required(authorization)
    return await proxy("PUT", f"{INVENTORY_SERVICE_URL}/api/v1/events/{event_id}",
                        headers=_inv_headers(authorization, auth_claims=claims, idempotency_key=str(uuid.uuid4())),
                        json=body, service_label="Inventory Service")


@app.delete("/api/events/{event_id}", summary="Apagar evento", tags=["Events"])
async def delete_event(event_id: str, authorization: Optional[str] = Header(None)):
    claims = await _ensure_event_admin_if_required(authorization)
    return await proxy("DELETE", f"{INVENTORY_SERVICE_URL}/api/v1/events/{event_id}",
                        headers=_inv_headers(authorization, auth_claims=claims, idempotency_key=str(uuid.uuid4())),
                        service_label="Inventory Service")


# ═══════════════════════════════════════════════════════════════════════════
# 3. TICKETS  —  /api/events/{id}/tickets  &  /api/tickets/{id}
#    Backend: INVENTORY_SERVICE /api/v1/events/{id}/tickets
#             INVENTORY_SERVICE /api/v1/tickets/{id}
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/events/{event_id}/tickets", summary="Criar bilhetes (batch)", tags=["Tickets"])
async def create_tickets(event_id: str, request: Request, authorization: Optional[str] = Header(None)):
    body = await request.json()
    claims = await _ensure_event_admin_if_required(authorization)
    return await proxy("POST", f"{INVENTORY_SERVICE_URL}/api/v1/events/{event_id}/tickets",
                        headers=_inv_headers(authorization, auth_claims=claims, idempotency_key=str(uuid.uuid4())),
                        json=body, service_label="Inventory Service")


@app.get("/api/events/{event_id}/tickets", summary="Listar bilhetes de um evento", tags=["Tickets"])
async def list_event_tickets(event_id: str, request: Request):
    return await proxy("GET", f"{INVENTORY_SERVICE_URL}/api/v1/events/{event_id}/tickets",
                        headers=_inv_headers(),
                        params=dict(request.query_params),
                        service_label="Inventory Service")


@app.get("/api/tickets/{ticket_id}/availability", summary="Disponibilidade do bilhete", tags=["Tickets"])
async def ticket_availability(ticket_id: str):
    """Proxy para GET /api/v1/tickets/{ticket_id} — devolve o estado atual do bilhete."""
    return await proxy("GET", f"{INVENTORY_SERVICE_URL}/api/v1/tickets/{ticket_id}",
                        headers=_inv_headers(),
                        service_label="Inventory Service")


# ═══════════════════════════════════════════════════════════════════════════
# 4. RESERVATIONS  —  /api/reservations
#    Backend: Inventory NÃO tem /reservations. Reservas = operações sobre tickets:
#      - Criar reserva   → POST /api/v1/events/{event_id}/tickets/reserve
#      - Confirmar        → POST /api/v1/tickets/{ticket_id}/confirm
#      - Cancelar         → POST /api/v1/tickets/{ticket_id}/cancel
#      - Ver reserva      → GET  /api/v1/tickets/{ticket_id}  (status=reserved)
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/reservations", summary="Reservar bilhetes", tags=["Reservations"])
async def create_reservation(request: Request, authorization: Optional[str] = Header(None)):
    body = await request.json()
    event_id = body.get("event_id")
    quantity = body.get("quantity", 1)
    if not event_id:
        raise HTTPException(status_code=422, detail="event_id é obrigatório")

    inv_headers = _inv_headers(authorization, idempotency_key=str(uuid.uuid4()))

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
async def get_reservation(ticket_id: str):
    """Proxy para GET /api/v1/tickets/{ticket_id} — devolve o bilhete (inclui status de reserva)."""
    return await proxy("GET", f"{INVENTORY_SERVICE_URL}/api/v1/tickets/{ticket_id}",
                        headers=_inv_headers(),
                        service_label="Inventory Service")


# ═══════════════════════════════════════════════════════════════════════════
# 5. PAYMENTS  —  /api/payments
#    Backend: PAYMENT_SERVICE /api/v1/payments
#    Nota: confirm usa PUT, cancel usa DELETE (no backend)
# ═══════════════════════════════════════════════════════════════════════════

@app.get("/api/payments", summary="Listar pagamentos", tags=["Payments"])
async def list_payments(request: Request, authorization: Optional[str] = Header(None)):
    claims = await _get_authenticated_claims(authorization)
    customer = await _find_payment_customer_by_email(claims["_normalized_email"])
    params = dict(request.query_params)
    limit = int(params.get("limit", 20)) if str(params.get("limit", "")).isdigit() else 20
    offset = int(params.get("offset", 0)) if str(params.get("offset", "")).isdigit() else 0

    if not customer or not customer.get("id"):
        return {"items": [], "total": 0, "limit": limit, "offset": offset, "has_more": False}

    params["customer_id"] = str(customer["id"])
    return await proxy(
        "GET",
        f"{PAYMENT_SERVICE_URL}/api/v1/payments",
        headers=_pay_headers(),
        params=params,
        service_label="Payment Service",
    )


@app.post("/api/payments", summary="Criar pagamento", tags=["Payments"])
async def create_payment(request: Request):
    body = await request.json()
    return await proxy("POST", f"{PAYMENT_SERVICE_URL}/api/v1/payments",
                        headers=_pay_headers(str(uuid.uuid4())),
                        json=body, service_label="Payment Service")


@app.get("/api/payments/{payment_id}", summary="Detalhes do pagamento", tags=["Payments"])
async def get_payment(payment_id: str, authorization: Optional[str] = Header(None)):
    claims = await _get_authenticated_claims(authorization)
    customer = await _find_payment_customer_by_email(claims["_normalized_email"])
    if not customer or not customer.get("id"):
        raise HTTPException(status_code=404, detail="Pagamento não encontrado")

    data = await proxy(
        "GET",
        f"{PAYMENT_SERVICE_URL}/api/v1/payments/{payment_id}",
        headers=_pay_headers(),
        service_label="Payment Service",
    )
    if str(data.get("customer_id") or "") != str(customer["id"]):
        raise HTTPException(status_code=404, detail="Pagamento não encontrado")
    return data


@app.post("/api/payments/{payment_id}/confirm", summary="Confirmar pagamento", tags=["Payments"])
async def confirm_payment(payment_id: str):
    # Payment Service usa PUT /payments/{id}/confirm
    return await proxy("PUT", f"{PAYMENT_SERVICE_URL}/api/v1/payments/{payment_id}/confirm",
                        headers=_pay_headers(),
                        service_label="Payment Service")


@app.post("/api/payments/{payment_id}/cancel", summary="Cancelar pagamento", tags=["Payments"])
async def cancel_payment(payment_id: str):
    # Payment Service usa DELETE /payments/{id} para cancelar/refund
    return await proxy("DELETE", f"{PAYMENT_SERVICE_URL}/api/v1/payments/{payment_id}",
                        headers=_pay_headers(),
                        service_label="Payment Service")


@app.get("/api/payments/{payment_id}/receipt", summary="Descarregar recibo (PDF)", tags=["Payments"])
async def download_receipt(payment_id: str, authorization: Optional[str] = Header(None)):
    claims = await _get_authenticated_claims(authorization)
    customer = await _find_payment_customer_by_email(claims["_normalized_email"])
    if not customer or not customer.get("id"):
        raise HTTPException(status_code=404, detail="Pagamento não encontrado")

    payment = await proxy(
        "GET",
        f"{PAYMENT_SERVICE_URL}/api/v1/payments/{payment_id}",
        headers=_pay_headers(),
        service_label="Payment Service",
    )
    if str(payment.get("customer_id") or "") != str(customer["id"]):
        raise HTTPException(status_code=404, detail="Pagamento não encontrado")

    data = await proxy(
        "GET",
        f"{PAYMENT_SERVICE_URL}/api/v1/payments/{payment_id}/receipt",
        headers=_pay_headers(),
        service_label="Payment Service",
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
    token = authorization.replace("Bearer ", "")

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Obter dados do utilizador do Auth Service
        me_resp = await client.get(
            f"{AUTH_SERVICE_URL}/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        if me_resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Não autorizado")
        user_data = me_resp.json()
        user_email = str(user_data.get("email") or "").strip().lower()
        if not user_email:
            raise HTTPException(status_code=401, detail="Sessão inválida: email em falta")

        customer = await _find_payment_customer_by_email(user_email)
        if not customer or not customer.get("id"):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "wallet_setup_required",
                    "message": "Configura primeiro a tua wallet no serviço de pagamentos para concluir o checkout.",
                    "action_url": f"{PAYMENT_PUBLIC_URL}/docs#/Authentication/register_customer_auth_register_post",
                },
            )

        # 2. Reservar bilhetes no Inventory Service
        inv_headers = _inv_headers(authorization, idempotency_key=str(uuid.uuid4()))
        
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
            "customer_email": user_data.get("email"),
            "customer_name": user_data.get("full_name"),
            "metadata": {
                "ticket_ids": ticket_ids_str,
                "frontend_success_url": order.success_url
            }
        }
        
        pay_resp = await client.post(
            f"{PAYMENT_SERVICE_URL}/api/v1/checkout/sessions",
            json=pay_payload,
            headers=_pay_headers(str(uuid.uuid4())),
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
            payload["checkout_url"] = checkout_url.replace(PAYMENT_SERVICE_URL, PAYMENT_PUBLIC_URL, 1)

        return payload


@app.get("/api/checkout/success", summary="Callback de Sucesso do Checkout SAGA", tags=["Orchestration"])
async def checkout_success(session_id: str):
    async with httpx.AsyncClient(timeout=15.0) as client:
        # Obter a Checkout Session para ler metadata
        sess_resp = await client.get(
            f"{PAYMENT_SERVICE_URL}/api/v1/checkout/sessions/{session_id}",
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
#    1. Auth verify → 2. Payment create refund → 3. Inventory cancel tickets
# ═══════════════════════════════════════════════════════════════════════════

@app.post("/api/refund", summary="Reembolso completo (devolve + cancela)", tags=["Orchestration"])
async def process_refund(req: RefundRequest, authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Token em falta")
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Token inválido")

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Verificar token
        claims = await _verify_user_token(token)
        if not claims.get("valid"):
            raise HTTPException(status_code=401, detail="Não autorizado")

        # 2. Criar reembolso no Payment Service
        #    Rota real: POST /api/v1/refunds
        #    Body esperado: { "payment_id": UUID, "reason": str, ... }
        refund_payload = {
            "payment_id": req.payment_id,
            "reason": req.reason,
        }
        ref_resp = await client.post(
            f"{PAYMENT_SERVICE_URL}/api/v1/refunds",
            json=refund_payload,
            headers=_pay_headers(str(uuid.uuid4())),
        )
        if ref_resp.status_code not in (200, 201):
            raise HTTPException(status_code=400, detail="Erro ao processar reembolso.")

        # 3. Cancelar bilhetes no Inventory
        #    Rota real: POST /api/v1/tickets/{ticket_id}/cancel
        inv_headers = _inv_headers(authorization, idempotency_key=str(uuid.uuid4()))
        for tid in req.ticket_ids:
            await _cancel_reserved_ticket(
                client,
                tid,
                inv_headers,
                service_label="Inventory Service",
            )

        return {
            "status": "reembolsado",
            "refund_id": ref_resp.json().get("id"),
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