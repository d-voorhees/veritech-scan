#!/usr/bin/env bash
# Native production deployment: pull -> venv/deps -> build -> migrate ->
# restart systemd services -> verify. No Docker involved anywhere.
#
# Run as the deploy user, from within the cloned repo on the Oracle VM
# (normally /opt/veritech-scan/app).
#
# Usage:
#   ./scripts/deploy.sh [branch]     # defaults to "main"
#   ./scripts/deploy.sh --no-pull    # deploy the current checkout as-is
#
# Rollback: if deployment fails, or a bad release needs to be reverted,
# check out the prior known-good commit/tag and re-run:
#   git checkout <prior-commit-or-tag>
#   ./scripts/deploy.sh --no-pull
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

cd "$(dirname "$0")/.."
REPO_ROOT="$(pwd)"

BRANCH="main"
NO_PULL=false
for arg in "$@"; do
  case "$arg" in
    --no-pull) NO_PULL=true ;;
    *) BRANCH="$arg" ;;
  esac
done

VENV="${VENV:-/opt/veritech-scan/venv}"
PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/opt/veritech-scan/ms-playwright}"

if [ ! -f .env.production ]; then
  echo "ERROR: .env.production not found at $REPO_ROOT/.env.production." >&2
  echo "Copy .env.example, fill in production secrets, and save it there." >&2
  exit 1
fi

echo "== 1. Fetching latest code =="
if [ "$NO_PULL" = false ]; then
  git fetch origin
  git checkout "$BRANCH"
  git pull origin "$BRANCH"
else
  echo "Skipping git pull (--no-pull); deploying current checkout at $(git rev-parse --short HEAD)."
fi

echo "== 2. Creating/updating the Python virtual environment =="
if [ ! -x "$VENV/bin/python" ]; then
  python3.12 -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r apps/api/requirements.txt

echo "== 3. Verifying Chromium still launches with this dependency set =="
PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" PYTHONPATH="$REPO_ROOT/apps/api" \
  "$VENV/bin/python" -m app.worker_check --startup-only

echo "== 4. Installing Node dependencies =="
(cd apps/web && npm ci)

echo "== 5. Building Next.js =="
(cd apps/web && npm run build)

echo "== 6. Running database migrations =="
load_env_file .env.production
(cd apps/api && "$VENV/bin/alembic" upgrade head)

echo "== 7. Syncing systemd units and Caddy config =="
sudo cp "$REPO_ROOT/deploy/systemd/veritech-scan-api.service" /etc/systemd/system/veritech-scan-api.service
sudo cp "$REPO_ROOT/deploy/systemd/veritech-scan-worker.service" /etc/systemd/system/veritech-scan-worker.service
sudo cp "$REPO_ROOT/deploy/systemd/veritech-scan-web.service" /etc/systemd/system/veritech-scan-web.service
sudo cp "$REPO_ROOT/deploy/caddy/Caddyfile" /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl daemon-reload

echo "== 8. Restarting services =="
sudo systemctl restart veritech-scan-api.service
sudo systemctl restart veritech-scan-worker.service
sudo systemctl restart veritech-scan-web.service
sudo systemctl reload caddy

echo "== 9. Waiting for services to come up =="
sleep 3
attempts=0
max_attempts=20
until curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 || [ "$attempts" -ge "$max_attempts" ]; do
  attempts=$((attempts + 1))
  sleep 3
done

echo "== 10. Verifying health =="
if ! ./scripts/healthcheck.sh prod; then
  echo ""
  echo "!! Deployment health check failed. Recent logs: !!"
  journalctl -u veritech-scan-api -u veritech-scan-worker -u veritech-scan-web --since "5 minutes ago" --no-pager | tail -150
  echo ""
  echo "Deployment did not verify cleanly. Consider rolling back:"
  echo "  git checkout <prior-commit-or-tag> && ./scripts/deploy.sh --no-pull"
  exit 1
fi

echo ""
echo "== Deployment complete: $(git rev-parse --short HEAD) on branch $BRANCH =="
