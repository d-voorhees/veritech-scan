# Operations

Day-2 operations for the single-VM Docker Compose deployment.

## Inspecting service logs

```bash
# all services, tailing
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f --tail=200

# one service
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f api
docker compose -f docker-compose.prod.yml --env-file .env.production logs -f worker
```

API and worker logs are structured JSON in production (`structlog`,
`LOG_FORMAT=json` set in `docker-compose.prod.yml`) — pipe through `jq` for
readability: `... logs api | jq .`.

## Restarting one service

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production restart worker
```

Restarting `worker` mid-scan will interrupt any in-flight collection step;
the affected `scan_jobs` row will be left `running` and the scan will appear
stuck. There's no automatic requeue in the MVP — see "Pausing scans safely"
below for how to handle this manually.

## Inspecting worker failures

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production logs worker | grep -i error
```

Per-scan failure detail lives in the database, not just logs:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec postgres \
  psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "select task_name, status, attempts, error_message from scan_jobs where scan_request_id = '<scan-id>';"
```

Or via the UI: open the scan's detail page — the "Collection tasks" panel
shows each task's status and error message directly.

## Inspecting queue status

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production exec redis redis-cli llen dramatiq:default
docker compose -f docker-compose.prod.yml --env-file .env.production exec redis redis-cli llen dramatiq:default.DQ
```

`dramatiq:default` is the pending-message queue; `.DQ` is the delayed
(retry) queue. A growing `dramatiq:default` length with an idle worker
process usually means the worker container is down or crash-looping —
check `docker compose ... ps worker` and worker logs first.

## Pausing scans safely

There is no built-in pause/resume for an in-flight scan in the MVP. To stop
processing without losing data:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production stop worker
```

The API will continue to accept new scan submissions (they queue in Redis)
but nothing will run until `worker` is started again
(`docker compose ... start worker`). Scans that were mid-run when the
worker stopped will remain in `status = running` with some `scan_jobs`
still `running`/`pending` — restarting the worker does **not** automatically
resume them (Dramatiq does not requeue an in-flight message on worker
restart in this configuration). For the MVP, manually re-trigger such a
scan by creating a new one; a "requeue stuck scan" admin action is a
reasonable post-MVP addition.

## Inspecting volume disk usage

```bash
docker system df -v
docker exec -it $(docker compose -f docker-compose.prod.yml --env-file .env.production ps -q postgres) \
  du -sh /var/lib/postgresql/data
docker run --rm -v veritech-scan_scan_artifacts:/data alpine du -sh /data
```

`scan_artifacts` (screenshots + HTML report exports) is the volume most
likely to grow steadily — there is no automatic pruning in the MVP. Monitor
it and add a retention policy (e.g. delete artifacts for scans older than
N days) before it becomes a problem on a small free-tier boot volume.

## Updating Docker images

```bash
cd /opt/veritech-scan/app
./scripts/deploy.sh main
```

Or manually: `git pull`, then
`docker compose -f docker-compose.prod.yml --env-file .env.production build`
followed by `... up -d`. Prefer `deploy.sh` — it also runs migrations and
verifies health, which a bare `up -d --build` does not.

## Rotating secrets

1. Generate a new value (`openssl rand -base64 32`, etc. — see
   `docs/oracle-deployment.md` step 8).
2. Update `.env.production`.
3. Recreate the affected services so they pick up the new environment:
   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.production up -d --force-recreate api worker
   ```
4. **Rotating `JWT_SECRET` invalidates every existing session** — all users
   will need to sign in again. Rotating `POSTGRES_PASSWORD` requires also
   updating it inside Postgres itself (`ALTER USER ... PASSWORD ...`) before
   recreating dependent services, or you'll lock the API/worker out of the
   database.

## Checking service health

```bash
./scripts/healthcheck.sh prod
```

Or `make healthcheck` for the local dev stack.

## Free-tier constraints (read before promising an SLA)

- **One server.** Everything — proxy, app, worker, database, queue — runs
  on a single Oracle Always Free ARM VM. There is no redundancy.
- **No automatic failover.** If the VM goes down, the app is down until
  it's manually restarted or the instance is recovered.
- **One worker, concurrency 1.** Scans run strictly one at a time
  (`SCAN_WORKER_CONCURRENCY=1`). This is intentional given free-tier memory
  limits, but it means throughput is low — plan scan scheduling
  accordingly, especially for browser-rendering steps.
- **Limited browser-scan throughput.** Playwright/Chromium is the heaviest
  step per scan; expect a small number of concurrent-ish scans queued
  sequentially, not parallel execution.
- **Disk growth needs monitoring.** Postgres data and `scan_artifacts` both
  grow unboundedly without a retention policy — check disk usage
  periodically (see above).
- **No high-availability promise.** Do not commit to an uptime SLA on this
  architecture without first adding redundancy.
- **Add off-server encrypted backups before accepting real client data.**
  `make backup-db` writes backups to `/opt/veritech-scan/backups` **on the
  same VM** — if the VM's disk is lost, so are the backups. Before this
  system handles real client engagements, ship backups off-box (e.g. to an
  Object Storage bucket) and consider encrypting them at rest. See
  `docs/backup-and-recovery.md`.
