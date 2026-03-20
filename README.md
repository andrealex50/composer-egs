# 🎯 FlashSale — Composer / API Gateway

Orquestrador central da plataforma **FlashSale**. Funciona como API Gateway (padrão *Backend for Frontend*), agregando três microsserviços independentes num único ponto de entrada para o frontend React.

```
┌──────────────────────────────────┐
│        Frontend React            │
└──────────────┬───────────────────┘
               ▼
┌──────────────────────────────────┐
│   Composer / API Gateway :8080   │
│          (FastAPI)               │
└───┬──────────┬───────────┬───────┘
    ▼          ▼           ▼
 Auth      Inventory    Payment
Service     Service     Service
```

---

## 📋 Endpoints Expostos

### Auth (`/api/auth`)

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/auth/register` | Registar novo utilizador |
| POST | `/api/auth/login` | Login (devolve JWT) |
| POST | `/api/auth/refresh` | Renovar access token |
| GET | `/api/auth/me` | Perfil do utilizador autenticado |
| POST | `/api/auth/logout` | Logout |
| POST | `/api/auth/forgot-password` | Solicitar reset de password |
| POST | `/api/auth/reset-password` | Aplicar nova password com token |
| DELETE | `/api/auth/me` | Eliminar conta autenticada |

### Events (`/api/events`)

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/events` | Listar eventos |
| POST | `/api/events` | Criar evento |
| GET | `/api/events/{id}` | Detalhes do evento (+ bilhetes) |
| PUT | `/api/events/{id}` | Atualizar evento |
| DELETE | `/api/events/{id}` | Apagar evento |

### Tickets (`/api/events/{id}/tickets`)

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/events/{id}/tickets` | Criar bilhetes (batch) |
| GET | `/api/events/{id}/tickets` | Listar bilhetes de um evento |
| GET | `/api/tickets/{id}/availability` | Ver disponibilidade |

### Reservations (`/api/reservations`)

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/reservations` | Reservar bilhetes |
| GET | `/api/reservations/{id}` | Ver estado da reserva |

### Payments (`/api/payments`)

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/payments` | Listar pagamentos |
| POST | `/api/payments` | Criar pagamento |
| GET | `/api/payments/{id}` | Detalhes do pagamento |
| POST | `/api/payments/{id}/confirm` | Confirmar pagamento |
| POST | `/api/payments/{id}/cancel` | Cancelar pagamento |
| GET | `/api/payments/{id}/receipt` | Descarregar recibo (PDF) |

### Orquestrações (Saga Pattern)

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/checkout` | Checkout completo (reserva → paga → confirma) |
| POST | `/api/refund` | Reembolso completo (devolve → cancela reserva) |

