#!/usr/bin/env bash
# Safe production deployment: pull -> build -> migrate -> start -> verify.
# Run from the deploy user on the Oracle VM, inside the cloned repo.
#
# Usage:
#   ./scripts/deploy.sh [branch]     # defaults to "main"
#
# Rollback: if deployment fails, or a bad release needs to be reverted,
# check out the prior known-good commit/tag and re-run this script:
#   git checkout <prior-commit-or-tag>
#   ./scripts/deploy.sh --no-pull
set -euo pipefail

cd "$(dirname "$0")/.."

BRANCH="main"
NO_PULL=false
for arg in "$@"; do
  case "$arg" in
    --no-pull) NO_PULL=true ;;
    *) BRANCH="$arg" ;;
  esac
done

COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.production)

if [ ! -f .env.production ]; then
  echo "ERROR: .env.production not found. Copy .env.example, fill in production secrets, and save it as .env.production." >&2
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

echo "== 2. Building images =="
"${COMPOSE[@]}" build

echo "== 3. Running database migrations =="
"${COMPOSE[@]}" run --rm api alembic upgrade head

echo "== 4. Starting / updating services =="
"${COMPOSE[@]}" up -d

echo "== 5. Waiting for services to report healthy =="
attempts=0
max_attempts=20
until "${COMPOSE[@]}" ps --format json | grep -q '"Health":"healthy"' || [ "$attempts" -ge "$max_attempts" ]; do
  attempts=$((attempts + 1))
  sleep 5
done

echo "== 6. Verifying health =="
if ! ./scripts/healthcheck.sh prod; then
  echo ""
  echo "!! Deployment health check failed. Recent logs: !!"
  "${COMPOSE[@]}" logs --tail=100 api worker web caddy
  echo ""
  echo "Deployment did not verify cleanly. Consider rolling back:"
  echo "  git checkout <prior-commit-or-tag> && ./scripts/deploy.sh --no-pull"
  exit 1
fi

echo ""
echo "== Deployment complete: $(git rev-parse --short HEAD) on branch $BRANCH =="
