# Backup and recovery

## What's backed up

`scripts/backup-postgres.sh` backs up the **Postgres database only** — every
table under `docs/architecture.md`'s data model (users, scans, evidence,
findings, reports, etc). It does **not** back up
`/opt/veritech-scan/artifacts` (screenshots, generated HTML report exports)
— those are regenerable (re-exporting a report re-renders it from the
database) with the exception of Playwright screenshots, which are not
currently reproducible after the fact once a scan's evidence has been
superseded. Treat screenshot loss as acceptable for the MVP; if that
changes, extend the backup script to also `tar` the artifacts directory.

## Creating a backup

```bash
make backup-db
# or directly:
./scripts/backup-postgres.sh
```

This runs the native `pg_dump` binary against `127.0.0.1:5432` (installed by
`scripts/install-server.sh` alongside the Postgres server itself, so the
version always matches), compresses the output, and writes a timestamped
file to `/opt/veritech-scan/backups/veritech-scan-<timestamp>.sql.gz` (mode
`600`). The 14 most recent backups are retained by default; older ones are
pruned automatically (`--retain N` to change this). The script fails loudly
(non-zero exit, partial file removed) if `pg_dump` errors or produces an
empty file. The Postgres password is read from `.env.production` and passed
via a `PGPASSWORD` environment variable scoped to the single `pg_dump`
invocation — it is never logged or echoed.

Backups on a fresh install won't exist until you run this at least once —
there is **no automatic daily cron job configured out of the box**. Set one
up:

```bash
# as the deploy user, crontab -e:
0 3 * * * cd /opt/veritech-scan/app && ./scripts/backup-postgres.sh >> /var/log/veritech-scan-backup.log 2>&1
```

## Restoring a backup

```bash
./scripts/restore-postgres.sh /opt/veritech-scan/backups/veritech-scan-<timestamp>.sql.gz
```

This is destructive — it **overwrites all current data** in the target
database. The script:

1. Refuses to run without a backup file path.
2. Prints a clear warning and requires you to type the database name to
   confirm (or pass `--yes` for non-interactive use, e.g. in a documented
   disaster-recovery runbook).
3. Stops `veritech-scan-api` and `veritech-scan-worker` via `systemctl`
   first (they must not write mid-restore).
4. Restores via the native `psql` client against `127.0.0.1:5432`, with
   `ON_ERROR_STOP=on` so a partial failure stops immediately rather than
   silently continuing.
5. Restarts `veritech-scan-api` and `veritech-scan-worker`.

Via Make: `make restore-db FILE=/opt/veritech-scan/backups/veritech-scan-<timestamp>.sql.gz ARGS=--yes`

**Expected downtime:** typically under a minute at MVP scale (a few scans'
worth of data) — dominated by `api`/`worker` systemd stop/start time, not
the restore itself.

**Verification after restore:**

```bash
./scripts/healthcheck.sh prod
```

Then open the app and confirm a scan you know should exist (e.g. the
seeded demo scan, or a recent real scan) is present with its findings and
evidence intact.

## Off-server backups (required before real client data)

The default setup writes backups to the **same VM's disk**. This protects
against accidental data corruption or a bad migration, but **not** against
VM loss, disk failure, or account compromise. Before accepting real client
engagement data:

1. Sync `/opt/veritech-scan/backups` to an off-server location — Oracle
   Object Storage, an encrypted S3/R2 bucket, or even a periodic `scp` to a
   separate machine. A simple approach:
   ```bash
   # after each backup, e.g. appended to the same cron job:
   oci os object put --bucket-name veritech-scan-backups --file "$latest_backup" --namespace <your-namespace>
   ```
2. Encrypt backups at rest if the destination doesn't already do so
   (`gpg --symmetric` before upload, or rely on the storage provider's
   server-side encryption plus a private bucket).
3. Periodically test a restore into a scratch environment — an untested
   backup is not a backup.

This is called out explicitly because it's easy to configure `make
backup-db` once, feel covered, and never verify that restores actually work
or that backups survive VM loss.
