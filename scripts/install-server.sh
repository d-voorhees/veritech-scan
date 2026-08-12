#!/usr/bin/env bash
# One-time bootstrap for a fresh Ubuntu 24.04 ARM64 VM (e.g. Oracle Cloud
# Always Free Ampere A1) that will run Veritech Scan as native systemd
# services — no Docker, no containers, anywhere.
#
# Installs and configures, all via the system package manager:
#   - Caddy (reverse proxy / TLS)
#   - PostgreSQL (localhost only)
#   - Redis (localhost only)
#   - Python 3.12 + venv tooling, Node.js 22
#   - Chromium's OS-level dependencies (for Playwright, used by the worker)
#   - A dedicated, unprivileged deploy user with a scoped sudoers grant
#     limited to managing this app's own systemd units and reloading Caddy
#   - UFW, restricted to SSH/HTTP/HTTPS
#
# It does NOT touch sshd_config or disable password/key auth for you — SSH
# hardening is printed as guidance at the end (see the same rationale as
# before: never apply that over the only session you have open).
#
# Usage:
#   sudo ./scripts/install-server.sh [--yes] [--deploy-user veritech] \
#       [--postgres-password SECRET]
#
# If --postgres-password is omitted, one is generated and printed once
# (also written to /opt/veritech-scan/postgres-password.txt, readable only
# by root and the deploy user — move it into .env.production and delete it).
set -euo pipefail

ASSUME_YES=false
DEPLOY_USER="veritech"
POSTGRES_PASSWORD=""
APP_ROOT="/opt/veritech-scan"
PLAYWRIGHT_BROWSERS_PATH="${APP_ROOT}/ms-playwright"
PLAYWRIGHT_VERSION="1.49.1"

while [ $# -gt 0 ]; do
  case "$1" in
    --yes) ASSUME_YES=true; shift ;;
    --deploy-user) DEPLOY_USER="$2"; shift 2 ;;
    --postgres-password) POSTGRES_PASSWORD="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

confirm() {
  local prompt="$1"
  if [ "$ASSUME_YES" = true ]; then
    return 0
  fi
  read -r -p "$prompt [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

if [ "$(id -u)" -ne 0 ]; then
  echo "This script must be run as root (e.g. via sudo)." >&2
  exit 1
fi

ARCH="$(dpkg --print-architecture)"
if [ "$ARCH" != "arm64" ]; then
  echo "WARNING: expected arm64 (Oracle Ampere A1), detected '$ARCH'. Continuing anyway." >&2
fi

echo "== 1. Updating system packages =="
apt-get update -y
apt-get upgrade -y

echo "== 2. Installing base tooling =="
apt-get install -y --no-install-recommends \
  ca-certificates curl gnupg git build-essential ufw \
  python3.12 python3.12-venv python3-pip libpq-dev

echo "== 3. Installing PostgreSQL (localhost only) =="
if ! command -v psql >/dev/null 2>&1; then
  apt-get install -y postgresql postgresql-contrib
else
  echo "PostgreSQL already installed: $(psql --version)"
fi
systemctl enable --now postgresql

echo "== 4. Installing Redis (localhost only) =="
if ! command -v redis-server >/dev/null 2>&1; then
  apt-get install -y redis-server
else
  echo "Redis already installed: $(redis-server --version)"
fi
# Force localhost-only binding regardless of package defaults.
sed -i 's/^bind .*/bind 127.0.0.1 -::1/' /etc/redis/redis.conf
if ! grep -q '^bind ' /etc/redis/redis.conf; then
  echo 'bind 127.0.0.1 -::1' >> /etc/redis/redis.conf
fi
sed -i 's/^# *supervised .*/supervised systemd/' /etc/redis/redis.conf
systemctl enable --now redis-server
systemctl restart redis-server

echo "== 5. Installing Caddy =="
if ! command -v caddy >/dev/null 2>&1; then
  # Official Caddy apt repo instructions (dl.cloudsmith.io/public/caddy).
  # The fetched .deb.txt source line hardcodes the signed-by path below, so
  # the key must be dearmored to exactly that path for apt to trust it.
  apt-get install -y debian-keyring debian-archive-keyring apt-transport-https
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -y
  apt-get install -y caddy
else
  echo "Caddy already installed: $(caddy version)"
fi

echo "== 6. Installing Node.js 22 =="
if ! command -v node >/dev/null 2>&1 || ! node --version | grep -q '^v22'; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y nodejs
else
  echo "Node.js already installed: $(node --version)"
fi

echo "== 7. Creating non-root deploy user ($DEPLOY_USER) =="
if id "$DEPLOY_USER" >/dev/null 2>&1; then
  echo "User $DEPLOY_USER already exists."
else
  if confirm "Create user '$DEPLOY_USER' (no sudo group membership; scoped sudoers grant only)?"; then
    adduser --disabled-password --gecos "" "$DEPLOY_USER"
    # Read-only journal access (journalctl -u ...) without a broader sudo grant.
    usermod -aG systemd-journal "$DEPLOY_USER"
    echo "Created $DEPLOY_USER. Copy your SSH public key to /home/$DEPLOY_USER/.ssh/authorized_keys before disabling password auth."
  else
    echo "Skipped deploy user creation."
    DEPLOY_USER=""
  fi
fi

echo "== 8. Creating application directories =="
mkdir -p "$APP_ROOT"/{app,backups,artifacts,venv} "$PLAYWRIGHT_BROWSERS_PATH"
if [ -n "$DEPLOY_USER" ]; then
  chown -R "$DEPLOY_USER":"$DEPLOY_USER" "$APP_ROOT"
fi

echo "== 9. Creating Postgres database and app role =="
if [ -z "$POSTGRES_PASSWORD" ]; then
  POSTGRES_PASSWORD="$(openssl rand -base64 24)"
fi
sudo -u postgres psql -v ON_ERROR_STOP=1 <<-SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'veritech_scan') THEN
    CREATE ROLE veritech_scan WITH LOGIN PASSWORD '${POSTGRES_PASSWORD}';
  ELSE
    ALTER ROLE veritech_scan WITH PASSWORD '${POSTGRES_PASSWORD}';
  END IF;
