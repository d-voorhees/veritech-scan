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

- A public marketing homepage at `/`, branded to match
  [veritechdiligence.com](https://veritechdiligence.com) (type, color,
  layout), with "Sign in" and "Request access" calls to action. The
  authenticated app lives at `/dashboard`.
- Invite-only, authenticated app (no public signup).
- Submit a domain/URL + business notes + crawl depth (10/25/50 pages) +
  a required authorization acknowledgment.
- An on-demand scan pipeline (no persistent worker, no Redis — see
  "Architecture" below) covering: HTTP/redirect checks, robots.txt +
  sitemap discovery, a bounded same-origin crawl, DNS/SPF/DMARC posture,
  Playwright homepage rendering + third-party dependency inventory, local
  rules-based technology detection, and a performance adapter (local
  metrics always; Google PageSpeed Insights optionally, when configured).
- A deterministic, versioned rules engine (12 rules) that turns collected
  evidence into severity- and confidence-scored findings — never an LLM.
- A full report UI: status, task panel, risk register, expandable evidence,
  DNS/HTTP/crawl/technology/performance sections, known limitations, and a
  clean HTML export meant for "Print → Save as PDF."
- Deploys to Fly.io: one web/API Machine plus on-demand scan-runner
  Machines, with PostgreSQL (hosted on [Neon](https://neon.tech), external
  to Fly) as the only persistent dependency.

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

## Architecture: web/API Machine vs. scan-runner Machines

Veritech Scan runs as a single Fly.io app with **two Machine roles**, built
from one image (root `Dockerfile`, role selected by `scripts/entrypoint.sh`):

- **Web/API Machine** — Next.js + FastAPI. Serves the browser and the API.
  Configured in `fly.toml` with `auto_stop_machines = "stop"`,
  `auto_start_machines = true`, `min_machines_running = 0`: it stops when
  idle and Fly's proxy auto-starts it again on the next request. It never
  runs a scan itself and never runs a permanent queue worker.
- **Scan-runner Machine** — created on demand, exactly one per scan, via
  the Fly Machines API (`apps/api/app/services/fly_machines.py`). It
  receives the scan ID (via the `SCAN_ID` environment variable), claims the
  scan, runs every collection stage, persists evidence/findings/events,
  sets the final status, and exits. The Machine is then destroyed
  (`config.auto_destroy = true`).

**Why on-demand instead of an always-on worker:** a scan's actual compute
need is bursty and short (a few seconds to `SCAN_MAX_TOTAL_MINUTES`, default
10) — running a worker continuously to handle that would mean paying for
idle time between scans. There's no Redis, no Dramatiq, no Celery, and no
persistent queue anywhere in this architecture: the API asks Fly to create
a Machine per scan, and PostgreSQL — not memory, not a queue — is the
single source of truth for scan status. The API layer only ever *polls the
database*; see `docs/architecture.md` for the full flow and diagram.

### Data flow

The database is **not** hosted on Fly — it's a [Neon](https://neon.tech)
Postgres project, external to the Fly app, reached over a TLS connection
(`sslmode=require`) from whichever Machine needs it:

```
Browser
  │ HTTPS
  ▼
Web/API Machine (Fly, autostop/autostart)
  │ reads/writes scan state           │ POST /apps/{app}/machines
  ▼                                   ▼ (Fly Machines API)
Neon Postgres (external) ◄──────── Scan-runner Machine (Fly, on-demand)
  ▲ persists evidence/findings/events, then exits
  └───────────────────────────────────┘
```

Both Machine roles connect to the same Neon database independently — there
is no proxy or connection-sharing between them. This also means Fly and the
database scale/bill independently: the two Machine roles above scale to
zero when idle, while Neon is the one component that's always provisioned
(see "Known limitations").

## Local setup

Prerequisites: **PostgreSQL 16+ running locally**, Python 3.12 (3.11 also
works), and Node.js 22. **No Docker, no Redis, and no Fly.io account are
required for local development** — starting a scan locally runs the same
runner code as a plain background subprocess on your own machine instead of
calling the Fly Machines API (see `request_scan_runner` in
`apps/api/app/services/scan_orchestrator.py`).

Install Postgres with your platform's package manager (e.g.
`brew install postgresql@16` on macOS, `sudo apt install postgresql` on
Ubuntu), then create the database and role:

```bash
createdb veritech_scan
createuser veritech_scan --pwprompt   # set password to match .env
```

```bash
cp .env.example .env
# edit .env — DATABASE_URL defaults to 127.0.0.1; set the password to match
# the role you just created. Leave the FLY_* variables unset for local dev.

cd apps/api && python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt && playwright install chromium
cd ../web && npm install
cd ../..

make migrate       # alembic upgrade head
make seed          # creates the dev admin user + a synthetic demo scan
make dev           # starts uvicorn --reload and next dev together
```