### Health

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/health` | Estado do sistema e conectividade dos serviços |

---

## 🚀 Quick Start

### Requisitos

- Python 3.11+
- Docker & Docker Compose

### Opção 1 — Docker Compose (recomendado)

Sobe todos os serviços (Composer + Auth + Inventory + Payment + Postgres + Redis):

```bash
cd ~/composer-egs
docker compose up --build -d
```

Verifica se tudo está a correr:

```bash
docker compose ps
```

O Composer fica disponível em **http://localhost:8080**

Para compatibilidade com o frontend estático da equipa de auth, o Auth Service fica também exposto em **http://localhost:8000**.

Para parar tudo:

```bash
docker compose down
```

Para parar e **apagar volumes** (BD):

```bash
docker compose down -v
```

### Opção 2 — Desenvolvimento local (só o Composer)

```bash
cd ~/composer-egs
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8080
```

> ⚠️ Neste modo os outros serviços precisam de estar a correr separadamente.

---

## ⚙️ Configuração

| Variável | Default | Descrição |
|----------|---------|-----------|
| `AUTH_SERVICE_URL` | `http://auth-service:8000` | URL do Auth Service |
| `COMPOSER_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173,http://localhost:5500,http://127.0.0.1:5500` | Origins permitidas pelo gateway Composer |
| `COMPOSER_BROWSER_RETURN_TO_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Origins autorizadas para o callback browser one-time do Composer |
| `AUTH_BACKEND_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173,http://localhost:5500,http://127.0.0.1:5500` | Origins permitidas diretamente pelo Auth Service |
| `AUTH_FRONTEND_PUBLIC_BASE_URL` | `http://localhost:5500` | Base URL pública do frontend separado do Auth usada nos links de reset |
| `AUTH_PASSWORD_RESET_LINK_PATH` | `/templates/reset_password.html` | Path do frontend do Auth que recebe o token de reset |
| `INVENTORY_SERVICE_URL` | `http://inventory-service:8000` | URL do Inventory Service |
| `PAYMENT_SERVICE_URL` | `http://payment-service:8000` | URL do Payment Service |
| `INVENTORY_API_KEY` | `your-secret-api-key` | API Key para o Inventory |
| `PAYMENT_API_KEY` | `your-secret-api-key` | API Key para o Payment |
| `PAYMENT_ADMIN_API_KEY` | `admin-dev-key-2024` | Admin key bootstrap do Payment Service |
| `INTERNAL_SERVICE_KEY` | `internal-dev-key-2024` | Chave interna para chamadas service-to-service ao Auth `/verify` |
| `EVENT_MUTATIONS_REQUIRE_ADMIN` | `false` | Se `true`, criar/editar/apagar eventos e criar tickets exige utilizador com role admin |
| `EVENT_ADMIN_ROLES` | `admin` | Lista de roles permitidas para mutações de eventos (separadas por vírgula) |

> **Nota:** Para o checkout/refund funcionar com pagamentos reais, é preciso configurar as Stripe test keys no `.env` do Payment Service (`STRIPE_SECRET_KEY` e `STRIPE_WEBHOOK_SECRET`).

> **Nota:** Em modo compatibilidade (`EVENT_MUTATIONS_REQUIRE_ADMIN=false`), o Composer continua a aceitar mutações via API key interna, mas já propaga contexto de utilizador para facilitar migração quando o Inventory passar a exigir role.

> **Nota:** O gateway também preserva `X-Request-ID` e `X-Correlation-ID` quando encaminha pedidos para troubleshooting distribuído.

### Auth API-only + Password Reset

O Auth Service deixou de servir templates server-side. Os links de reset devem apontar para o frontend separado da equipa de auth, configurado por `AUTH_FRONTEND_PUBLIC_BASE_URL` + `AUTH_PASSWORD_RESET_LINK_PATH`.

O frontend estático do auth que está no repositório EGS chama a API diretamente em `http://localhost:8000/api/v1`. Por isso, este `docker-compose.yml` expõe o Auth Service na porta `8000` e já inclui `http://localhost:5500`/`http://127.0.0.1:5500` em `AUTH_BACKEND_CORS_ORIGINS`.

Usar o mesmo Auth Service não implica juntar os fluxos de negócio de FlashSale e Payment. O Auth centraliza identidade; cada serviço continua a ter as suas próprias regras, permissões e onboarding.

Para o login browser completo com frontend separado, o Composer expõe dois endpoints internos de integração:

- `POST /api/auth/browser/handoff`: recebe tokens do frontend de auth, valida o access token e devolve um redirect com código one-time.
- `POST /api/auth/browser/exchange`: troca esse código one-time pela sessão local do Composer no callback.

Pedir link de reset:

```bash
curl -s -X POST http://localhost:8080/api/auth/forgot-password \
  -H "Content-Type: application/json" \
  -d '{"email":"teste@flashsale.pt"}' | python3 -m json.tool
```

Testar guard de reset com token inválido:

```bash
curl -s -X POST http://localhost:8080/api/auth/reset-password \
  -H "Content-Type: application/json" \
  -d '{"token":"invalid-token","new_password":"ChangedPass123"}' | python3 -m json.tool
```

### API Key recomendada para o Payment

