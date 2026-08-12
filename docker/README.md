# docker/

Application Dockerfiles live next to the code they build
(`apps/api/Dockerfile`, `apps/worker/Dockerfile`, `apps/web/Dockerfile`) so
each stays in sync with its own `requirements.txt`/`package.json`. This
directory holds cross-cutting Docker/deployment notes that don't belong to
any single app.

## ARM64 Playwright build notes

`apps/worker/Dockerfile` builds Chromium support from `python:3.12-slim`
(a genuinely multi-arch base image) via `playwright install --with-deps
chromium`, rather than using `mcr.microsoft.com/playwright/python`, which
has historically prioritized `linux/amd64` and is not a reliable ARM64
target. `--with-deps` resolves the correct Debian package set for whatever
architecture the image is being built on — this is also why the worker
image **must be built natively on an ARM64 host** (the target Oracle Cloud
VM itself), not cross-built via QEMU emulation from an x86 machine. See
`docs/oracle-deployment.md`.

The worker Dockerfile's final build step,
`RUN python -m app.worker_check --startup-only`, launches real Chromium
during the image build. If Chromium cannot launch on the build host's
architecture, the build fails immediately instead of shipping a broken
image.

## Where everything else lives

- Local development stack: `../docker-compose.yml`
- Production stack: `../docker-compose.prod.yml`
- Reverse proxy / TLS / routing: `../Caddyfile`
- Named volumes (`postgres_data`, `redis_data`, `caddy_data`,
  `caddy_config`, `scan_artifacts`, `app_uploads`): declared at the bottom
  of both compose files. `app_uploads` is reserved and not yet mounted by
  any service — the MVP has no user-upload feature — but is declared now so
  a future feature (e.g. attaching acquisition documents to a scan) doesn't
  require a volume-migration story.