Open http://localhost:3000 and sign in with `INITIAL_ADMIN_EMAIL` /
`INITIAL_ADMIN_PASSWORD` from your `.env` (defaults:
`admin@example.com` / `change-me` — **change these** even for local dev if
your machine is at all shared).

`make dev` runs both processes in the foreground (Ctrl+C stops both). To
run them separately instead (e.g. in different terminals):

```bash
cd apps/api && PYTHONPATH=. .venv/bin/uvicorn app.main:app --reload --port 8000
cd apps/web && npm run dev
```

## Environment configuration

All configuration is via environment variables — see
[`.env.example`](./.env.example) for the full list with defaults, including
product identity (`PRODUCT_NAME`, `PARENT_BRAND`, `APP_DOMAIN`, ...), scan
safety limits (`SCAN_MAX_PAGES`, `SCAN_DEFAULT_REQUEST_DELAY_SECONDS`,
`SCAN_MAX_TOTAL_MINUTES`, `SCAN_CREATE_RATE_LIMIT_PER_HOUR`), and optional
providers (`GOOGLE_PAGESPEED_API_KEY`, `SENTRY_DSN`). Never commit `.env` or
any `.env.*` file — all are gitignored.

### Required Fly secrets (production only)

Set these with `flyctl secrets set` — see `docs/fly-deployment.md` for the
full walkthrough of every value:

| Variable | Purpose |
|---|---|
| `FLY_APP_NAME` | The Fly app name; used by both `flyctl` commands and the app's own Fly Machines API calls. |
| `FLY_API_TOKEN` | Lets the API create scan-runner Machines. Server-side only — **never sent to the browser**. |
| `FLY_PRIMARY_REGION` | Region new scan-runner Machines are created in. |
| `DATABASE_URL` | The Neon Postgres connection string (`postgresql+psycopg://...?sslmode=require`), set by hand from the Neon dashboard/CLI — not by Fly. `FLY_DATABASE_URL` is an alternate name the app also accepts, for the (unused here) case of `fly postgres attach` setting it automatically instead. |
| `APP_URL` | The app's public URL. |
| `MARKETING_SITE_URL`, `PRODUCT_NAME`, `PARENT_BRAND` | Product identity shown in the UI/API. |
| `JWT_SECRET` | Session signing secret. |
| `INITIAL_ADMIN_EMAIL`, `INITIAL_ADMIN_PASSWORD` | Bootstrap admin account (`make seed`/`app.seed --admin-only`). |
| `GOOGLE_PAGESPEED_API_KEY` | Optional — enables PageSpeed Insights metrics in the performance section. |
| `SENTRY_DSN` | Optional — error reporting. |

### Database requirements

