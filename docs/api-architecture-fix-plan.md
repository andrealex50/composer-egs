# FlashSale / EGS API Architecture Fix Plan

This plan is based on `docs/api-architecture.md` and a validation pass against the current source code. It is intentionally a plan only: no application code is changed here.

Risk level means implementation risk and regression risk for the fix, not only severity of the current bug.

## Recommended Implementation Order

| Order | Fix | Reason |
|---:|---|---|
| 1 | Add Composer compatibility alias `POST /api/tickets/{ticket_id}/cancel` | Lowest-risk, backward-compatible, fixes a concrete frontend 404 |
| 2 | Normalize `ticket_category_id` vs `category` in Composer | Fixes ticket selection/reservation correctness while preserving frontend payloads |
| 3 | Fix `GET /api/events/{event_id}` response mapping | Prevents misleading `ticket_categories` data and improves frontend contract |
| 4 | Review and harden Composer payment endpoint authentication | Security-sensitive; may be breaking if clients call unauthenticated payment endpoints |
| 5 | Clarify Auth internal header usage or centralize constants/docs | Low code risk, but affects service-to-service clients if changed |
| 6 | Improve checkout compensation behavior after partial success | Business-critical but higher complexity because Payment and Inventory states interact |
| 7 | Clean infrastructure/documentation mismatches | Mostly documentation/config cleanup; do after API behavior is stable |
| 8 | Review Payment refund model/OpenAPI/static route documentation | Good cleanup, but not blocking the purchase flow |

## Fix Items

### 1. Frontend Calls `POST /api/tickets/{id}/cancel`, Composer Only Exposes `DELETE /api/tickets/{id}`

| Field | Details |
|---|---|
| Inconsistency | The React frontend calls `POST /api/tickets/${ticketId}/cancel`, but Composer implements only `DELETE /api/tickets/{ticket_id}` for the same logical action. |
| Files/functions/routes involved | `frontend/src/App.jsx:643`; `composer-egs/main.py:885` route `@app.delete("/api/tickets/{ticket_id}")`; function `cancel_ticket`; Inventory downstream `DELETE /api/v1/tickets/{ticket_id}`. |
| Risk level | Low |
| Proposed fix | In Composer, extract the existing `cancel_ticket` proxy logic into a helper such as `_cancel_ticket_via_inventory(ticket_id, request, authorization)`. Keep `DELETE /api/tickets/{ticket_id}` and add `POST /api/tickets/{ticket_id}/cancel` as a compatibility alias calling the same helper. |
| Breaking or backward-compatible | Backward-compatible. Existing DELETE behavior remains unchanged; frontend POST starts working. |
| Tests to update/add | Add Composer route test for `POST /api/tickets/{id}/cancel` verifying it calls Inventory `DELETE /api/v1/tickets/{id}`. Add regression test that existing `DELETE /api/tickets/{id}` still works. If no test suite exists, add curl/smoke-test examples for both routes. |
| Notes | This should be implemented first. It does not require frontend changes and fixes a real 404 path. |

### 2. Composer Uses `ticket_category_id`, Inventory Uses `category`

