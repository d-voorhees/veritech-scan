# Oracle Cloud deployment

Exact steps to deploy Veritech Scan to a single Oracle Cloud **Always Free**
ARM64 (Ampere A1) Ubuntu 24.04 VM.

> **Build on the VM itself.** The worker image's Docker build includes a
> `RUN python -m app.worker_check --startup-only` step that launches real
> Chromium. Building on an ARM64 host natively (as below) is required —
> cross-building for `linux/arm64` from an x86 machine via QEMU emulation is
> unreliable for Chromium and is not a supported path for this project.

## 1. Provision the Ubuntu 24.04 ARM64 VM

In the Oracle Cloud console: **Compute → Instances → Create Instance**.

- Image: **Canonical Ubuntu 24.04** (Minimal or default, ARM64/Ampere).
- Shape: **VM.Standard.A1.Flex** (Always Free eligible — up to 4 OCPU / 24GB
  total across your Always Free A1 instances).
- Networking: create/use a VCN with a public subnet.

## 2. Create a public IP

Assign a public IPv4 address to the instance during creation (or attach a
reserved public IP afterward via **Networking → IP Management**). Note this
IP — it's what `app.veritechdiligence.com` will point to.

## 3. Configure SSH key access

Provide your SSH public key during instance creation (Oracle's console
supports pasting a key or generating one). Confirm you can connect:

```bash
ssh ubuntu@<public-ip>
```

## 4. Install Docker and the Compose plugin

Copy the repo to the VM (or clone it directly there — see step 6), then run
the bootstrap script, which installs Docker Engine + Compose plugin,
creates a non-root deploy user, and configures UFW:

```bash
scp -r scripts ubuntu@<public-ip>:~/bootstrap
ssh ubuntu@<public-ip>
sudo ~/bootstrap/bootstrap-server.sh
```

Review `scripts/bootstrap-server.sh` before running it — it prompts for
confirmation before creating the deploy user and enabling UFW, and it
prints SSH-hardening guidance at the end rather than applying it
automatically (see that script's header comment for why).

## 5. Configure UFW to allow only SSH, HTTP, and HTTPS

Done by `bootstrap-server.sh` (`ufw allow OpenSSH`, `80/tcp`, `443/tcp`,
`ufw enable`). Verify:

```bash
sudo ufw status verbose
```

## 6. Clone the private repository

As the deploy user created in step 4:

```bash
sudo -iu veritech
mkdir -p /opt/veritech-scan && cd /opt/veritech-scan
git clone git@github.com:<your-org>/veritech-scan.git app
cd app
```

(Set up a deploy key or SSH agent forwarding for the private repo beforehand.)

## 7. Configure `.env.production`

```bash
cp .env.example .env.production
```

Edit `.env.production` and set at minimum:

```
APP_ENV=production
APP_DOMAIN=app.veritechdiligence.com
APP_URL=https://app.veritechdiligence.com
MARKETING_SITE_URL=https://veritechdiligence.com

POSTGRES_DB=veritech_scan
POSTGRES_USER=veritech_scan
POSTGRES_PASSWORD=<generated — step 8>
DATABASE_URL=postgresql+psycopg://veritech_scan:<same-password>@postgres:5432/veritech_scan

REDIS_URL=redis://redis:6379/0

JWT_SECRET=<generated — step 8>
INITIAL_ADMIN_EMAIL=<your admin email>
INITIAL_ADMIN_PASSWORD=<generated — step 8>
```

## 8. Generate secure secrets

```bash
openssl rand -base64 32   # -> POSTGRES_PASSWORD
openssl rand -base64 48   # -> JWT_SECRET
openssl rand -base64 24   # -> INITIAL_ADMIN_PASSWORD
```

Never commit `.env.production`. It's already covered by `.gitignore`.

## 9. Build and start production services

```bash
cd /opt/veritech-scan/app
make prod-up
```

This runs `docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build`,
building the ARM64 `api`, `worker`, and `web` images locally on the VM and
starting `caddy`, `web`, `api`, `worker`, `postgres`, and `redis`.

## 10. Run migrations

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production run --rm api alembic upgrade head
```

(Also available as `make migrate`, which targets whichever compose file
`DATABASE_URL` in your active environment points at — for production, run
the explicit command above or set up your shell to source
`.env.production` first.)

Then bootstrap the admin user:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production run --rm api python -m app.seed --admin-only
```

## 11. Configure DNS

- `veritechdiligence.com` — leave exactly as-is on **GitHub Pages** (this
  repository does not touch the marketing site).
- `app.veritechdiligence.com` — create an **A record** pointing at the VM's
  public IP from step 2 (and an **AAAA record** if the VM has a public
  IPv6 address).

DNS propagation can take a few minutes to a few hours depending on your
registrar's TTL.

## 12. Verify Caddy TLS certificate issuance

Once DNS resolves to the VM, Caddy automatically requests a certificate from
Let's Encrypt on first request to `app.veritechdiligence.com`. Check:

```bash
curl -vI https://app.veritechdiligence.com/health
docker compose -f docker-compose.prod.yml logs caddy | grep -i certificate
```

If issuance fails, confirm DNS has propagated and that ports 80/443 are
reachable from the public internet (Let's Encrypt's HTTP-01 challenge needs
port 80 open, which `bootstrap-server.sh` already configured via UFW).

## 13. Verify application, API, worker, Postgres, and Redis health

```bash
./scripts/healthcheck.sh prod
```

This checks Postgres readiness, Redis `PING`, the API's `/health` endpoint
(which itself verifies Postgres + Redis connectivity from the API's
perspective), that the worker process imports cleanly, Caddy's admin API,
and the web app's `/healthz` route through Caddy.

Also confirm the full user flow: open `https://app.veritechdiligence.com`,
sign in with the admin account from step 10, and check `/scans` for the
seeded demo scan (run `make seed` — without `--admin-only` — if you want
the synthetic demo data too).

## 14. Update and rollback procedures

**Update / deploy a new release:**

```bash
cd /opt/veritech-scan/app
./scripts/deploy.sh main
```

`deploy.sh` pulls the branch, builds images, runs migrations explicitly,
starts/updates services, and verifies health — printing recent logs and
exiting non-zero if anything fails, without leaving the stack half-updated.

**Rollback to a prior release:**

```bash
git checkout <prior-commit-or-tag>
./scripts/deploy.sh --no-pull
```

This rebuilds images from the checked-out (older) commit, re-runs
migrations (Alembic migrations in this project are additive/forward-only by
convention — a rollback to older *code* against a newer *schema* is a
case-by-case judgment call; for the MVP's schema this is not expected to be
an issue, but always take a fresh `make backup-db` before rolling back a
release that included a migration), and restarts services.
