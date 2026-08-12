#!/usr/bin/env bash
# Verifies Caddy, web, API, Postgres, Redis, and worker health.
#
# Usage:
#   ./scripts/healthcheck.sh            # local dev stack (docker-compose.yml)
#   ./scripts/healthcheck.sh prod        # production stack (docker-compose.prod.yml)
set -euo pipefail

MODE="${1:-dev}"
cd "$(dirname "$0")/.."

if [ "$MODE" = "prod" ]; then
  COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.production)
else
  COMPOSE=(docker compose)
fi

pass=0
fail=0

check() {
  local name="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "  [OK]   $name"
    pass=$((pass + 1))
  else
    echo "  [FAIL] $name"
    fail=$((fail + 1))
  fi
}

echo "== Container status =="
"${COMPOSE[@]}" ps

echo ""
echo "== Service health =="

check "postgres accepting connections" \
  "${COMPOSE[@]}" exec -T postgres pg_isready -U "${POSTGRES_USER:-veritech_scan}"

check "redis responding to PING" \
  "${COMPOSE[@]}" exec -T redis redis-cli ping

check "api /health" bash -c '
  "$@" exec -T api python -c "
import urllib.request
import sys
sys.exit(0 if urllib.request.urlopen(\"http://localhost:8000/health\", timeout=5).status == 200 else 1)
"
' _ "${COMPOSE[@]}"

check "worker process running" \
  "${COMPOSE[@]}" exec -T worker python -c "import app.tasks.scan_tasks"

if [ "$MODE" = "prod" ]; then
  check "caddy admin API" \
    "${COMPOSE[@]}" exec -T caddy wget -qO- http://localhost:2019/config/
  check "web /healthz via caddy" \
    curl -fsS "https://${APP_DOMAIN}/health"
else
  check "web /healthz" \
    "${COMPOSE[@]}" exec -T web wget -qO- http://localhost:3000/healthz
fi

echo ""
echo "== Summary: $pass passed, $fail failed =="
[ "$fail" -eq 0 ]