| Field | Details |
|---|---|
| Inconsistency | Composer request models and filters use `ticket_category_id`, while Inventory ticket schemas expose `category`. Some Composer paths only check `ticket_category_id`, so filtering can fail even when tickets exist. |
| Files/functions/routes involved | `composer-egs/main.py:500` `CheckoutRequest.ticket_category_id`; `main.py:515` `CartCheckoutItemRequest.ticket_category_id`; `main.py:942-944` reservation filter; `main.py:1203-1204` single checkout filter; `main.py:1377-1381` cart checkout filter already checks both; Inventory schema `inventory-service-egs/app/schemas/ticket.py` `TicketBatchCreate.category` and `TicketResponse.category`; frontend checkout payloads in `frontend/src/App.jsx:858` and `frontend/src/App.jsx:996`. |
| Risk level | Medium |
| Proposed fix | Implemented in Composer only with compatibility helpers. `_requested_ticket_category_from_mapping` and `_requested_ticket_category_from_model` accept `category` first and legacy `ticket_category_id` second. `_ticket_matches_requested_category` filters Inventory tickets by canonical `category` with a legacy fallback. `_normalize_ticket_batch_payload_for_inventory` maps legacy `ticket_category_id` into Inventory's `category` field before ticket batch creation and removes the legacy key from the downstream payload. |
| Breaking or backward-compatible | Backward-compatible. Frontend can keep sending `ticket_category_id`; Inventory remains unchanged. Existing clients already sending `category` continue to work. |
| Tests to update/add | Unit test/helper test for matching tickets with `category`, legacy `ticket_category_id`, and no match. Composer endpoint tests for `POST /api/reservations`, `POST /api/checkout`, and `POST /api/checkout/cart` using both payload styles. Add a ticket creation proxy test proving `ticket_category_id` becomes `category` only when `category` is absent. |
| Notes | Inventory was not changed. Inventory contract remains clear: tickets have `category`. Composer now preserves backward compatibility for existing frontend payloads. |

Validation examples for both accepted payload styles:

```bash
# Canonical Inventory-compatible style
curl -X POST http://composer.flashsale/api/checkout \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"event_id":"EVENT_ID","quantity":1,"category":"VIP","success_url":"http://composer.flashsale/success","cancel_url":"http://composer.flashsale/cancel","amount_cents":1000}'

# Legacy frontend-compatible style
curl -X POST http://composer.flashsale/api/checkout \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"event_id":"EVENT_ID","quantity":1,"ticket_category_id":"VIP","success_url":"http://composer.flashsale/success","cancel_url":"http://composer.flashsale/cancel","amount_cents":1000}'
```

### 3. `GET /api/events/{id}` Maps Raw Tickets Into `ticket_categories`

| Field | Details |
|---|---|
| Inconsistency | Composer adds `event_data["ticket_categories"] = tickets.get("data", [])`, but Inventory returns individual ticket objects, not aggregated category objects. |
| Files/functions/routes involved | `composer-egs/main.py:762` route `@app.get("/api/events/{event_id}")`; function `get_event`; `main.py:776` assignment to `ticket_categories`; downstream Inventory `GET /api/v1/events/{event_id}` and `GET /api/v1/events/{event_id}/tickets`; frontend event-detail usage should be inspected in `frontend/src/App.jsx`. |
| Risk level | Medium |
| Proposed fix | Implemented the backward-compatible response shape: `tickets` contains raw Inventory ticket rows, `tickets_total` contains the fetched ticket count, and `ticket_categories` is now a real grouped summary by Inventory `category`. Composer paginates Inventory tickets in pages of 100 before building the summary. |
| Breaking or backward-compatible | Mostly backward-compatible because `ticket_categories` remains present, but its contents are now grouped summaries instead of raw tickets. Frontend search found no current dependency on `ticket_categories`, so the practical breaking risk is low. |
| Tests to update/add | Composer test for event detail with mocked Inventory tickets across multiple categories. Assert `tickets` contains raw list and `ticket_categories` contains grouped summaries with `category`, `currency`, `min_price`, `total_count`, `available_count`, `reserved_count`, `sold_count`, and `used_count`. |
| Notes | The old misleading raw-ticket mapping is removed. Raw tickets are still available through the correctly named `tickets` field. |

Validation example:

```bash
curl -s http://composer.flashsale/api/events/EVENT_ID | jq '{id, tickets_total, tickets, ticket_categories}'
```

### 4. Some Composer Public Payment Endpoints Do Not Require Bearer Auth

