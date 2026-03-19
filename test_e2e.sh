#!/bin/bash
# ======================================================
# FlashSale Composer - E2E Integracao (Auth+Inventory+Payment)
# Valida os 3 servicos atraves do Composer (porta 8080)
# ======================================================

set -u
set -o pipefail

BASE="http://localhost:8080"
PASSED=0
FAILED=0
TOTAL=0

pass() { ((PASSED++)); ((TOTAL++)); echo "  PASS"; }
fail() { ((FAILED++)); ((TOTAL++)); echo "  FAIL - $1"; }
section() { echo ""; echo "=== $1 ==="; }

json_get() {
  local key="$1"
  python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('$key',''))" 2>/dev/null
}

section "SANITY"
echo "1. Dependencias minimas (curl/python3)"
if command -v curl >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
  pass
else
  fail "curl/python3 nao encontrados"
fi

section "HEALTH"
echo "2. GET /health"
HEALTH=$(curl -s "$BASE/health")
echo "   $HEALTH"
echo "$HEALTH" | grep -q '"healthy"' && pass || fail "health nao retornou healthy"

section "AUTH SERVICE VIA COMPOSER"
EMAIL="composer-e2e-$(date +%s)@test.pt"
PASSWORD="Teste1234!"

echo "3. POST /api/auth/register"
REG_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"full_name\":\"Composer E2E\",\"role\":\"admin\"}")
[[ "$REG_CODE" =~ ^(200|201)$ ]] && pass || fail "register expected 200/201, got $REG_CODE"

