# Veritech Scan

**Evidence-first technical pre-screening for web-business acquisitions.**

Veritech Scan is a product of [Veritech Diligence](https://veritechdiligence.com).
Veritech Diligence provides technical due diligence for buyers of web-based
businesses. Veritech Scan is a bounded, rate-limited, public-web technical
evidence system: a user enters a public web domain, confirms they are
authorized to assess it, and receives a structured, evidence-linked
**Technical Acquisition Brief** — a prioritized risk register with every
finding traceable back to the exact evidence that produced it.

It answers one practical question for a prospective buyer:

> Is this web property worth deeper technical diligence, and what should I
> investigate next?

## MVP scope

- Invite-only, authenticated app (no public signup).
- Submit a domain/URL + business notes + crawl depth (10/25/50 pages) +
  a required authorization acknowledgment.
- Asynchronous scan pipeline (Dramatiq + Redis) covering: HTTP/redirect
  checks, robots.txt + sitemap discovery, a bounded same-origin crawl,
  DNS/SPF/DMARC posture, Playwright homepage rendering + third-party
  dependency inventory, local rules-based technology detection, and a
  performance adapter (local metrics always; Google PageSpeed Insights
  optionally, when configured).
- A deterministic, versioned rules engine (12 rules) that turns collected
  evidence into severity- and confidence-scored findings — never an LLM.
- A full report UI: status, task panel, risk register, expandable evidence,
  DNS/HTTP/crawl/technology/performance sections, known limitations, and a
  clean HTML export meant for "Print → Save as PDF."
- Runs entirely on one native Ubuntu VM (Postgres, Redis, Dramatiq worker,
  FastAPI, Next.js, Caddy, all as systemd services) — no Docker, no
  containers, no managed cloud services required.

## Explicit non-goals

Veritech Scan is **not**:

- A vulnerability scanner or penetration-testing tool.
- An access-control bypass, credential-testing, or exploitation system.
- A scraping proxy for arbitrary/bulk use.
- A source of confirmed vulnerabilities — findings distinguish
  *observation* from *interpretation* and a *hardening opportunity* from a
  *confirmed vulnerability*, and the product never claims the latter.

See `docs/threat-model.md` for the full list of technical non-goals (full
`robots.txt` enforcement, DKIM discovery, high availability, etc).

## Repository layout

```
apps/web/       Next.js App Router frontend (TypeScript, Tailwind)
apps/api/       FastAPI + SQLAlchemy + Alembic + the collectors/rules engine
apps/worker/    Dramatiq worker (same codebase as apps/api, run via app.tasks.scan_tasks)
packages/shared/  Cross-cutting TypeScript constants/types
docs/           Architecture, rules engine, threat model, deployment, ops
scripts/        Native server install, deploy, backup/restore, healthcheck scripts
deploy/systemd/ systemd unit files for the api/worker/web services
deploy/caddy/   Native Caddy reverse-proxy config
tests/backend/  pytest suite (89 tests at last count)
```

## Local setup

Prerequisites: **PostgreSQL 16+ and Redis 7+ running locally**, Python 3.12
(3.11 also works), and Node.js 22. No Docker is used anywhere in this
project, in development or production.

Install Postgres/Redis with your platform's package manager (e.g.
`brew install postgresql@16 redis` on macOS, `sudo apt install postgresql
redis-server` on Ubuntu), then create the database and role:

```bash
createdb veritech_scan
createuser veritech_scan --pwprompt   # set password to match .env
```

```bash
cp .env.example .env
# edit .env — DATABASE_URL/REDIS_URL default to 127.0.0.1; set POSTGRES_PASSWORD
# to match the role you just created.

cd apps/api && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt && playwright install chromium
cd ../web && npm install
cd ../..

make migrate       # alembic upgrade head
make seed          # creates the dev admin user + a synthetic demo scan
make dev           # starts uvicorn --reload, the dramatiq worker, and next dev together
```