| Field | Details |
|---|---|
| Inconsistency | Composer hides Payment `X-API-Key`, but exposes some payment routes publicly without requiring a user Bearer token. |
| Files/functions/routes involved | Protected today: `main.py:986` `list_payments`, `main.py:1034` `get_payment_account`, `main.py:1045` `setup_payment_account`, `main.py:1079` `get_payment`, `main.py:1116` `download_receipt`, `main.py:1161` `checkout`, `main.py:1293` `checkout_cart`, `main.py:1602` `process_refund`. Missing Bearer today: `main.py:1071` `create_payment`, `main.py:1098` `confirm_payment`, `main.py:1107` `cancel_payment`. Payment downstream routes: `POST /api/v1/payments`, `PUT /api/v1/payments/{id}/confirm`, `DELETE /api/v1/payments/{id}`. |
| Risk level | High |
| Proposed fix | First create `docs/payment-endpoint-auth-review.md` to classify intended caller and expected auth per route. Then add Bearer auth and ownership checks to `POST /api/payments`, `POST /api/payments/{id}/confirm`, and `POST /api/payments/{id}/cancel`, unless they are proven to be service-to-service only. For cancel/confirm, verify payment ownership by fetching Payment detail and comparing `customer_id` or Composer metadata `composer_initiator_auth_user_id`. |
| Breaking or backward-compatible | Potentially breaking. If any existing client calls these routes without Bearer, it will start receiving 401. Could stage via compatibility mode/env flag if required. |
| Tests to update/add | Auth tests for 401 when missing Bearer. Ownership tests for 404/403 when authenticated user does not own the payment. Positive tests for owner. Regression tests for checkout flow, refund flow, receipt access, and payment list. |
| Notes | Do not rush this as a "quick fix". It is security-sensitive and should be reviewed after the low-risk compatibility fixes. |

### 5. Auth Uses `X-Service-Auth` For Verify But `X-Internal-Service-Key` For KPI

| Field | Details |
|---|---|
| Inconsistency | Auth internal endpoints use two different header names for the same shared secret. Token verification requires `X-Service-Auth`; KPI snapshot requires `X-Internal-Service-Key`. |
| Files/functions/routes involved | `EGS/auth-service/app/api/v1/auth.py:408` route `POST /api/v1/auth/verify`; `auth.py:413` header alias `X-Service-Auth`; `EGS/auth-service/app/api/kpi.py:15` header alias `X-Internal-Service-Key`; `app/api/kpi.py:32` route `GET /internal/kpi/snapshot`; Composer usage in `composer-egs/main.py:339` and `main.py:1683`. |
| Risk level | Low to medium |
| Proposed fix | Decide if this is intentional separation or accidental inconsistency. Lowest-risk fix is documentation plus named constants in Composer (`AUTH_VERIFY_HEADER`, `AUTH_KPI_HEADER`) to prevent accidental swapping. If changing Auth, accept both headers on KPI or verify as a backward-compatible transition, while documenting the preferred header. |
| Breaking or backward-compatible | Documentation/constants only: backward-compatible. Accepting both headers: backward-compatible. Renaming one header: breaking and not recommended without versioning. |
| Tests to update/add | Auth test that `/api/v1/auth/verify` accepts `X-Service-Auth`. Auth test that `/internal/kpi/snapshot` accepts `X-Internal-Service-Key`. If dual-header support is added, tests for both accepted headers and invalid secret rejection. Composer KPI test to assert correct header. |
| Notes | Since both routes work as currently coded, this is more of an operability/API-consistency problem than an immediate runtime bug. |

### 6. Payment OpenAPI Security Overstates `X-API-Key` Requirements

| Field | Details |
|---|---|
| Inconsistency | Payment middleware exempts static/checkout/user routes from API-key auth, but OpenAPI adds global `X-API-Key`, which may imply those endpoints need an API key. |
| Files/functions/routes involved | `Payment_service/app/main.py` custom OpenAPI/security setup and auth middleware; Payment routes `GET /api/v1/checkout/{session_id}`, `POST /api/v1/checkout/{session_id}/authorize`, `GET /api/v1/customers/me/transactions`, static `/wallet/*`, `/checkout/{session_id}`. |
| Risk level | Low |
| Proposed fix | Update Payment OpenAPI generation to override security per exempt route, or document exceptions clearly in Payment README and `docs/api-architecture.md`. |
| Breaking or backward-compatible | Backward-compatible documentation/OpenAPI fix. |
| Tests to update/add | OpenAPI snapshot/assertion that exempt endpoints either have empty security or a correct Bearer-only requirement. Runtime smoke tests confirming no `X-API-Key` required for public checkout detail and authorize still requires Bearer. |
| Notes | This affects API consumers and professor review more than runtime behavior. |