echo "4. POST /api/auth/login"
LOGIN=$(curl -s -X POST "$BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
TOKEN=$(echo "$LOGIN" | json_get access_token)
REFRESH=$(echo "$LOGIN" | json_get refresh_token)
[ -n "$TOKEN" ] && pass || fail "login sem access_token"

echo "5. GET /api/auth/me"
ME_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/auth/me" \
  -H "Authorization: Bearer $TOKEN")
[ "$ME_CODE" = "200" ] && pass || fail "auth/me expected 200, got $ME_CODE"

echo "6. POST /api/auth/refresh"
REF_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/auth/refresh" \
  -H "Content-Type: application/json" \
  -d "{\"refresh_token\":\"$REFRESH\"}")
[ "$REF_CODE" = "200" ] && pass || fail "refresh expected 200, got $REF_CODE"

echo "7. POST /api/auth/logout"
LOGOUT_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/auth/logout" \
  -H "Authorization: Bearer $TOKEN")
[[ "$LOGOUT_CODE" =~ ^(200|204)$ ]] && pass || fail "logout expected 200/204, got $LOGOUT_CODE"

echo "8. Re-login para continuar testes"
LOGIN=$(curl -s -X POST "$BASE/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")
TOKEN=$(echo "$LOGIN" | json_get access_token)
[ -n "$TOKEN" ] && pass || fail "re-login sem token"

section "INVENTORY SERVICE VIA COMPOSER"
echo "9. POST /api/events"
EVENT=$(curl -s -X POST "$BASE/api/events" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name":"Composer E2E Event","venue":"Lisboa","date":"2026-12-01T18:00:00Z"}')
EVENT_ID=$(echo "$EVENT" | json_get id)
[ -n "$EVENT_ID" ] && pass || fail "evento nao criado"

echo "10. GET /api/events"
EVENTS_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/events")
[ "$EVENTS_CODE" = "200" ] && pass || fail "events list expected 200, got $EVENTS_CODE"

echo "11. GET /api/events/{id}"
SINGLE_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/events/$EVENT_ID")
[ "$SINGLE_CODE" = "200" ] && pass || fail "event detail expected 200, got $SINGLE_CODE"

echo "12. PUT /api/events/{id}"
UPD=$(curl -s -X PUT "$BASE/api/events/$EVENT_ID" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"status":"published"}')
UPD_STATUS=$(echo "$UPD" | json_get status)
[ "$UPD_STATUS" = "published" ] && pass || fail "status do evento nao ficou published"

echo "13. POST /api/events/{id}/tickets"
TCREATE=$(curl -s -X POST "$BASE/api/events/$EVENT_ID/tickets" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"category":"General Admission","price":25.00,"currency":"EUR","quantity":20}')
TCOUNT=$(echo "$TCREATE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total', len(d.get('data', []))))" 2>/dev/null)
[ "$TCOUNT" = "20" ] && pass || fail "ticket batch expected 20, got $TCOUNT"

echo "14. GET /api/events/{id}/tickets"
TLIST=$(curl -s "$BASE/api/events/$EVENT_ID/tickets?limit=2")
FIRST_TID=$(echo "$TLIST" | python3 -c "import sys,json; d=json.load(sys.stdin); print((d.get('data') or [{}])[0].get('id',''))" 2>/dev/null)
[ -n "$FIRST_TID" ] && pass || fail "nao foi possivel obter ticket_id"

echo "15. GET /api/tickets/{id}/availability"
AVAIL=$(curl -s "$BASE/api/tickets/$FIRST_TID/availability")
AVAIL_STATUS=$(echo "$AVAIL" | json_get status)
[ "$AVAIL_STATUS" = "available" ] && pass || fail "availability expected available, got '$AVAIL_STATUS'"

echo "16. POST /api/reservations"
RESERVE=$(curl -s -X POST "$BASE/api/reservations" \
  -H "Content-Type: application/json" \
  -d "{\"event_id\":\"$EVENT_ID\",\"quantity\":2}")
RES_COUNT=$(echo "$RESERVE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('reserved_count', len(d.get('tickets',[]))))" 2>/dev/null)
RES_TID=$(echo "$RESERVE" | python3 -c "import sys,json; d=json.load(sys.stdin); t=d.get('tickets',[]); print(t[0]['id'] if t else '')" 2>/dev/null)
[ "$RES_COUNT" = "2" ] && pass || fail "reservations expected 2, got $RES_COUNT"

echo "17. GET /api/reservations/{ticket_id}"
RES_GET=$(curl -s "$BASE/api/reservations/$RES_TID")
RES_STATUS=$(echo "$RES_GET" | json_get status)
[ "$RES_STATUS" = "reserved" ] && pass || fail "reservation status expected reserved, got '$RES_STATUS'"

section "PAYMENT SERVICE VIA COMPOSER"
echo "18. GET /api/payments"
PAY_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/payments")
[ "$PAY_CODE" = "200" ] && pass || fail "payments list expected 200, got $PAY_CODE"

section "SAGA CHECKOUT (AUTH+INVENTORY+PAYMENT)"
echo "19. POST /api/checkout"
CHECKOUT=$(curl -s -X POST "$BASE/api/checkout" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"event_id\":\"$EVENT_ID\",\"quantity\":1,\"success_url\":\"http://localhost:5173/?status=success\",\"cancel_url\":\"http://localhost:5173/?status=cancel\",\"amount_cents\":1500}")
CHECKOUT_URL=$(echo "$CHECKOUT" | json_get checkout_url)
SESSION_ID=$(echo "$CHECKOUT" | json_get session_id)

if [ -n "$CHECKOUT_URL" ] && [ -n "$SESSION_ID" ]; then
  pass
  echo "   checkout_url=$CHECKOUT_URL"
else
  fail "checkout sem checkout_url/session_id"
fi

echo "20. checkout_url deve ser publico (localhost:8002)"
echo "$CHECKOUT_URL" | grep -q '^http://localhost:8002/checkout/' && pass || fail "checkout_url nao foi reescrito para localhost:8002"

echo "21. Autorizar sessao no payment-service"
AUTH_RES=$(curl -s -X POST "http://localhost:8002/api/v1/checkout/sessions/$SESSION_ID/authorize" \
  -H "Content-Type: application/json" \
  -d "{\"password\":\"$PASSWORD\"}")
AUTH_STATUS=$(echo "$AUTH_RES" | json_get status)
if [ "$AUTH_STATUS" = "succeeded" ]; then
  pass
elif echo "$AUTH_RES" | grep -qi "digital wallet password configured"; then
  pass
  echo "   nota: ambiente sem wallet password configurada, teste segue com callback"
else
  fail "authorize expected succeeded (ou detalhe conhecido de wallet), got '$AUTH_STATUS' - response: $AUTH_RES"
fi

echo "22. Callback de sucesso do Composer"
CB_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/checkout/success?session_id=$SESSION_ID")
[[ "$CB_CODE" =~ ^(302|303|307|308)$ ]] && pass || fail "checkout/success expected redirect, got $CB_CODE"

echo "23. POST /api/checkout sem token deve falhar"
NO_AUTH=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/api/checkout" \
  -H "Content-Type: application/json" \
  -d '{"event_id":"fake","quantity":1,"success_url":"http://x","cancel_url":"http://y","amount_cents":100}')
[ "$NO_AUTH" = "401" ] && pass || fail "checkout sem token expected 401, got $NO_AUTH"

section "NEGATIVE E CLEANUP"
echo "24. GET /api/events/{uuid-inexistente}"
ERR_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/events/00000000-0000-0000-0000-000000000000")
[ "$ERR_CODE" = "404" ] && pass || fail "evento inexistente expected 404, got $ERR_CODE"

echo "25. GET /api/auth/me sem token"
NO_TOKEN=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/auth/me")
[[ "$NO_TOKEN" =~ ^(401|403|422)$ ]] && pass || fail "auth/me sem token expected 401/403/422, got $NO_TOKEN"

echo "26. DELETE /api/events/{id}"
DEL_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$BASE/api/events/$EVENT_ID" \
  -H "Authorization: Bearer $TOKEN")
[[ "$DEL_CODE" =~ ^(200|204)$ ]] && pass || fail "delete event expected 200/204, got $DEL_CODE"

echo ""
echo "==============================================="
if [ "$FAILED" -eq 0 ]; then
  echo "COMPOSER E2E OK - $PASSED/$TOTAL testes passaram"
else
  echo "COMPOSER E2E - $PASSED/$TOTAL passaram, $FAILED falharam"
fi
echo "==============================================="

[ "$FAILED" -eq 0 ] && exit 0 || exit 1