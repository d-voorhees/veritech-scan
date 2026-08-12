# Operations

Day-2 operations for the single-VM native (systemd) deployment. No Docker
is installed anywhere in this stack — everything below uses `systemctl`,
`journalctl`, and the native `psql`/`redis-cli` clients directly.

## Inspecting service logs

```bash
# all three app services, tailing
journalctl -u veritech-scan-api -u veritech-scan-worker -u veritech-scan-web -f

# one service
journalctl -u veritech-scan-api -f
journalctl -u veritech-scan-worker -f

# caddy
journalctl -u caddy -f
```

API and worker logs are structured JSON in production (`structlog`,
`LOG_FORMAT=json` set in `.env.production`) — pipe through `jq` for
readability: `journalctl -u veritech-scan-api -o cat | jq .`.

The deploy user (created by `scripts/install-server.sh`) is a member of the
`systemd-journal` group, so `journalctl -u ...` works without `sudo`.

## Restarting one service

```bash
sudo systemctl restart veritech-scan-worker
```

Restarting `veritech-scan-worker` mid-scan will interrupt any in-flight
collection step; the affected `scan_jobs` row will be left `running` and
the scan will appear stuck. There's no automatic requeue in the MVP — see
"Pausing scans safely" below for how to handle this manually.

## Inspecting worker failures

```bash
journalctl -u veritech-scan-worker --no-pager | grep -i error
```

Per-scan failure detail lives in the database, not just logs:

```bash
psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "select task_name, status, attempts, error_message from scan_jobs where scan_request_id = '<scan-id>';"
```

Or via the UI: open the scan's detail page — the "Collection tasks" panel
shows each task's status and error message directly.

## Inspecting queue status

```bash
redis-cli -h 127.0.0.1 llen dramatiq:default
redis-cli -h 127.0.0.1 llen dramatiq:default.DQ
```

`dramatiq:default` is the pending-message queue; `.DQ` is the delayed
(retry) queue. A growing `dramatiq:default` length with an idle worker
process usually means `veritech-scan-worker` is down or crash-looping —
check `sudo systemctl status veritech-scan-worker` and its journal first.

## Pausing scans safely

There is no built-in pause/resume for an in-flight scan in the MVP. To stop
processing without losing data:

```bash
sudo systemctl stop veritech-scan-worker
```

The API will continue to accept new scan submissions (they queue in Redis)
but nothing will run until the worker is started again
(`sudo systemctl start veritech-scan-worker`). Scans that were mid-run when
the worker stopped will remain in `status = running` with some `scan_jobs`
still `running`/`pending` — restarting the worker does **not**
automatically resume them (Dramatiq does not requeue an in-flight message
on worker restart in this configuration). For the MVP, manually re-trigger
such a scan by creating a new one; a "requeue stuck scan" admin action is a
reasonable post-MVP addition.

## Inspecting disk usage

```bash
df -h /opt/veritech-scan
sudo du -sh /var/lib/postgresql/*/main
du -sh /opt/veritech-scan/artifacts
```

`/opt/veritech-scan/artifacts` (screenshots + HTML report exports,
`ARTIFACT_STORAGE_LOCAL_PATH`) is the location most likely to grow steadily
— there is no automatic pruning in the MVP. Monitor it and add a retention
policy (e.g. delete artifacts for scans older than N days) before it
becomes a problem on a small free-tier boot volume.

## Deploying an update

```bash
cd /opt/veritech-scan/app
./scripts/deploy.sh main
```

Or `make deploy`. This pulls, reinstalls Python/Node dependencies, rebuilds
the Next.js bundle, runs migrations, restarts all three systemd services,
reloads Caddy, and verifies health — see
`docs/oracle-native-deployment.md` for the full breakdown. Prefer it over
manually pulling and restarting services — it's the only path that also
runs migrations and verifies health before declaring success.

## Rotating secrets

1. Generate a new value (`openssl rand -base64 32`, etc. — see
   `docs/oracle-native-deployment.md` step 7).
2. Update `.env.production`.
3. Restart the affected services so they pick up the new environment:
   ```bash
   sudo systemctl restart veritech-scan-api veritech-scan-worker
   ```
4. **Rotating `JWT_SECRET` invalidates every existing session** — all users
   will need to sign in again. Rotating `POSTGRES_PASSWORD` requires also
   updating it inside Postgres itself:
   ```bash
   sudo -u postgres psql -c "ALTER ROLE veritech_scan WITH PASSWORD '<new-password>';"
   ```
   before restarting the API/worker, or you'll lock them out of the
   database.

## Checking service health

```bash
./scripts/healthcheck.sh prod
# or: make healthcheck MODE=prod
```

Checks that `veritech-scan-api`, `veritech-scan-worker`,
`veritech-scan-web`, and `caddy` are all `active` under systemd, plus
Postgres, Redis, the API's `/health`, the web app, a real worker
queue/Chromium check, and the public HTTPS endpoint.

For the local dev stack (native processes, no systemd), use
`./scripts/healthcheck.sh` (defaults to `dev` mode) or `make healthcheck`.

## Free-tier constraints (read before promising an SLA)

- **One server.** Everything — Caddy, app, worker, database, queue — runs
  as native processes on a single Oracle Always Free ARM VM. There is no
  redundancy.
- **No automatic failover.** If the VM goes down, the app is down until
  it's manually restarted or the instance is recovered. `systemd`'s
  `Restart=on-failure` on all three app units handles process crashes, not
  VM-level outages.
- **One worker, concurrency 1.** Scans run strictly one at a time
  (`--processes 1 --threads 1` in `deploy/systemd/veritech-scan-worker.service`).
  This is intentional given free-tier memory limits, but it means
  throughput is low — plan scan scheduling accordingly, especially for
  browser-rendering steps.
- **Limited browser-scan throughput.** Playwright/Chromium is the heaviest
  step per scan; expect a small number of concurrent-ish scans queued
  sequentially, not parallel execution.
- **Disk growth needs monitoring.** Postgres data and
  `/opt/veritech-scan/artifacts` both grow unboundedly without a retention
  policy — check disk usage periodically (see above).
- **No high-availability promise.** Do not commit to an uptime SLA on this
  architecture without first adding redundancy.
- **Add off-server encrypted backups before accepting real client data.**
  `make backup-db` writes backups to `/opt/veritech-scan/backups` **on the
  same VM** — if the VM's disk is lost, so are the backups. Before this
  system handles real client engagements, ship backups off-box (e.g. to an
  Object Storage bucket) and consider encrypting them at rest. See
  `docs/backup-and-recovery.md`.