### 7. Payment Has `Refund` Model/Table But Current Refund Path Updates Payment Status Only

| Field | Details |
|---|---|
| Inconsistency | A `Refund` model exists, but the current cancel/refund behavior is through `DELETE /api/v1/payments/{payment_id}` and updates the payment status/amount instead of creating a separate refund resource. |
| Files/functions/routes involved | `Payment_service/app` payment models/services; Payment route `DELETE /api/v1/payments/{payment_id}`; Composer route `POST /api/refund` in `composer-egs/main.py:1602`. |
| Risk level | Medium |
| Proposed fix | Choose one contract: either keep simple payment-state refund and remove/ignore unused Refund model from docs, or implement explicit refund rows and optional `POST /api/v1/payments/{id}/refunds`. For the current project phase, document the actual behavior and do not add a new Payment API unless required. |
| Breaking or backward-compatible | Documentation-only: backward-compatible. Adding a new refund resource can be backward-compatible if existing DELETE behavior remains. Removing model/table may be breaking for migrations. |
| Tests to update/add | Payment cancel/refund tests for pending -> canceled and succeeded -> refunded. If refund rows are implemented, migration and receipt/refund tests. Composer `POST /api/refund` test asserting Payment DELETE is called. |
| Notes | Not a first-pass implementation item unless refund auditability is required. |

### 8. Payment Auth Is Separate From Composer Auth

| Field | Details |
|---|---|
| Inconsistency | Payment verifies checkout tokens against `payment-auth-service`, while Composer verifies users against `auth-service`. These are separate Auth deployments with separate DB/Redis/JWT/cookie settings. |
| Files/functions/routes involved | `composer-egs/docker-compose.yml` services `auth-service` and `payment-auth-service`; `EGS_k8s/03-apps.yaml` deployments; Payment env `AUTH_SERVICE_URL=http://payment-auth-service:8000`; Composer env `AUTH_SERVICE_URL=http://auth-service:8000`; Auth UI and Payment UI flows. |
| Risk level | High if unifying; low if documenting |
| Proposed fix | Product decision needed. Either keep separate identities and make the UI/flows explicit, or configure Payment to verify against the same Auth Service as Composer if one identity is intended. Do not change this casually because JWT secrets, cookies, users and sessions differ. |
| Breaking or backward-compatible | Keeping and documenting: backward-compatible. Unifying Auth: breaking for Payment Auth users/tokens unless migrated. |
| Tests to update/add | End-to-end checkout test using the intended Auth authority. If unifying, token verification tests proving Composer token is accepted by Payment authorize. Migration/compatibility test for existing Payment Auth tokens if needed. |
| Notes | This is architecture-level, not a small bug. |

### 9. Docker And Kubernetes Public Observability Routes Differ

| Field | Details |
|---|---|
| Inconsistency | Docker Traefik exposes `vault.flashsale`, `grafana.flashsale`, `jaeger.flashsale`, but not Prometheus/MailHog. Kubernetes exposes `/grafana`, `/prometheus`, `/jaeger`, `/mail`, but not `/vault`. |
| Files/functions/routes involved | `composer-egs/traefik/dynamic.yml`; `composer-egs/docker-compose.yml`; `EGS_k8s/05-ingress.yaml`; `EGS_k8s/04-observability.yaml`. |
| Risk level | Low |
| Proposed fix | Keep as documented if intentional. If parity is desired, add missing Docker Traefik routers for Prometheus/MailHog and/or add a K8s `/vault` path only if exposing Vault is acceptable. |
| Breaking or backward-compatible | Usually backward-compatible if adding routes. Removing public Vault would be breaking for dev users but safer. |
| Tests to update/add | Smoke tests for each documented public observability URL in Docker and K8s. |
| Notes | Exposing Vault publicly should be reviewed from a security perspective. |