PostgreSQL is the **only** persistent dependency — scan status, events,
evidence, findings, and reports are all Postgres rows; there is no Redis
and no other stateful service. Production uses [Neon](https://neon.tech)
(project `veritech-scan`), external to Fly — not Fly's own Postgres
offering. `app/config.py`'s `resolved_database_url` also accepts
`FLY_DATABASE_URL` as a fallback name, which would let a future move to
Fly Postgres (or any other provider) work by just changing the secret
value, but nothing in this deployment relies on that today. See
`docs/fly-deployment.md` for provisioning and `docs/fly-operations.md` for
backup guidance.

## Migrations

```bash
make migrate                 # alembic upgrade head, using apps/api/.venv (local dev)
make fly-migrate              # same, against production, via a one-off Fly Machine
```

Migrations are **never** run automatically at Machine startup — the web/API
and scan-runner Machines never run `alembic upgrade head` themselves. In
production, migrations instead run automatically as the last step of the
`Deploy` GitHub Actions workflow (`.github/workflows/deploy.yml`): every push
to `main` that passes the test suite runs `flyctl deploy`, then
`./scripts/migrate-fly.sh` against the image just deployed. Run
`make fly-migrate` by hand only if you need to apply a migration outside
that pipeline (e.g. a deploy triggered via `workflow_dispatch` before a
schema change has merged, or a manual `make fly-deploy` from your machine).

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

The backend suite (`tests/backend/`) covers URL normalization,
SSRF/private-IP/redirect-revalidation protections, crawl URL filtering and
max-page limits, SPF/DMARC parsing, all 12 rules (firing and non-firing
cases), finding-to-evidence linkage, the scan creation/retrieval API and
ownership authorization, scan status transitions, duplicate-runner
prevention, Fly Machine creation failure handling, partial-completion
behavior after a simulated task failure, database-backed scan-event
history, a real Chromium launch + render check, and one fully mocked
end-to-end happy-path scan (`test_e2e_scan.py`). All Fly Machines API calls
are mocked in tests — **the test suite never needs Docker, Redis, Oracle,
live Fly credentials, or a real Fly app.**

`make test` runs `apps/api/.venv/bin/python -m pytest` from the repo root
(picking up `pytest.ini`'s `testpaths = tests/backend`) against whatever
`DATABASE_URL` is set in your environment/`.env`, then
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
   while the scan is `queued`/`starting`/`running` and shows each
   collection task's status live.
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

- **Cold starts for the web/API app.** `min_machines_running = 0` means the
  first request after an idle period waits for Fly to autostart the
  Machine — typically a few seconds.
- **Cold starts for scan runners.** Every scan waits for its Fly Machine to
  boot before processing starts; there's no "warm" runner.
- **One scan per runner.** Each scan gets its own Machine — there is no
  batching/sharing, by design (see "Architecture" above).
- **The database is a persistent, paid dependency.** Unlike the two Machine
  roles, Neon Postgres doesn't scale to zero at the same tier this project
  uses — it's the one always-on cost in this architecture, and it's billed
  and managed separately from Fly (a different provider, a different
  invoice).
- **No public signup** — invite-only by design; see `docs/threat-model.md`.
- **Finite scan resource/time limits.** `SCAN_MAX_TOTAL_MINUTES` (default
  10) and the 10/25/50 page caps bound every scan; browser rendering covers
  the homepage only, not every crawled page.
- `robots.txt` is recorded as evidence but not enforced against the
  crawler (documented in the report itself, not just here).
- DKIM discovery is out of scope for the MVP (SPF + DMARC only).
- Google PageSpeed Insights metrics only appear when
  `GOOGLE_PAGESPEED_API_KEY` is configured; otherwise the report says so
  explicitly rather than silently omitting the section.

## Fly.io deployment

Full step-by-step in [`docs/fly-deployment.md`](docs/fly-deployment.md);
day-two operations (logs, failed scans, cleaning up Machines, secret
rotation) in [`docs/fly-operations.md`](docs/fly-operations.md). Short
version — **no Docker or Docker Desktop required on your machine**, since
`fly deploy --remote-only` builds on Fly's own infrastructure:

```bash
export FLY_APP_NAME=veritech-scan
flyctl auth login
make fly-init                # create the app
# create a Neon project, get its connection string, and set every secret
# listed above (DATABASE_URL included) — see docs/fly-deployment.md
make fly-deploy               # fly deploy --remote-only
make fly-migrate              # alembic upgrade head, via a one-off Fly Machine
make fly-status                # app + Machine status
make fly-scan-runner-test       # creates a real synthetic scan end-to-end
```

### Inspecting failed scans

Query `scan_requests`/`scan_events` directly, or use the API
(`GET /scans/{id}`, `GET /scans/{id}/events`) — see
`docs/fly-operations.md`'s "Inspecting a failed scan".

### Inspecting and cleaning up stopped scan-runner Machines

```bash
flyctl machine list --app "$FLY_APP_NAME"
flyctl machine destroy <machine_id> --app "$FLY_APP_NAME" --force
```

Scan-runner Machines self-destruct after a scan (`config.auto_destroy`);
Fly keeps a Machine around for ~2 hours after a *non-zero* exit
specifically so you can inspect it before it's cleaned up automatically.
See `docs/fly-operations.md` for detail.

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) for notable fixes and changes.

## Documentation index

- [`docs/architecture.md`](docs/architecture.md) — system diagram, why
  scan-runners are on-demand Fly Machines instead of a persistent worker,
  the full scan initiation flow, collection/evidence/rules/report flow.
- [`docs/rules-engine.md`](docs/rules-engine.md) — rule architecture,
  versioning, the full rule catalog, how to add a rule safely.
- [`docs/threat-model.md`](docs/threat-model.md) — SSRF prevention, crawl
  boundaries, authorization, isolation, rate limiting, explicit non-goals.
- [`docs/fly-deployment.md`](docs/fly-deployment.md) — exact Fly.io initial
  setup and deployment commands.
- [`docs/fly-operations.md`](docs/fly-operations.md) — logs, failed-scan
  inspection, scan-runner Machine cleanup, secret rotation, cost notes.
- [`docs/security-hardening.md`](docs/security-hardening.md) — what's
  already hardened and what to add before handling real client data.
- [`deploy/fly/README.md`](deploy/fly/README.md) — quick command reference
  for the Fly deployment.
