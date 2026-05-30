---
marp: true
title: FlashSale - Composer / API Gateway
paginate: true
---

# FlashSale

## Composer / API Gateway

Plataforma de venda de bilhetes para eventos, com autenticação, inventário, pagamentos e checkout orquestrado num único fluxo.

---

# Ideia

FlashSale é uma plataforma para comprar e gerir bilhetes de eventos.

O utilizador entra no frontend, consulta eventos publicados, adiciona bilhetes ao carrinho e faz checkout através de um fluxo de pagamento separado.

Por trás, o Composer junta serviços independentes e apresenta ao frontend uma API única.

---

# Problema

Sem Composer, o frontend teria de conhecer diretamente vários serviços:

- Auth para login, sessão e perfil
- Inventory para eventos, bilhetes e reservas
- Payment para conta de pagamento, checkout e recibos
- regras de compensação quando uma compra falha

Isto aumenta acoplamento e espalha lógica de negócio pelo browser.

---

# Solução

O Composer funciona como API Gateway e Backend for Frontend.

Ele recebe chamadas `/api/*` do frontend, fala com os microsserviços internos e devolve uma resposta já adaptada à experiência da aplicação.

Também concentra fluxos de orquestração como checkout, cancelamento e reembolso.

---

# Arquitectura

Diagrama principal: [diagrama-arquitectura.md](./diagrama-arquitectura.md)

Camadas principais:

- Frontend React
- Composer / FastAPI Gateway
- Auth Service
- Inventory Service
- Payment Service
- Postgres e Redis por domínio
- Vault, Traefik e observabilidade

---

# Componentes

## Frontend React

Interface usada pelo cliente para:

- consultar eventos publicados
- gerir carrinho
- autenticar sessão
- iniciar checkout
- consultar conta, pagamentos e recibos

Durante desenvolvimento, o Vite encaminha `/api/*` para o Composer.

---

# Componentes

## Composer / API Gateway

Responsabilidades:

- expor uma API única ao frontend
- fazer proxy para Auth, Inventory e Payment
- enriquecer dados de eventos com preço mínimo
- aplicar regras de roles para operações de gestão
- orquestrar checkout e reembolso
- expor health checks, métricas e KPI dashboard

---

# Componentes

## Auth Service

Responsável por identidade e sessão:

- registo e login
- refresh token
- perfil do utilizador
- logout
- reset de password
- verificação interna de tokens

O Composer usa o Auth para validar quem está a comprar ou a gerir eventos.

---

# Componentes

## Inventory Service

Responsável por stock e ciclo de vida dos bilhetes:

- eventos publicados
- criação e atualização de eventos
- emissão de bilhetes por evento
- reserva temporária de bilhetes
- confirmação de venda
- validação de utilização
- cancelamento de reservas

É a fonte de verdade para disponibilidade.

---

# Componentes

## Payment Service

Responsável por pagamentos e checkout:

- criação de hosted checkout sessions
- conta local de pagamento
- carteira / wallet UI
- listagem de pagamentos
- confirmação ou cancelamento
- recibos
- refund/cancel quando necessário

O checkout é iniciado pelo Composer, mas a autorização do pagamento acontece no Payment.

---

# Componentes

## Infraestrutura

- Traefik: entrada HTTP e roteamento por domínio
- Vault: gestão de segredos em ambiente local
- Postgres: persistência por serviço
- Redis: cache/sessões/apoio operacional por serviço
- OpenTelemetry Collector: recolha de métricas
- Prometheus: armazenamento de métricas
- Grafana: dashboards
- Jaeger: tracing

---

# APIs

Mapa de APIs: [diagrama-apis.md](./diagrama-apis.md)

O frontend chama sempre o Composer:

| Domínio | Prefixo público |
| --- | --- |
| Auth | `/api/auth/*` |
| Eventos | `/api/events/*` |
| Bilhetes | `/api/events/{id}/tickets`, `/api/tickets/*` |
| Reservas | `/api/reservations/*` |
| Pagamentos | `/api/payments/*`, `/api/payment-account` |
| Checkout | `/api/checkout`, `/api/checkout/cart` |
| Observabilidade | `/health`, `/metrics`, `/api/kpi/dashboard` |

---

# APIs - Auth

