# Composer Payment Endpoint Auth Review

This review inspects the Composer public payment-related routes in `composer-egs/main.py`. No application code was changed for this review.

Composer is a browser-facing BFF. The Payment Service API key is hidden inside Composer and added to downstream Payment calls as `X-API-Key`. That means any Composer route that proxies to Payment without checking a user Bearer token effectively exposes privileged Payment operations to the browser.

## Summary

| Route | Intended caller | Actual auth in Composer | Expected auth | Risk | Proposed change | Breaking risk | Tests needed |
|---|---|---|---|---|---|---|---|
| `GET /api/payments` | Browser user | Requires `Authorization: Bearer`; verifies Auth claims; filters Payment results by local Payment customer id or Composer initiator metadata | Bearer token required; only own payments returned | Low | Keep current model. Consider adding tests for metadata ownership and pagination. | None | Missing Bearer -> 401; owner sees own payments; non-owner does not see others |
| `POST /api/payments` | Not used by current frontend; likely service-to-service/admin or authenticated user creating own payment | No Bearer token required; Composer adds Payment `X-API-Key` | At minimum Bearer token required. Prefer authenticated user must have or create Payment customer; Composer should set/validate `customer_id` or initiator metadata. If service-to-service, move under an internal route/header. | High | Require Bearer and bind payment creation to authenticated identity. Reject arbitrary `customer_id` unless admin/promoter policy allows it. | Medium to high if external clients call it anonymously | Missing Bearer -> 401; arbitrary customer_id rejected; authenticated owner can create; admin/service path if needed |
| `GET /api/payments/{id}` | Browser user | Requires Bearer; fetches Payment customer by email; fetches payment; returns 404 if `customer_id` differs | Bearer token required; own payment only | Low to medium | Keep auth. Consider matching Composer initiator metadata too, because list/receipt already allow metadata ownership. | Low | Missing Bearer -> 401; owner -> 200; non-owner -> 404; metadata-owned payment -> expected behavior decided |
| `POST /api/payments/{id}/confirm` | Should be service-to-service/admin, not normal public browser | No Bearer token required; Composer maps to Payment `PUT /api/v1/payments/{id}/confirm` with `X-API-Key` | Require Bearer plus admin/promoter role, or make internal-only. Normal users should not confirm arbitrary payments directly. | High | Add Bearer check and role/ownership policy. If this route is legacy/debug only, hide behind admin role or remove from UI docs. | Medium to high | Missing Bearer -> 401; fan -> 403; admin/promoter -> 200 for valid payment; invalid id -> propagated error |
| `POST /api/payments/{id}/cancel` | Browser user cancel/refund or admin/service operation, depending product decision | No Bearer token required; Composer maps to Payment `DELETE /api/v1/payments/{id}` with `X-API-Key` | Require Bearer. For user cancellation/refund, verify payment ownership before deleting/refunding. For admin cancellation, require admin/promoter role. | High | Add Bearer check, fetch payment first, verify owner by Payment customer id or Composer initiator metadata, then call Payment DELETE. Consider reusing refund ownership logic. | Medium to high | Missing Bearer -> 401; non-owner -> 404/403; owner pending payment -> canceled; owner succeeded payment -> refunded if allowed |
| `GET /api/payments/{id}/receipt` | Browser user | Requires Bearer; checks Payment customer id or `composer_initiator_auth_user_id` metadata before returning PDF | Bearer token required; own receipt only | Low | Keep current model. Align `GET /api/payments/{id}` with the same metadata ownership rule. | None | Missing Bearer -> 401; owner -> PDF; non-owner -> 404; non-succeeded payment behavior from Payment |
| `GET /api/payment-account` | Browser user | Requires Bearer via Auth profile; looks up Payment customer by email | Bearer token required | Low | Keep current model. | None | Missing Bearer -> 401; existing customer -> exists true; no customer -> exists false |
| `POST /api/payment-account/setup` | Browser user | Requires Bearer; idempotently creates Payment customer for Auth email | Bearer token required | Low | Keep current model. Ensure created customer metadata includes Auth user id. | None | Missing Bearer -> 401; first call creates; second call returns existing |
| `POST /api/checkout` | Browser user buying tickets | Requires Bearer; gets Auth profile; checks wallet/customer; reserves Inventory tickets; creates Payment checkout session with service API key | Bearer token required | Low | Keep current model. Continue deriving amount from Inventory, not request body. | None | Missing Bearer -> 401; event unpublished -> 409; reserve failure compensates; success returns public checkout URL |
| `POST /api/checkout/cart` | Browser user buying multiple items | Requires Bearer; gets Auth profile; reserves multiple Inventory tickets; creates one Payment checkout session | Bearer token required | Low | Keep current model. | None | Missing Bearer -> 401; mixed currency -> 409; partial failure compensates all reserved tickets |
| `POST /api/refund` | Browser user requesting refund | Requires Bearer and verifies token, but does not verify payment ownership before calling Payment DELETE | Bearer token present, plus ownership/admin authorization before refund/cancel | High | Fetch payment first, verify ownership by Payment customer id or Composer initiator metadata, then delete/refund. If admin refund allowed, require admin/promoter role. | Medium | Missing Bearer -> 401; non-owner -> 404/403 and no Payment DELETE; owner -> Payment DELETE and Inventory release attempts |