Em ambiente de demo/dev rápido o Composer pode usar a admin key, mas o fluxo correto é usar uma tenant key dedicada:

```bash
# 1) Criar tenant key no Payment (porta publica 8002)
curl -s -X POST http://localhost:8002/api/v1/admin/api-keys \
  -H "Content-Type: application/json" \
  -H "X-API-Key: ${PAYMENT_ADMIN_API_KEY:-admin-dev-key-2024}" \
  -d '{
    "client_name": "Composer Service",
    "description": "Tenant key para o Composer",
    "rate_limit_requests": 500,
    "rate_limit_window_seconds": 60
  }' | python3 -m json.tool
```

Guarda o campo `raw_key` e exporta no terminal antes de subir o stack:

```bash
export PAYMENT_API_KEY="<raw_key_tenant>"
export PAYMENT_ADMIN_API_KEY="admin-dev-key-2024"
docker compose up --build -d
```

---

## 📚 Documentação Interativa

Com o serviço a correr:

- **Swagger UI** → [http://localhost:8080/docs](http://localhost:8080/docs)
- **ReDoc** → [http://localhost:8080/redoc](http://localhost:8080/redoc)

---

## 🎓 Comandos Para Mostrar Ao Professor

Sequência curta para demo completa (health, auth, eventos e checkout):

### 1. Subir stack

```bash
cd ~/composer-egs
docker compose up --build -d
docker compose ps
```

### 2. Health check

```bash
curl -s http://localhost:8080/health | python3 -m json.tool
```

### 3. Registar utilizador de demo

```bash
curl -s -X POST http://localhost:8080/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "prof.demo@flashsale.pt",
    "password": "Demo1234!",
    "full_name": "Professor Demo"
  }' | python3 -m json.tool
```

### 4. Login e guardar token

```bash
LOGIN_JSON=$(curl -s -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "prof.demo@flashsale.pt",
    "password": "Demo1234!"
  }')

echo "$LOGIN_JSON" | python3 -m json.tool
TOKEN=$(echo "$LOGIN_JSON" | sed -n 's/.*"access_token":"\([^"]*\)".*/\1/p')
echo "TOKEN obtido: ${#TOKEN} chars"
```

### 5. Ver perfil autenticado

```bash
curl -s http://localhost:8080/api/auth/me \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### 6. Listar eventos e guardar EVENT_ID

```bash
EVENTS_JSON=$(curl -s http://localhost:8080/api/events)
echo "$EVENTS_JSON" | python3 -m json.tool
EVENT_ID=$(echo "$EVENTS_JSON" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p' | head -n1)
echo "EVENT_ID=$EVENT_ID"
```

> Se não houver eventos, cria um no endpoint `POST /api/events` e repete este passo.

### 7. Iniciar checkout (Saga)

```bash
curl -s -X POST http://localhost:8080/api/checkout \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{
    \"event_id\": \"${EVENT_ID}\",
    \"quantity\": 1,
    \"success_url\": \"http://localhost:5173/?status=success\",
    \"cancel_url\": \"http://localhost:5173/?status=cancel\",
    \"amount_cents\": 1500
  }" | python3 -m json.tool
```

### 8. Abrir o checkout_url no browser

No JSON da resposta anterior, abre o campo `checkout_url` no browser para concluir a compra.

### 9. Frontend (opcional para demo visual)

```bash
cd ~/composer-egs/frontend
cp .env.example .env.local
npm install
npm run dev
```

Depois abre: [http://localhost:5173](http://localhost:5173)

O portal do Composer pode mostrar links diretos para o frontend separado do auth. Ajusta em `frontend/.env.local` se o teu colega tiver outro host/path:

```env
VITE_AUTH_UI_BASE_URL=http://localhost:5500
VITE_AUTH_UI_LOGIN_PATH=/templates/login.html
VITE_AUTH_UI_REGISTER_PATH=/templates/register.html
VITE_AUTH_UI_FORGOT_PATH=/templates/forgot_password.html
```

Se usares o frontend do teu colega tal como ele está, não mudes a porta do Auth Service: os templates dele estão hardcoded para `http://localhost:8000/api/v1`.

O fluxo completo de login fica assim:

1. O Composer envia o browser para a UI de auth com `handoff_url`, `return_to` e `state`.
2. A UI de auth autentica o utilizador e entrega os tokens ao `POST /api/auth/browser/handoff` do Composer.
3. O Composer devolve um redirect com código one-time.
4. O frontend do Composer recebe esse código, chama `POST /api/auth/browser/exchange` e cria a sua própria sessão local.

Se estiveres a usar o frontend do teu colega tal como está no repositório dele:

```bash
cd ../EGS/frontend
python3 -m http.server 5500
```

---

## 🧪 Testes End-to-End

Depois de correr `docker compose up --build -d`, testa com os seguintes comandos:

### 1. Health Check

```bash
curl -s http://localhost:8080/health | python3 -m json.tool
```

### 2. Registar Utilizador

```bash
curl -s -X POST http://localhost:8080/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "teste@flashsale.pt",
    "password": "Teste1234!",
    "full_name": "Tester FlashSale"
  }' | python3 -m json.tool
```

### 3. Login

```bash
curl -s -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "teste@flashsale.pt",
    "password": "Teste1234!"
  }' | python3 -m json.tool
```

Guardar o token:

```bash
TOKEN="<colar o access_token aqui>"
```

### 4. Ver Perfil

```bash
curl -s http://localhost:8080/api/auth/me \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### 4.1. Forgot Password

```bash
curl -s -X POST http://localhost:8080/api/auth/forgot-password \
  -H "Content-Type: application/json" \
  -d '{
    "email": "teste@flashsale.pt"
  }' | python3 -m json.tool
```

### 5. Criar Evento

```bash
curl -s -X POST http://localhost:8080/api/events \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "NOS Alive 2026",
    "description": "Festival de verão em Lisboa",
    "venue": "Passeio Marítimo de Algés",
    "date": "2026-07-09T18:00:00Z",
    "end_date": "2026-07-11T23:59:00Z",
    "max_capacity": 50000
  }' | python3 -m json.tool
```

Guardar o ID:

```bash
EVENT_ID="<colar o id do evento>"
```

### 6. Listar Eventos

```bash
curl -s http://localhost:8080/api/events | python3 -m json.tool
```

### 7. Criar Bilhetes (batch de 100)

```bash
curl -s -X POST "http://localhost:8080/api/events/${EVENT_ID}/tickets" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "General Admission",
    "description": "Entrada geral",
    "price": 49.99,
    "currency": "EUR",
    "total_quantity": 100,
    "max_per_order": 4
  }' | python3 -m json.tool
