#!/usr/bin/env bash
# Restores a Postgres backup created by backup-postgres.sh.
#
# WARNING: this OVERWRITES the current database contents. There is no
# undo other than restoring a different (older) backup.
#
# Expected downtime: the API and worker should be stopped (or will error on
# writes) for the duration of the restore — typically under a minute for an
# MVP-scale database. Verify afterwards by checking `make healthcheck` and
# spot-checking a known scan in the UI.
#
# Usage:
#   ./scripts/restore-postgres.sh /opt/veritech-scan/backups/veritech-scan-20260101-120000.sql.gz [--yes]
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_FILE="${1:-}"
ASSUME_YES=false
for arg in "$@"; do
  [ "$arg" = "--yes" ] && ASSUME_YES=true
done

if [ -z "$BACKUP_FILE" ]; then
  echo "Usage: $0 <path-to-backup.sql.gz> [--yes]" >&2
  exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
  echo "ERROR: backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

if [ -f .env.production ]; then
  set -a
  # shellcheck disable=SC1091
  source .env.production
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:?POSTGRES_USER must be set (via .env.production or the environment)}"
POSTGRES_DB="${POSTGRES_DB:?POSTGRES_DB must be set (via .env.production or the environment)}"

COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.production)

echo "!! This will REPLACE all data in database '${POSTGRES_DB}' with the contents of:"
echo "     $BACKUP_FILE"
echo "!! Any scans, findings, or evidence created after this backup will be permanently lost."
echo ""

if [ "$ASSUME_YES" != true ]; then
  read -r -p "Type the database name ('${POSTGRES_DB}') to confirm: " confirm_db
  if [ "$confirm_db" != "$POSTGRES_DB" ]; then
    echo "Confirmation did not match. Aborting." >&2
    exit 1
  fi
fi

echo "Stopping api and worker (they must not write during restore) ..."
"${COMPOSE[@]}" stop api worker

echo "Restoring from $BACKUP_FILE ..."
if ! gunzip -c "$BACKUP_FILE" | "${COMPOSE[@]}" exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" --set ON_ERROR_STOP=on; then
  echo "ERROR: restore failed partway through. The database may be in an inconsistent state." >&2
  echo "Restore a known-good backup again, or investigate manually before restarting api/worker." >&2
  exit 1
fi

echo "Restarting api and worker ..."
"${COMPOSE[@]}" up -d api worker

echo ""
echo "Restore complete. Verify with:"
echo "  ./scripts/healthcheck.sh prod"
echo "  and by opening the app and checking a known scan."
