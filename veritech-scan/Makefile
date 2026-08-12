SHELL := /bin/bash
COMPOSE := docker compose
COMPOSE_PROD := docker compose -f docker-compose.prod.yml --env-file .env.production

.PHONY: dev dev-down test lint build migrate seed logs prod-up prod-down deploy \
        healthcheck worker-check backup-db restore-db

## Local development -----------------------------------------------------------

dev:
	$(COMPOSE) up --build

dev-down:
	$(COMPOSE) down

build:
	$(COMPOSE) build
	$(COMPOSE_PROD) build

logs:
	$(COMPOSE) logs -f --tail=200

## Quality ------------------------------------------------------------------------

test:
	$(COMPOSE) run --rm api pytest -q
	$(COMPOSE) run --rm web npm run test --if-present

lint:
	$(COMPOSE) run --rm api ruff check app
	$(COMPOSE) run --rm api mypy app --ignore-missing-imports || true
	$(COMPOSE) run --rm web npm run lint

## Database -------------------------------------------------------------------------

migrate:
	$(COMPOSE) run --rm api alembic upgrade head

seed:
	$(COMPOSE) run --rm api python -m app.seed

## Production (Oracle VM) ------------------------------------------------------------

prod-up:
	$(COMPOSE_PROD) up -d --build

prod-down:
	$(COMPOSE_PROD) down

deploy:
	./scripts/deploy.sh

healthcheck:
	./scripts/healthcheck.sh

worker-check:
	$(COMPOSE) run --rm worker python -m app.worker_check

backup-db:
	./scripts/backup-postgres.sh

restore-db:
	./scripts/restore-postgres.sh $(FILE) $(ARGS)