END
\$\$;
SQL
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='veritech_scan'" | grep -q 1; then
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE DATABASE veritech_scan OWNER veritech_scan;"
fi
# Postgres listens on localhost only by default on a fresh install
# (listen_addresses = 'localhost' in postgresql.conf) — verify, don't assume.
PG_CONF="$(sudo -u postgres psql -tAc 'SHOW config_file;')"
if ! grep -Eq "^listen_addresses\s*=\s*'localhost'" "$PG_CONF"; then
  sed -i "s/^#\?listen_addresses.*/listen_addresses = 'localhost'/" "$PG_CONF"
  systemctl restart postgresql
fi

echo "$POSTGRES_PASSWORD" > "$APP_ROOT/postgres-password.txt"
chmod 600 "$APP_ROOT/postgres-password.txt"
[ -n "$DEPLOY_USER" ] && chown "$DEPLOY_USER":"$DEPLOY_USER" "$APP_ROOT/postgres-password.txt"

echo "== 10. Provisioning the Python venv + Playwright/Chromium =="
python3.12 -m venv "$APP_ROOT/venv"
"$APP_ROOT/venv/bin/pip" install --upgrade pip
"$APP_ROOT/venv/bin/pip" install "playwright==${PLAYWRIGHT_VERSION}"
# `--with-deps` installs the correct Debian package set for whatever
# architecture this VM actually is (this must run on the real ARM64 target,
# not be cross-built/emulated) and then downloads Chromium itself into
# PLAYWRIGHT_BROWSERS_PATH.
PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" "$APP_ROOT/venv/bin/playwright" install --with-deps chromium

echo "-- Verifying Chromium actually launches on this host --"
PLAYWRIGHT_BROWSERS_PATH="$PLAYWRIGHT_BROWSERS_PATH" "$APP_ROOT/venv/bin/python" - <<'PY'
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    page = browser.new_page()
    page.set_content("<html><body><h1>install-server.sh Chromium check</h1></body></html>")
    assert page.title() == ""  # no <title>; presence of a real render is what matters
    browser.close()
print("Chromium launched and rendered successfully.")
PY

if [ -n "$DEPLOY_USER" ]; then
  chown -R "$DEPLOY_USER":"$DEPLOY_USER" "$APP_ROOT/venv" "$PLAYWRIGHT_BROWSERS_PATH"
fi