Principais endpoints expostos pelo Composer:

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/refresh`
- `GET /api/auth/me`
- `POST /api/auth/logout`
- `POST /api/auth/forgot-password`
- `POST /api/auth/reset-password`
- `DELETE /api/auth/me`
- `POST /api/auth/browser/handoff`
- `POST /api/auth/browser/exchange`

Internamente mapeia para `/api/v1/auth/*` no Auth Service.

---

# APIs - Eventos e Bilhetes

Eventos:

- `GET /api/events`
- `POST /api/events`
- `GET /api/events/{event_id}`
- `PUT /api/events/{event_id}`
- `DELETE /api/events/{event_id}`

Bilhetes:

- `POST /api/events/{event_id}/tickets`
- `GET /api/events/{event_id}/tickets`
- `GET /api/tickets/{ticket_id}`
- `GET /api/tickets/{ticket_id}/availability`
- `PUT /api/tickets/{ticket_id}/reserve`
- `PUT /api/tickets/{ticket_id}/sell`
- `PUT /api/tickets/{ticket_id}/use`
- `DELETE /api/tickets/{ticket_id}`
- `POST /api/tickets/{ticket_id}/cancel` alias de compatibilidade

---

# APIs - Pagamentos e Checkout

Pagamentos:

- `GET /api/payment-account`
- `POST /api/payment-account/setup`
- `GET /api/payments`
- `POST /api/payments`
- `GET /api/payments/{payment_id}`
- `POST /api/payments/{payment_id}/confirm`
- `POST /api/payments/{payment_id}/cancel`
- `GET /api/payments/{payment_id}/receipt`

Checkout:

- `POST /api/checkout`
- `POST /api/checkout/cart`
- `GET /api/checkout/success`
- `GET /api/checkout/cancel`
- `POST /api/refund`

---

# Fluxo Principal

Diagrama do checkout: [diagrama-checkout.md](./diagrama-checkout.md)

1. Utilizador escolhe evento e bilhetes.
2. Frontend pede checkout ao Composer.
3. Composer valida sessão no Auth.
4. Composer reserva bilhetes no Inventory.
5. Composer cria checkout session no Payment.
6. Utilizador paga no hosted checkout.
7. Payment chama callback do Composer.
8. Composer confirma venda dos bilhetes no Inventory.

---

# Orquestração SAGA

O checkout não é uma única transação de base de dados.

Por isso o Composer usa compensações:

- se a reserva falha, não cria pagamento
- se o Payment falha, cancela as reservas criadas
- se o utilizador cancela checkout, liberta os bilhetes
- se o pagamento não fica pago, cancela as reservas
- se a confirmação de venda falha, evita repetir efeitos, propaga erro e só liberta reservas que ainda estejam reservadas

Isto evita bilhetes presos ou vendidos sem pagamento válido.

---

# Segurança

Principais mecanismos:

- JWT Bearer token para chamadas autenticadas
- refresh token via Auth
- `INTERNAL_SERVICE_KEY` para chamadas internas privilegiadas
- `INVENTORY_API_KEY` e `PAYMENT_API_KEY` para integração entre serviços
- roles `admin` e `promoter` para gerir eventos e bilhetes
- CORS limitado às origens esperadas do frontend
- idempotency keys em mutações críticas

---

# Observabilidade

O sistema expõe:

- `GET /health` para estado geral e dependências
- `/metrics` para Prometheus
- `/api/kpi/dashboard` para dashboard operacional no frontend
- tracing via OpenTelemetry e Jaeger
- métricas agregadas em Prometheus/Grafana

Isto ajuda a perceber rapidamente se Auth, Inventory ou Payment estão offline.

---

# Demonstração

Fluxo recomendado:

1. Abrir frontend React.
2. Registar/login no Auth.
3. Criar ou usar evento publicado.
4. Criar bilhetes para o evento.
5. Comprar bilhete pelo checkout.
6. Confirmar que o carrinho fica limpo após sucesso.
7. Ver pagamentos/recibos na área de conta.
8. Mostrar `GET /health` com serviços online.

---

# Resultado

O Composer reduz a complexidade no frontend e dá uma API única para a experiência FlashSale.

A arquitectura fica separada por domínios, mas o utilizador vê um fluxo contínuo:

evento -> carrinho -> reserva -> pagamento -> bilhete vendido