```

### 8. Listar Bilhetes

```bash
curl -s "http://localhost:8080/api/events/${EVENT_ID}/tickets" | python3 -m json.tool
```

### 9. Ver Detalhes do Evento (com bilhetes)

```bash
curl -s "http://localhost:8080/api/events/${EVENT_ID}" | python3 -m json.tool
```

### 10. Reservar Bilhetes

```bash
curl -s -X POST http://localhost:8080/api/reservations \
  -H "Content-Type: application/json" \
  -d "{
    \"event_id\": \"${EVENT_ID}\",
    \"quantity\": 2
  }" | python3 -m json.tool
```

Guardar um ticket_id:

```bash
TICKET_ID="<colar o id de um dos tickets reservados>"
```

### 11. Ver Disponibilidade do Bilhete

```bash
curl -s "http://localhost:8080/api/tickets/${TICKET_ID}/availability" | python3 -m json.tool
```

### 12. Ver Reserva

```bash
curl -s "http://localhost:8080/api/reservations/${TICKET_ID}" | python3 -m json.tool
```

### 13. Listar Pagamentos

```bash
curl -s http://localhost:8080/api/payments \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### 14. Checkout Completo (Saga)

```bash
curl -s -X POST http://localhost:8080/api/checkout \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{
    \"event_id\": \"${EVENT_ID}\",
    \"quantity\": 2,
    \"payment_method_id\": \"pm_card_visa\",
    \"amount_cents\": 9998
  }" | python3 -m json.tool
```

