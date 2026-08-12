SHELL := /bin/bash

# Path to the Python virtualenv used for API/worker commands. Defaults to a
# local dev venv (see README.md's "Local setup"); override on the Oracle VM
# with VENV=/opt/veritech-scan/venv, e.g.:
#   make migrate VENV=/opt/veritech-scan/venv
VENV ?= apps/api/.venv
PYTHON := $(abspath $(VENV))/bin/python
ALEMBIC := $(abspath $(VENV))/bin/alembic

# Health check mode: "dev" (plain local processes) or "prod" (systemd + Caddy).
MODE ?= dev

.PHONY: dev install-server deploy migrate seed test lint healthcheck backup-db restore-db

## Local development (native, no Docker) -----------------------------------------

dev:
	@echo "Starting api (uvicorn --reload :8000), worker (dramatiq), web (next dev :3000)."
	@echo "Requires Postgres and Redis already running locally — see README.md."
	@trap 'kill 0' EXIT INT TERM; \
	(cd apps/api && PYTHONPATH=. $(PYTHON) -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload) & \
	(cd apps/api && PYTHONPATH=. $(PYTHON) -m dramatiq app.tasks.scan_tasks --processes 1 --threads 1) & \
	(cd apps/web && npm run dev) & \
	wait

## Quality ------------------------------------------------------------------------

test:
	$(PYTHON) -m pytest -q
	cd apps/web && npm run test --if-present

lint:
	cd apps/api && $(PYTHON) -m ruff check app
	cd apps/api && $(PYTHON) -m mypy app --ignore-missing-imports || true
	cd apps/web && npm run lint

## Database -------------------------------------------------------------------------

migrate:
	cd apps/api && $(ALEMBIC) upgrade head

seed:
	cd apps/api && PYTHONPATH=. $(PYTHON) -m app.seed $(ARGS)

## Production (Oracle VM, native systemd) ------------------------------------------

install-server:
	sudo ./scripts/install-server.sh $(ARGS)

deploy:
	./scripts/deploy.sh $(ARGS)

healthcheck:
	./scripts/healthcheck.sh $(MODE)

backup-db:
	./scripts/backup-postgres.sh $(ARGS)

restore-db:
	./scripts/restore-postgres.sh $(FILE) $(ARGS)
