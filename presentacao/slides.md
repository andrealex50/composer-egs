---
marp: true
title: FlashSale - EGS Microsserviços
paginate: true
---

# FlashSale

## Plataforma de bilhetes com microsserviços

Composer / API Gateway, Auth, Inventory, Payment e checkout orquestrado.

---

# Visão Geral

FlashSale permite consultar eventos, reservar bilhetes, pagar e receber confirmação de compra num fluxo único.

Por trás da interface existem serviços independentes, cada um dono do seu domínio.

---

# Stakeholders

## Fãs / Compradores

Querem encontrar eventos, comprar bilhetes e receber confirmação rapidamente.

## Promotores

Querem criar eventos, gerir bilhetes e acompanhar vendas.

---

# Stakeholders

## Operação

Precisa de health checks, métricas, logs e tracing para perceber falhas entre serviços.

## Pagamentos

Precisa de checkout, recibos, cancelamentos e uma separação clara entre pagamento e inventário.

---

# Serviços Fornecidos

- Autenticação e sessão de utilizadores
- Catálogo de eventos
- Inventário de bilhetes
- Carrinho e checkout
- Pagamentos e recibos
- KPIs, métricas e observabilidade

---

# Decisões de Escopo

O projeto privilegia integração entre serviços e consistência do fluxo principal.

Algumas funcionalidades ficam simples de propósito:

- Payment UI separado do frontend principal
- Auth UI separado para login/registo
- Composer sem base de dados própria de negócio
- compensações SAGA sem rollback total de bilhetes já vendidos

---

# Arquitectura

meter aqui diagrama-arquitectura

---

# Ideia Da Arquitectura

O frontend fala com uma API pública única: o Composer.

O Composer encaminha chamadas para os serviços certos e esconde do browser os detalhes internos de Auth, Inventory e Payment.

Cada serviço mantém a sua própria base de dados.

---

# Composer / API Gateway

---

# Composer - Ideia Principal

O Composer funciona como Backend for Frontend.

Responsabilidades:

- expor `/api/*` ao frontend
- validar sessão quando necessário
- transformar respostas para a UI
- orquestrar checkout e carrinho
- aplicar compensações quando uma etapa falha

---

# Composer - Operações

O Composer não é dono dos dados principais.

Ele coordena:

- Auth para identidade
- Inventory para eventos e bilhetes
- Payment para checkout, pagamentos e recibos

Isto reduz acoplamento no frontend e centraliza fluxos de negócio.

---

# Auth Service

---

# Auth - Ideia Principal

O Auth Service é responsável por identidade.

Inclui:

- registo
- login
- refresh token
- perfil do utilizador
- logout
- reset de password
- verificação interna de tokens

---

# Auth - Contrato

O Composer usa endpoints internos `/api/v1/auth/*`.

Mecanismos importantes:

- JWT Bearer token
- refresh token
- roles `fan`, `promoter` e `admin`
- Redis para denylist / estado de tokens
- `X-Service-Auth` para verificação interna

---

# Inventory Service

---

# Inventory - Ideia Principal

O Inventory Service é a fonte de verdade para eventos, bilhetes e disponibilidade.

Inclui:

- criação e publicação de eventos
- criação de bilhetes
- consulta de stock
- reserva temporária
- venda
- validação de entrada
- cancelamento/libertação quando aplicável

---

# Inventory - Ciclo Do Bilhete

O ciclo principal é:

`available -> reserved -> sold -> used`

Durante checkout, o Composer reserva primeiro. Só depois de o Payment confirmar pagamento é que o bilhete passa para vendido.

---

# Payment Service

---

# Payment - Ideia Principal

O Payment Service trata do lado financeiro.

Inclui:

- hosted checkout
- pagamentos
- confirmação
- cancelamento/refund
- clientes
- recibos
- API keys

O utilizador pode ser redirecionado para a UI própria de pagamento.

---

# Payment - Integração

O Composer cria a checkout session e recebe o `checkout_url`.

Depois:

- o browser abre a Payment UI
- o Payment valida a autorização
- o Payment redireciona o browser para sucesso ou cancelamento
- o Composer consulta o estado final e atualiza o Inventory

---

# APIs

meter aqui diagrama-apis

---

# APIs - Composer

O frontend chama apenas rotas `/api/*`.

Grupos principais:

- `/api/auth/*`
- `/api/events`
- `/api/tickets/*`
- `/api/payment-account`
- `/api/payments/*`
- `/api/checkout`
- `/api/refund`
- `/health` e `/metrics`

---

# APIs - Bilhetes

Rotas relevantes no Composer:

- `GET /api/tickets/{ticket_id}`
- `PUT /api/tickets/{ticket_id}/reserve`
- `PUT /api/tickets/{ticket_id}/sell`
- `PUT /api/tickets/{ticket_id}/use`
- `DELETE /api/tickets/{ticket_id}`
- `POST /api/tickets/{ticket_id}/cancel`

`POST /cancel` existe como alias de compatibilidade para o frontend.

---

# APIs - Pagamentos

Rotas principais no Composer:

- `GET /api/payments`
- `POST /api/payments`
- `GET /api/payments/{payment_id}`
- `POST /api/payments/{payment_id}/confirm`
- `POST /api/payments/{payment_id}/cancel`
- `GET /api/payments/{payment_id}/receipt`

No Payment Service, o cancelamento interno pode mapear para `DELETE /api/v1/payments/{payment_id}`.

---

# Contratos E Segurança

- `Authorization: Bearer <token>` para utilizadores autenticados
- `X-API-Key` para Inventory e Payment
- `X-Service-Auth` para verificação interna
- `Idempotency-Key` em mutações críticas
- `X-Request-ID` / `X-Correlation-ID` para rastreabilidade
- CORS configurado para as origens esperadas

---

# Fluxo De Checkout

meter aqui diagrama-checkout

---

# Orquestração SAGA

O checkout não é uma transação única.

O Composer coordena passos independentes:

1. valida utilizador
2. reserva bilhetes
3. cria checkout session
4. confirma pagamento
5. vende bilhetes reservados

---

# Compensações

Se algo falha, o Composer evita repetir efeitos, propaga o erro e só liberta reservas que ainda estejam reservadas.

Exemplos:

- se a reserva falha, não cria pagamento
- se o Payment falha, liberta reservas criadas
- se o utilizador cancela, cancela reservas pendentes
- se um bilhete já foi vendido, não promete rollback total

---

# Observabilidade

O sistema inclui:

- health checks por serviço
- métricas para Prometheus
- dashboards em Grafana
- tracing via OpenTelemetry e Jaeger
- MailHog para email em ambiente de desenvolvimento
- KPI dashboard agregado pelo Composer

---

# Demo

Fluxo recomendado:

1. abrir frontend
2. fazer login/registo
3. consultar eventos
4. escolher bilhete
5. comprar pelo checkout
6. voltar ao sucesso
7. confirmar carrinho limpo
8. ver health/métricas

---

# Resultado

O FlashSale apresenta ao utilizador uma experiência contínua:

`evento -> carrinho -> reserva -> pagamento -> bilhete vendido`

Internamente, a solução mantém serviços separados por domínio, contratos explícitos e observabilidade para diagnosticar falhas.