> ⚠️ Sem Stripe keys reais, o pagamento é recusado e a reserva é cancelada automaticamente (Saga compensation). Com keys válidas, devolve `{"status": "sucesso", ...}`.

### 15. Reembolso (Saga)

```bash
curl -s -X POST http://localhost:8080/api/refund \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "payment_id": "<PAYMENT_ID>",
    "ticket_ids": ["<TICKET_ID_1>", "<TICKET_ID_2>"],
    "reason": "requested_by_customer"
  }' | python3 -m json.tool
```

---

## 🏗️ Arquitetura

### Proxy Simples
Para a maioria dos endpoints, o Composer funciona como proxy transparente — recebe o pedido, encaminha para o serviço correto, e devolve a resposta.

### Saga Pattern (Orquestração)
Para operações que envolvem múltiplos serviços (`/api/checkout` e `/api/refund`), o Composer orquestra a sequência de chamadas com **compensação automática** em caso de falha:

```
CHECKOUT:
  1. Verifica token (Auth)
  2. Reserva bilhetes (Inventory → POST /events/{id}/tickets/reserve)
  3. Processa pagamento (Payment → POST /payments)
  4a. ✅ Sucesso → Confirma cada bilhete (Inventory → POST /tickets/{id}/confirm)
  4b. ❌ Falha   → Cancela cada bilhete (Inventory → POST /tickets/{id}/cancel)

REFUND:
  1. Verifica token (Auth)
  2. Cria reembolso (Payment → POST /refunds)
  3. Cancela cada bilhete (Inventory → POST /tickets/{id}/cancel)
```

### Mapeamento de Rotas (Composer → Backend)

| Composer | Backend Real |
|----------|-------------|
| `/api/auth/*` | Auth Service → `/api/v1/auth/*` |
| `/api/events/*` | Inventory → `/api/v1/events/*` |
| `/api/events/{id}/tickets` | Inventory → `/api/v1/events/{id}/tickets` |
| `/api/tickets/{id}/availability` | Inventory → `/api/v1/tickets/{id}` |
| `/api/reservations` (POST) | Inventory → `/api/v1/events/{id}/tickets/reserve` |
| `/api/reservations/{id}` (GET) | Inventory → `/api/v1/tickets/{id}` |
| `/api/payments/*` | Payment → `/api/v1/payments/*` |
| `/api/payments/{id}/confirm` (POST) | Payment → `PUT /api/v1/payments/{id}/confirm` |
| `/api/payments/{id}/cancel` (POST) | Payment → `DELETE /api/v1/payments/{id}` |

---

## 🛠️ Stack Tecnológica

| Componente | Tecnologia |
|------------|------------|
| Framework | FastAPI |
| HTTP Client | httpx (async) |
| Validação | Pydantic v2 |
| Server | Uvicorn |
| Container | Docker |

---

## 🐳 Docker Compose — Containers

O `docker-compose.yml` unificado sobe **10 containers**:

| Container | Serviço | Porta Externa |
|-----------|---------|---------------|
| `composer` | API Gateway | 8080 |
| `auth-service` | Auth API | — (interna) |
| `auth-postgres` | Auth DB | — |
| `auth-redis` | Auth Cache | — |
| `inventory-service` | Inventory API | — (interna) |
| `inv-postgres` | Inventory DB | — |
| `inv-redis` | Inventory Cache | — |
| `payment-service` | Payment API | — (interna) |
| `pay-postgres` | Payment DB | — |
| `pay-redis` | Payment Cache | — |

Apenas o Composer expõe porta externamente (8080). Todos os outros serviços comunicam pela rede interna `flashsale`.
