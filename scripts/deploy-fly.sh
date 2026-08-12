#!/usr/bin/env bash
# Deploys Veritech Scan to Fly.io using Fly's remote builder — the image is
# built on Fly's infrastructure, not locally, so this never requires Docker
# or Docker Desktop on the developer's machine. See docs/fly-deployment.md.
#
# Usage: FLY_APP_NAME=veritech-scan ./scripts/deploy-fly.sh [extra flyctl args]
set -euo pipefail

: "${FLY_APP_NAME:?Set FLY_APP_NAME (see docs/fly-deployment.md)}"

if ! command -v flyctl >/dev/null 2>&1 && ! command -v fly >/dev/null 2>&1; then
  echo "flyctl is required (https://fly.io/docs/flyctl/install/) — no Docker needed." >&2
  exit 1
fi
FLY_BIN="$(command -v flyctl || command -v fly)"

"$FLY_BIN" deploy --remote-only --app "$FLY_APP_NAME" "$@"

cat <<EOF

Deployed. This build ran on Fly's remote builder, not locally.
Run 'make fly-migrate' if this deploy included a schema change.
EOF
