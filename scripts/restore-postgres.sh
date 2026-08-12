#!/usr/bin/env bash
# Restores a Postgres backup created by backup-postgres.sh, against the
# native localhost Postgres server. No Docker involved.
#
# WARNING: this OVERWRITES the current database contents. There is no
# undo other than restoring a different (older) backup.
#
# Expected downtime: the API and worker services are stopped for the
# duration of the restore — typically under a minute for an MVP-scale
# database. Verify afterwards with `make healthcheck` and by spot-checking
# a known scan in the UI.
#
# Usage:
#   ./scripts/restore-postgres.sh /opt/veritech-scan/backups/veritech-scan-20260101-120000.sql.gz [--yes]
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

load_env_file .env.production

POSTGRES_USER="${POSTGRES_USER:?POSTGRES_USER must be set (via .env.production or the environment)}"
POSTGRES_DB="${POSTGRES_DB:?POSTGRES_DB must be set (via .env.production or the environment)}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set (via .env.production or the environment)}"

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
sudo systemctl stop veritech-scan-api.service
sudo systemctl stop veritech-scan-worker.service

echo "Restoring from $BACKUP_FILE ..."
if ! gunzip -c "$BACKUP_FILE" | PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" --set ON_ERROR_STOP=on; then
  echo "ERROR: restore failed partway through. The database may be in an inconsistent state." >&2
  echo "Restore a known-good backup again, or investigate manually before restarting api/worker." >&2
  exit 1
fi

echo "Restarting api and worker ..."
sudo systemctl start veritech-scan-api.service
sudo systemctl start veritech-scan-worker.service

echo ""
echo "Restore complete. Verify with:"
echo "  ./scripts/healthcheck.sh prod"
echo "  and by opening the app and checking a known scan."
