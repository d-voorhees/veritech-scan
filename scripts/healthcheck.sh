#!/usr/bin/env bash
# Verifies Caddy, API, web app, worker, Postgres, Redis, and Chromium
# health for the native (non-Docker) deployment.
#
# Usage:
#   ./scripts/healthcheck.sh            # local dev (processes run directly, no systemd)
#   ./scripts/healthcheck.sh prod        # production (systemd units + Caddy)
set -euo pipefail

# Exports KEY=VALUE lines from a .env-style file without shell-interpreting
# values (plain `source` breaks on unquoted values containing spaces, e.g.
# PRODUCT_NAME=Veritech Scan).
load_env_file() {
  local file="$1"
  [ -f "$file" ] || return 0
  while IFS='=' read -r key value; do
    case "$key" in ''|'#'*) continue ;; esac
    export "$key=$value"
  done < "$file"
}

MODE="${1:-dev}"
cd "$(dirname "$0")/.."

ENV_FILE=".env"
[ "$MODE" = "prod" ] && ENV_FILE=".env.production"
load_env_file "$ENV_FILE"

POSTGRES_USER="${POSTGRES_USER:-veritech_scan}"
POSTGRES_DB="${POSTGRES_DB:-veritech_scan}"
APP_DOMAIN="${APP_DOMAIN:-localhost}"
VENV="${VENV:-/opt/veritech-scan/venv}"
[ "$MODE" != "prod" ] && VENV="${VENV_DEV:-apps/api/.venv}"

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

echo "== Native service health ($MODE) =="
echo ""

if [ "$MODE" = "prod" ]; then
  check "systemd: veritech-scan-api active" systemctl is-active --quiet veritech-scan-api
  check "systemd: veritech-scan-worker active" systemctl is-active --quiet veritech-scan-worker
  check "systemd: veritech-scan-web active" systemctl is-active --quiet veritech-scan-web
  check "systemd: caddy active" systemctl is-active --quiet caddy
fi

check "postgres accepting connections" \
  pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"

check "redis responding to PING" \
  bash -c "redis-cli -h 127.0.0.1 ping | grep -q PONG"

check "api /health" \
  curl -fsS http://127.0.0.1:8000/health

check "web responding" \
  curl -fsS http://127.0.0.1:3000

if [ -x "$VENV/bin/python" ]; then
  check "worker: queue/actor registration + Chromium launch" \
    bash -c "cd apps/api && PYTHONPATH=. '$VENV/bin/python' -m app.worker_check"
else
  echo "  [SKIP] worker check ($VENV/bin/python not found — pass VENV=/path/to/venv)"
fi

if [ "$MODE" = "prod" ]; then
  check "caddy: https://$APP_DOMAIN/health via TLS" \
    curl -fsS "https://${APP_DOMAIN}/health"
fi

echo ""
echo "== Summary: $pass passed, $fail failed =="
[ "$fail" -eq 0 ]