### 10. Docker Compose YAML Has Suspicious Duplicate Keys/Entries

| Field | Details |
|---|---|
| Inconsistency | `docker-compose.yml` appears to contain a duplicate `services-net:` network key and a duplicated `observability-net` entry under `payment-auth-service`. |
| Files/functions/routes involved | `composer-egs/docker-compose.yml`; Docker Compose parser behavior. |
| Risk level | Medium |
| Proposed fix | Normalize the Compose file: remove duplicate network key and duplicate list entry, then run `docker compose config` to see the effective configuration. Commit only if effective output remains equivalent. |
| Breaking or backward-compatible | Intended to be backward-compatible, but network changes can break service discovery if the duplicate key currently masks a value. |
| Tests to update/add | `docker compose config`; `docker compose up --build -d`; Composer `/health`; E2E smoke test. |
| Notes | This is infrastructure cleanup, not application code. |

### 11. Inventory Standalone DB Name Differs From Integrated Deployment

| Field | Details |
|---|---|
| Inconsistency | Standalone Inventory deployment and integrated Composer/K8s deployment use different DB naming/configuration conventions. |
| Files/functions/routes involved | `inventory-service-egs/docker-compose.yml`; `composer-egs/docker-compose.yml`; `EGS_k8s/00-secrets.yaml`; Inventory DB settings. |
| Risk level | Low |
| Proposed fix | Document that each environment injects its own `DATABASE_URL`. Optionally align DB names for developer clarity if no data migration is needed. |
| Breaking or backward-compatible | Documentation-only: backward-compatible. Renaming DB: breaking for existing local volumes unless migrated. |
| Tests to update/add | Inventory `/health` in standalone and integrated stacks. Migration check against active `DATABASE_URL`. |
| Notes | Keep as documentation unless it actively confuses setup. |

### 12. Checkout Partial Success Compensation Is Limited

| Field | Details |
|---|---|
| Inconsistency | In checkout success handling, Composer can try to cancel/release tickets after some were already sold, but Inventory `DELETE /api/v1/tickets/{id}` only releases RESERVED tickets and returns conflict for SOLD tickets. |
| Files/functions/routes involved | Composer success callback `GET /api/checkout/success` in `composer-egs/main.py:1507`; helper `_cancel_reserved_ticket` in `main.py:474`; Inventory `DELETE /api/v1/tickets/{ticket_id}` release route; Inventory ticket lifecycle `available -> reserved -> sold -> used`. |
| Risk level | High |
| Proposed fix | Make success callback idempotent and explicit: if Payment is paid, retry selling reserved tickets; tolerate already sold/used; record/report partial failures instead of attempting to "release" sold tickets. If true rollback is required, add an explicit Inventory compensation endpoint/state transition for sold-ticket cancellation. |
| Breaking or backward-compatible | Idempotency/reporting improvement can be backward-compatible. Adding new Inventory state transitions may be breaking from a business-rules perspective. |
| Tests to update/add | Saga tests for all success callback cases: all reserved sell successfully, ticket already sold, one ticket missing, one sell conflict, repeated success callback. Inventory tests for release only working on RESERVED. |
| Notes | This should come after compatibility/schema fixes because it touches core business consistency. |

### 13. `CheckoutRequest.amount_cents` Is Present But Not Authoritative

| Field | Details |
|---|---|
| Inconsistency | Composer request model includes `amount_cents`, but checkout uses price from reserved Inventory tickets instead. |
| Files/functions/routes involved | `composer-egs/main.py:496-502` `CheckoutRequest`; `composer-egs/main.py:1161` `checkout`; frontend payload build in `frontend/src/App.jsx:858`. |
| Risk level | Low |
| Proposed fix | Keep ignoring client-provided amount for security, but rename/deprecate it in docs. In code, make it optional or remove only after frontend no longer sends it. Optionally validate that if provided it matches Inventory price and log mismatch. |
| Breaking or backward-compatible | Making optional and documenting ignored behavior is backward-compatible. Removing field is breaking if frontend still sends or Pydantic rejects unknown/missing fields depending config. |
| Tests to update/add | Checkout request test without `amount_cents` if made optional. Test that price used in Payment line items comes from Inventory, not client amount. |
| Notes | This is actually safer than trusting frontend price; fix is mostly naming/contract clarity. |

