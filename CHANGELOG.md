# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Changed

- **Replaced the Oracle Cloud/systemd/Caddy/Dramatiq+Redis deployment with
  Fly.io.** The app now deploys as one Fly app with two Machine roles: an
  always-deployed web/API Machine (Next.js + FastAPI, autostop/autostart,
  `min_machines_running = 0`) and on-demand scan-runner Machines created
  per scan via the Fly Machines API, which exit and self-destruct when the
  scan finishes. There is no persistent worker and no Redis/Dramatiq/Celery
  anywhere in the stack; scan status, events, evidence, findings, and
  reports all live in PostgreSQL, and the API polls the database rather
  than holding queue/worker state in memory. Added `starting` and
  `cancelled` to the scan status lifecycle, plus `runner_machine_id`,
  `heartbeat_at`, and `retry_count` tracking on `scan_requests`. Rate
  limiting moved from a Redis counter to a Postgres query. See
  `docs/architecture.md` and `docs/fly-deployment.md`.

### Fixed

- `apps/api/.env` and `apps/web/.env` symlinks to the repo-root `.env`.
  Pydantic-settings (`apps/api/app/config.py`) and Next.js both resolve
  `.env` relative to their own working directory, but `make migrate`,
  `make seed`, and `make dev` all `cd` into `apps/api`/`apps/web` before
  running. Without the symlinks, the root `.env` was silently ignored and
  commands fell back to `config.py`'s hardcoded defaults — including a
  `postgres` hostname that only resolves inside Docker — causing
  `make migrate` to fail with `nodename nor servname provided, or not
  known` even when a correctly filled-out root `.env` was present.