Open http://localhost:3000 and sign in with `INITIAL_ADMIN_EMAIL` /
`INITIAL_ADMIN_PASSWORD` from your `.env` (defaults:
`admin@example.com` / `change-me` — **change these** even for local dev if
your machine is at all shared).

`make dev` runs all three processes in the foreground (Ctrl+C stops all of
them). To run them separately instead (e.g. in different terminals):

```bash
cd apps/api && PYTHONPATH=. .venv/bin/uvicorn app.main:app --reload --port 8000
cd apps/api && PYTHONPATH=. .venv/bin/dramatiq app.tasks.scan_tasks --processes 1 --threads 1
cd apps/web && npm run dev
```

## Environment configuration

All configuration is via environment variables — see
[`.env.example`](./.env.example) for the full list with defaults, including
product identity (`PRODUCT_NAME`, `PARENT_BRAND`, `APP_DOMAIN`, ...), scan
safety limits (`SCAN_MAX_PAGES`, `SCAN_DEFAULT_REQUEST_DELAY_SECONDS`,
`SCAN_MAX_TOTAL_MINUTES`, `SCAN_CREATE_RATE_LIMIT_PER_HOUR`), and optional
providers (`GOOGLE_PAGESPEED_API_KEY`, `SENTRY_DSN`). Never commit `.env` or
`.env.production` — both are gitignored.

## Migrations

```bash
make migrate                 # alembic upgrade head, using apps/api/.venv
```

Migrations are **never** run automatically at service startup (see
`deploy/systemd/veritech-scan-api.service` — there's no migration step in
its `ExecStart`) — this is a deliberate choice so a deploy never silently
applies schema changes without an operator seeing it happen. Always run
`make migrate` (or `./scripts/deploy.sh`, which runs it explicitly) after
pulling new code.

To generate a new migration after changing SQLAlchemy models:

```bash
cd apps/api && .venv/bin/alembic revision --autogenerate -m "describe the change"
```

Review the generated file before committing — autogenerate is a starting
point, not a guarantee.

## Seed data

```bash
make seed                    # admin user + fictional org + fully synthetic demo scan
make seed ARGS=--admin-only  # (or: cd apps/api && .venv/bin/python -m app.seed --admin-only)
```

The synthetic demo scan is clearly labeled everywhere it appears (`is_demo`
flag on the organization and scan, `[SYNTHETIC DEMO DATA]` in its notes, a
visible "Synthetic demo data" badge in the UI, and the same disclosure in
the HTML export) — it exists to let you see a fully populated report
without running a real scan.

## Testing

```bash
make test           # backend pytest suite + frontend tests (if present)
make lint            # ruff + mypy (backend), eslint (frontend)
```

The backend suite (`tests/backend/`, 89 tests) covers URL normalization,
SSRF/private-IP/redirect-revalidation protections, crawl URL filtering and
max-page limits, SPF/DMARC parsing, all 12 rules (firing and non-firing
cases), finding-to-evidence linkage, the scan creation/retrieval API and
ownership authorization, partial-completion behavior after a simulated task
failure, a real Chromium launch + render check, and one fully mocked
end-to-end happy-path scan (`test_e2e_scan.py`) that exercises the real
collector → evidence → rules-engine pipeline with no real network or DNS
calls (`respx` for HTTP, a fake DNS resolver, real Playwright with route
interception for the browser step).

