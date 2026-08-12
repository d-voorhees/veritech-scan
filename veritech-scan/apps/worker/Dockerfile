# syntax=docker/dockerfile:1
#
# ARM64-compatible worker image.
#
# The official mcr.microsoft.com/playwright/python image historically favors
# x86_64. To guarantee Oracle Cloud Always Free ARM64 (Ampere A1) compatibility
# we build our own image from python:3.12-slim (multi-arch) and install
# Chromium + its system dependencies via `playwright install --with-deps`.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    wget \
    gnupg \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

WORKDIR /app

COPY apps/api/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Installs Chromium and the Debian system libraries it needs (fonts, GTK,
# NSS, etc). `--with-deps` resolves the correct package set per-arch, which is
# why we do not hand-maintain the apt-get list for Chromium itself.
RUN mkdir -p /ms-playwright && playwright install --with-deps chromium

COPY apps/api/app ./app
COPY apps/api/alembic ./alembic
COPY apps/api/alembic.ini ./alembic.ini

RUN mkdir -p /data/artifacts && \
    chown -R appuser:appuser /app /data/artifacts /ms-playwright

USER appuser

# Fails the build/startup fast if Chromium cannot launch in this environment,
# rather than discovering it only when the first scan runs in production.
RUN python -m app.worker_check --startup-only

CMD ["dramatiq", "app.tasks.scan_tasks", "--processes", "1", "--threads", "1"]