### 14. Static UI Routes Are Not OpenAPI Endpoints

| Field | Details |
|---|---|
| Inconsistency | Auth templates/static routes and Payment wallet/checkout pages can be confused with REST API endpoints. |
| Files/functions/routes involved | Auth frontend static paths under `/auth/templates` and `/auth/static`; Payment static routes `/wallet/login`, `/wallet/register`, `/wallet/dashboard`, `/checkout/{session_id}` in `Payment_service/app/main.py`; `docs/api-architecture.md` static UI section. |
| Risk level | Low |
| Proposed fix | Keep these in a separate "Static UI routes" section in docs and avoid adding them to API endpoint tables except as non-OpenAPI browser pages. |
| Breaking or backward-compatible | Documentation-only, backward-compatible. |
| Tests to update/add | None required beyond route smoke tests for pages. |
| Notes | Already handled in the architecture doc; continue preserving separation. |

### 15. Vite Dev Proxy Depends On Public Host Configuration

| Field | Details |
|---|---|
| Inconsistency | Frontend dev proxy points `/api` to `http://composer.flashsale`, so local `npm run dev` requires Traefik/hosts to resolve. Without that, browser calls can hit Vite and return 404. |
| Files/functions/routes involved | `composer-egs/frontend/vite.config.js`; `composer-egs/frontend/.env.local`; Composer public host `composer.flashsale`; previous observed browser errors on `localhost:5173/api/*`. |
| Risk level | Low |
| Proposed fix | Document the required local hosts/Traefik setup, or allow `VITE_API_PROXY_TARGET`/env override to point to `http://localhost:<composer-port>` when running Composer directly. |
| Breaking or backward-compatible | Backward-compatible if default remains `composer.flashsale` and override is optional. |
| Tests to update/add | Frontend dev smoke test with default proxy and with local override. |
| Notes | Useful developer-experience fix, not a production API change. |

## Cross-Cutting Test Plan

| Test area | Recommended checks |
|---|---|
| Composer route compatibility | Verify `DELETE /api/tickets/{id}` and `POST /api/tickets/{id}/cancel` both call Inventory DELETE and return equivalent responses. |
| Category compatibility | Verify reservation, single checkout, cart checkout, and ticket creation with both `ticket_category_id` and `category`. |
| Event detail response | Verify event detail returns stable raw `tickets` and either grouped or legacy-compatible `ticket_categories`. |
| Payment auth hardening | Verify missing Bearer returns 401, wrong owner gets hidden/denied, owner succeeds, and checkout/refund flows still pass. |
| Auth internal headers | Verify `X-Service-Auth` and `X-Internal-Service-Key` are used on the right endpoints. |
| Saga compensation | Verify partial reservation failures, payment-session creation failures, checkout cancel, repeated success callback, and already-sold tickets. |
| Infrastructure | Run `docker compose config`, `docker compose up --build -d`, Composer `/health`, Composer `/metrics`, and K8s `kubectl apply --dry-run=client -k .`. |

## Suggested Validation Commands

```bash
# Documentation/source consistency
rg -n "api/tickets/.*/cancel|ticket_category_id|ticket_categories|api/payments|X-Service-Auth|X-Internal-Service-Key" \
  /home/andrealex/composer-egs \
  /home/andrealex/EGS/auth-service \
  /home/andrealex/inventory-service-egs \
  /home/andrealex/Payment_service

# Composer syntax check after code changes
cd /home/andrealex/composer-egs
python3 -m py_compile main.py

# Docker effective configuration
docker compose config

# Mermaid/doc validation after documentation changes
for f in docs/diagrams/*.mmd; do
  npx @mermaid-js/mermaid-cli -i "$f" -o "/tmp/$(basename "${f%.mmd}").svg"
done
```