`make test` runs `apps/api/.venv/bin/python -m pytest` from the repo root
(picking up `pytest.ini`'s `testpaths = tests/backend`) against whatever
`DATABASE_URL`/`REDIS_URL` are set in your environment/`.env`, then
`npm run test --if-present` in `apps/web`. To point it at a dedicated test
database instead of your dev one:

```bash
createdb veritech_scan_test
PYTHONPATH=apps/api DATABASE_URL=postgresql+psycopg://$(whoami)@localhost:5432/veritech_scan_test \
  apps/api/.venv/bin/python -m pytest tests/backend -q
```

## Running an authorized scan

1. Sign in.
2. **New scan** → enter a domain/URL you own or are authorized to analyze,
   optional notes, a crawl depth (10/25/50 pages), and check the
   authorization acknowledgment (required — the form won't submit without
   it, and the API rejects the request server-side too).
3. You're redirected to the scan's status page, which polls automatically
   while the scan is `queued`/`running` and shows each collection task's
   status live.
4. Once `completed` or `completed_with_warnings`, review the risk register,
   click into any finding to see its exact linked evidence, and use
   **Export HTML report** for a print-ready Technical Acquisition Brief.

## Safety boundaries

Summarized here; full detail in `docs/threat-model.md`:

- Only `http`/`https`, only public IPs (loopback/private/link-local/
  multicast/reserved/cloud-metadata all rejected, before *and* after every
  redirect).
- Same-origin crawl only, excluding login/admin/cart/checkout/API paths,
  static assets, and non-http(s) schemes.
- Hard page-count cap (10/25/50), 1.5s/request delay, 15s/page timeout,
  10-minute total scan timeout.
- Never submits forms, authenticates, solves CAPTCHAs, or bypasses access
  controls.
- Ephemeral browser context per scan — no cookie/session persistence.
- Scan creation is rate-limited per user; the app is invite-only.

## Known limitations

- `robots.txt` is recorded as evidence but not enforced against the
  crawler (documented in the report itself, not just here).
- DKIM discovery is out of scope for the MVP (SPF + DMARC only).
- Browser rendering covers the homepage only, not every crawled page.
- Google PageSpeed Insights metrics only appear when
  `GOOGLE_PAGESPEED_API_KEY` is configured; otherwise the report says so
  explicitly rather than silently omitting the section.
- Single-VM, single-worker deployment: no high availability, no automatic
  scan requeue if the worker restarts mid-scan (see `docs/operations.md`).
- Off-server backups are not configured by default — see
  `docs/backup-and-recovery.md` before storing real client data.

## Production deployment summary

Full step-by-step in `docs/oracle-native-deployment.md`. Short version:

```bash
# on a fresh Ubuntu 24.04 ARM64 Oracle Cloud VM:
sudo ./scripts/install-server.sh            # Caddy, Postgres, Redis, Python, Node, deploy user, UFW
# clone the repo into /opt/veritech-scan/app, then:
cp .env.example .env.production             # fill in production secrets
make deploy                                 # venv/deps, npm build, migrate, restart systemd services
make seed ARGS=--admin-only VENV=/opt/veritech-scan/venv
# point app.veritechdiligence.com's A record at the VM's public IP
make healthcheck MODE=prod
```

Every service — Caddy, PostgreSQL, Redis, the API, the worker, and Next.js
— runs as a native systemd unit. Only Caddy publishes ports (80/443);
Postgres and Redis are bound to `127.0.0.1` and the worker exposes no port
at all — none are ever exposed to the public internet. Subsequent deploys
use `./scripts/deploy.sh` (`make deploy`), which pulls, installs
dependencies, builds, migrates, restarts services, and verifies health in
one step, printing logs and instructions to roll back if anything fails.

## Documentation index

- [`docs/architecture.md`](docs/architecture.md) — system diagram, why a
  background worker is required, collection/evidence/rules/report flow.
- [`docs/rules-engine.md`](docs/rules-engine.md) — rule architecture,
  versioning, the full rule catalog, how to add a rule safely.
- [`docs/threat-model.md`](docs/threat-model.md) — SSRF prevention, crawl
  boundaries, authorization, isolation, rate limiting, explicit non-goals.
- [`docs/oracle-native-deployment.md`](docs/oracle-native-deployment.md) —
  exact Oracle Cloud ARM64 VM native (systemd) deployment steps.
- [`docs/operations.md`](docs/operations.md) — logs, restarts, queue
  inspection, secret rotation, free-tier constraints.
- [`docs/backup-and-recovery.md`](docs/backup-and-recovery.md) — backup,
  restore, and off-server backup guidance.
- [`docs/security-hardening.md`](docs/security-hardening.md) — what's
  already hardened and what to add before handling real client data.