echo "== 11. Installing the Caddyfile and systemd units =="
mkdir -p /etc/caddy
systemctl enable --now caddy
if [ -f "$APP_ROOT/app/deploy/caddy/Caddyfile" ]; then
  cp "$APP_ROOT/app/deploy/caddy/Caddyfile" /etc/caddy/Caddyfile
  caddy validate --config /etc/caddy/Caddyfile
  systemctl reload caddy || systemctl restart caddy
  cp "$APP_ROOT"/app/deploy/systemd/*.service /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable veritech-scan-api.service veritech-scan-worker.service veritech-scan-web.service
  echo "Units installed and enabled (not started yet — run scripts/deploy.sh first so"
  echo "dependencies/build/migrations are in place before the app starts)."
else
  echo "NOTE: repo not yet cloned into $APP_ROOT/app — skipping Caddyfile/systemd unit install."
  echo "      Re-run 'sudo ./scripts/install-server.sh --yes' after cloning, or just run"
  echo "      scripts/deploy.sh once the repo is present (it installs/refreshes both)."
fi

echo "== 12. Configuring scoped sudo for the deploy user =="
if [ -n "$DEPLOY_USER" ]; then
  cat > /etc/sudoers.d/veritech-scan-deploy <<SUDOERS
# Allow the deploy user to manage only this app's systemd units and reload
# Caddy, without full sudo/root access.
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart veritech-scan-api.service
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart veritech-scan-worker.service
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart veritech-scan-web.service
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl stop veritech-scan-api.service
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl stop veritech-scan-worker.service
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl start veritech-scan-api.service
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl start veritech-scan-worker.service
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl status veritech-scan-api.service
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl status veritech-scan-worker.service
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl status veritech-scan-web.service
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl is-active veritech-scan-api.service
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl is-active veritech-scan-worker.service
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl is-active veritech-scan-web.service
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl daemon-reload
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl reload caddy
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/systemctl restart caddy
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/cp /opt/veritech-scan/app/deploy/systemd/veritech-scan-api.service /etc/systemd/system/veritech-scan-api.service
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/cp /opt/veritech-scan/app/deploy/systemd/veritech-scan-worker.service /etc/systemd/system/veritech-scan-worker.service
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/cp /opt/veritech-scan/app/deploy/systemd/veritech-scan-web.service /etc/systemd/system/veritech-scan-web.service
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/cp /opt/veritech-scan/app/deploy/caddy/Caddyfile /etc/caddy/Caddyfile
$DEPLOY_USER ALL=(root) NOPASSWD: /usr/bin/caddy validate --config /etc/caddy/Caddyfile
SUDOERS
  chmod 440 /etc/sudoers.d/veritech-scan-deploy
  visudo -cf /etc/sudoers.d/veritech-scan-deploy
fi

echo "== 13. Configuring UFW (allow only SSH, HTTP, HTTPS) =="
if confirm "Enable UFW and allow only OpenSSH, 80/tcp, and 443/tcp?"; then
  ufw allow OpenSSH
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
  ufw status verbose
else
  echo "Skipped UFW configuration. Configure firewall rules manually before exposing this host."
fi

cat <<EOF

== install-server.sh complete ==

PostgreSQL role 'veritech_scan' password: $(cat "$APP_ROOT/postgres-password.txt")
(also saved to $APP_ROOT/postgres-password.txt, mode 600 — move it into
.env.production's DATABASE_URL and delete the file once you have.)

Next manual steps:

1. Log in as $DEPLOY_USER (copy your SSH public key into
   /home/$DEPLOY_USER/.ssh/authorized_keys first) and clone the private
   repository:
     sudo -iu $DEPLOY_USER
     git clone git@github.com:<your-org>/veritech-scan.git $APP_ROOT/app

2. Copy .env.example to $APP_ROOT/app/.env.production and fill in
   production values, using 127.0.0.1 for DATABASE_URL/REDIS_URL and the
   Postgres password printed above. See docs/oracle-native-deployment.md.

3. Run the deploy workflow:
     cd $APP_ROOT/app && ./scripts/deploy.sh

4. SSH hardening (apply yourself, after confirming your current session
   still works — do NOT do this over the only session you have open):
     - Confirm you can log in as $DEPLOY_USER with your SSH key.
     - In /etc/ssh/sshd_config, set:
         PasswordAuthentication no
         PermitRootLogin no
       Then: sudo systemctl restart ssh
     - Test a NEW connection in a separate terminal before closing your
       current session, to avoid locking yourself out.

EOF
