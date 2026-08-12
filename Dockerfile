# Veritech Scan — single production image for Fly.io.
#
# One image, two runtime roles (see scripts/entrypoint.sh): the web/API
# process (Next.js + FastAPI, autostop/autostart on Fly) and the scan-runner
# process (one-off Fly Machine per scan, created via the Fly Machines API —
# see apps/api/app/services/fly_machines.py). Built via `fly deploy
# --remote-only` (scripts/deploy-fly.sh) — no local Docker required.
#
# All base images have official linux/amd64 and linux/arm64 variants, and
# `playwright install --with-deps chromium` supports arm64.

# ---------------------------------------------------------------------------
# Stage 1: build the Next.js frontend (standalone output)
# ---------------------------------------------------------------------------
FROM node:22-bookworm-slim AS web-builder
WORKDIR /build/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
# next.config.mjs's rewrites() (which proxies /api/* and /health to the API
# process) is resolved ONCE at build time and frozen into
# .next/routes-manifest.json — Next.js does not re-read next.config.mjs at
# server start. This must be set here, at build time, matching the value
# scripts/entrypoint.sh sets at runtime (both processes always share one
# Machine, so this is a fixed value, not a real per-deploy secret).
ENV API_INTERNAL_URL=http://127.0.0.1:8000
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: runtime — Python + Playwright/Chromium + Node.js runtime (for the
# standalone Next.js server), all installed in this one final image.
#
# Deliberately NOT split into a separate "python-deps" stage copied in via
# COPY --from: `playwright install --with-deps` apt-installs Chromium's
# shared-library dependencies (libnss3, libatk-bridge2.0-0, libgtk-3-0,
# libasound2, ...) system-wide (/usr/lib, /lib), not just under
# /usr/local — a COPY --from would silently miss those and Chromium would
# fail to launch at runtime. Installing everything directly in the image
# that actually runs it avoids that whole class of bug.
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# Node.js runtime (only the binary is needed — the standalone Next.js build
# already bundles its own pruned node_modules, so no npm install here).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY apps/api/requirements.txt ./apps/api/requirements.txt
RUN pip install --no-cache-dir -r apps/api/requirements.txt

# Installs Chromium itself plus every OS-level shared library it needs, in
# this same filesystem — see the stage comment above for why this can't be
# copied in from elsewhere.
RUN python -m playwright install --with-deps chromium

COPY apps/api ./apps/api

# Next.js standalone output: server.js + a pruned node_modules, then static
# assets and public/ layered back on top (standalone output excludes them
# by design — see Next.js docs on `output: "standalone"`).
COPY --from=web-builder /build/web/.next/standalone ./apps/web
COPY --from=web-builder /build/web/.next/static ./apps/web/.next/static
COPY --from=web-builder /build/web/public ./apps/web/public

COPY scripts/entrypoint.sh ./scripts/entrypoint.sh
RUN chmod +x ./scripts/entrypoint.sh

ENV PYTHONPATH=/app/apps/api
ENV APP_ENV=production
ENV PORT=8080

# Fail the build loudly if Chromium can't launch on this image, rather than
# discovering it at first scan.
RUN cd apps/api && python -m app.worker_check --startup-only

EXPOSE 8080

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["web"]
