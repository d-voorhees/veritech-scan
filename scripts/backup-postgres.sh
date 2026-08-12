#!/usr/bin/env bash
# Creates a compressed, timestamped Postgres backup via `pg_dump` run inside
# the postgres container, and prunes old backups beyond the retention count.
#
# Usage:
#   ./scripts/backup-postgres.sh [--retain N] [--backup-dir DIR]
set -euo pipefail

cd "$(dirname "$0")/.."

RETAIN=14
BACKUP_DIR="/opt/veritech-scan/backups"

while [ $# -gt 0 ]; do
  case "$1" in
    --retain) RETAIN="$2"; shift 2 ;;
    --backup-dir) BACKUP_DIR="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [ -f .env.production ]; then
  set -a
  # shellcheck disable=SC1091
  source .env.production
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:?POSTGRES_USER must be set (via .env.production or the environment)}"
POSTGRES_DB="${POSTGRES_DB:?POSTGRES_DB must be set (via .env.production or the environment)}"

COMPOSE=(docker compose -f docker-compose.prod.yml --env-file .env.production)

mkdir -p "$BACKUP_DIR"
timestamp="$(date +%Y%m%d-%H%M%S)"
target_file="${BACKUP_DIR}/veritech-scan-${timestamp}.sql.gz"
tmp_file="${target_file}.partial"

echo "Backing up database '${POSTGRES_DB}' to ${target_file} ..."

# Credentials are never echoed: pg_dump runs inside the container using the
# Postgres image's own trust/env auth, not a password on this command line.
if ! "${COMPOSE[@]}" exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-password \
    | gzip -9 > "$tmp_file"; then
  echo "ERROR: pg_dump failed. No backup was written." >&2
  rm -f "$tmp_file"
  exit 1
fi

if [ ! -s "$tmp_file" ]; then
  echo "ERROR: backup file is empty. Refusing to keep it." >&2
  rm -f "$tmp_file"
  exit 1
fi

mv "$tmp_file" "$target_file"
echo "Backup written: $target_file ($(du -h "$target_file" | cut -f1))"

echo "Pruning backups beyond the ${RETAIN} most recent ..."
# shellcheck disable=SC2012
ls -1t "${BACKUP_DIR}"/veritech-scan-*.sql.gz 2>/dev/null | tail -n "+$((RETAIN + 1))" | while read -r old_file; do
  echo "  removing $old_file"
  rm -f "$old_file"
done

echo "Done. $(ls "${BACKUP_DIR}"/veritech-scan-*.sql.gz 2>/dev/null | wc -l | tr -d ' ') backup(s) retained."