## Callback Routes Adjacent To Payment

These routes were not in the original payment endpoint list, but they are part of the checkout payment flow.

| Route | Intended caller | Actual auth | Risk | Recommendation |
|---|---|---|---|---|
| `GET /api/checkout/success` | Browser redirect callback from Payment checkout UI | Public; uses `session_id` to read Payment checkout session and sell Inventory tickets | Medium | Keep public redirect behavior, but make it idempotent and validate session metadata carefully. A repeated callback should not corrupt state. |
| `GET /api/checkout/cancel` | Browser redirect callback from Payment checkout UI | Public; releases ticket ids provided in query string | Medium | Avoid trusting arbitrary `tickets` query alone. Prefer loading checkout session metadata by `session_id`, or sign/validate cancel parameters. |

## Current Implementation Notes

| Area | Notes |
|---|---|
| Downstream Payment auth | Composer always uses the server-side `PAYMENT_API_KEY` for Payment business endpoints. This is correct for service-to-service calls, but it increases the importance of Composer-side user authorization. |
| Ownership model | Composer uses Payment customer email lookup for several endpoints. Some routes also rely on metadata `composer_initiator_auth_user_id`. The model should be made consistent across list/detail/receipt/refund/cancel. |
| Admin model | Payment Service has admin API keys for Payment admin routes, but Composer public payment routes currently do not have a clear admin-vs-user split for confirm/cancel. |
| Frontend usage | Current React frontend uses `GET /api/payments`, `GET /api/payments/{id}/receipt`, `GET /api/payment-account`, `POST /api/payment-account/setup`, `POST /api/checkout`, `POST /api/checkout/cart`, and `POST /api/refund`. It does not appear to use `POST /api/payments`, `POST /api/payments/{id}/confirm`, or `POST /api/payments/{id}/cancel` directly. |

## Recommended Implementation Order

1. Add tests around the current auth behavior for all Composer payment routes before changing policy.
2. Harden `POST /api/refund` ownership first, because the frontend uses it and it can call Payment DELETE.
3. Harden `POST /api/payments/{id}/cancel` next by requiring Bearer and ownership/admin policy.
4. Harden or restrict `POST /api/payments/{id}/confirm`; likely admin/promoter or internal-only.
5. Harden `POST /api/payments`; either require Bearer and bind to current user, or move to an internal/admin-only integration path.
6. Align `GET /api/payments/{id}` with receipt/list ownership behavior if metadata-owned checkout payments can lack a matching customer id.
7. Review callback trust model for `/api/checkout/success` and `/api/checkout/cancel`.

## Suggested Tests

| Test | Expected result |
|---|---|
| Missing Bearer on all browser-user payment routes | 401 |
| Authenticated user lists payments | Only owned payments returned |
| Authenticated user reads another user's payment | 404 or 403, no payment details leaked |
| Authenticated non-owner refund attempt | No Payment DELETE call; 404 or 403 |
| Authenticated owner refund attempt | Payment DELETE called once; Inventory release attempted only for supplied/owned ticket ids |
| Fan calls confirm route | 403 if route remains public but admin-gated |
| Admin/promoter calls confirm route | Confirmation succeeds for valid payment |
| Public checkout success callback replay | Idempotent success, no duplicate sell side effects |
| Public checkout cancel with tampered ticket ids | Rejected or ignored unless session metadata validates ownership |

## Validation Commands

```bash
rg -n '@app\\.(get|post)\\("/api/(payments|payment-account|checkout|refund)' main.py
rg -n 'Authorization|_get_authenticated_claims|_get_authenticated_user_profile|_verify_user_token|PAYMENT_API_KEY|/api/v1/payments' main.py
python3 -m py_compile main.py
```
