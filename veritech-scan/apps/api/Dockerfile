# syntax=docker/dockerfile:1

# ---- base ---------------------------------------------------------------
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser
WORKDIR /app

# ---- deps -----------------------------------------------------------------
FROM base AS deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-dev.txt ./
RUN pip install --user -r requirements-dev.txt

# ---- dev --------------------------------------------------------------------
# Used by docker-compose.yml for local development with live-reload.
FROM deps AS dev
ENV PATH=/root/.local/bin:$PATH
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---- production -----------------------------------------------------------------
FROM base AS production
COPY requirements.txt ./
RUN pip install --user -r requirements.txt && \
    mkdir -p /home/appuser/.local && \
    cp -r /root/.local/* /home/appuser/.local/ && \
    chown -R appuser:appuser /home/appuser/.local
COPY --chown=appuser:appuser . .
RUN mkdir -p /data/artifacts && chown -R appuser:appuser /data/artifacts /app
USER appuser
ENV PATH=/home/appuser/.local/bin:$PATH
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health',timeout=3).status==200 else 1)"
CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "--workers", "2", "--bind", "0.0.0.0:8000", "--access-logfile", "-", "--error-logfile", "-"]
