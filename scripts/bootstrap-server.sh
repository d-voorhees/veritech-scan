#!/usr/bin/env bash
# One-time bootstrap for a fresh Ubuntu 24.04 ARM64 VM (e.g. Oracle Cloud
# Always Free Ampere A1) that will run Veritech Scan via Docker Compose.
#
# This script is deliberately conservative:
#   - It updates packages, installs Docker, creates a deploy user, and
#     configures UFW for HTTP/HTTPS/SSH only.
#   - It does NOT touch sshd_config or disable password/key auth for you.
#     SSH hardening is printed as guidance at the end — apply it yourself
#     after confirming you still have a working session.
#   - Every destructive/irreversible step asks for confirmation unless
#     --yes is passed.
#
# Usage:
#   sudo ./scripts/bootstrap-server.sh [--yes] [--deploy-user veritech]
set -euo pipefail

ASSUME_YES=false
DEPLOY_USER="veritech"

while [ $# -gt 0 ]; do
  case "$1" in
    --yes) ASSUME_YES=true; shift ;;
    --deploy-user) DEPLOY_USER="$2"; shift 2 ;;
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

echo "== 1. Updating system packages =="
apt-get update -y
apt-get upgrade -y

echo "== 2. Installing Docker Engine + Compose plugin =="
if ! command -v docker >/dev/null 2>&1; then
  apt-get install -y ca-certificates curl gnupg
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  ARCH="$(dpkg --print-architecture)"
  CODENAME="$(. /etc/os-release && echo "$VERSION_CODENAME")"
  echo \
    "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
else
  echo "Docker already installed: $(docker --version)"
fi

echo "== 3. Creating non-root deploy user ($DEPLOY_USER) =="
if id "$DEPLOY_USER" >/dev/null 2>&1; then
  echo "User $DEPLOY_USER already exists."
else
  if confirm "Create user '$DEPLOY_USER' with sudo + docker group membership?"; then
    adduser --disabled-password --gecos "" "$DEPLOY_USER"
    usermod -aG sudo "$DEPLOY_USER"
    echo "Created $DEPLOY_USER. Copy your SSH public key to /home/$DEPLOY_USER/.ssh/authorized_keys before disabling password auth."
  else
    echo "Skipped deploy user creation."
  fi
fi

echo "== 4. Adding $DEPLOY_USER to the docker group =="
usermod -aG docker "$DEPLOY_USER" || true

echo "== 5. Configuring UFW (allow only SSH, HTTP, HTTPS) =="
if confirm "Enable UFW and allow only OpenSSH, 80/tcp, and 443/tcp? (existing custom rules are preserved, but review before confirming on a remote session)"; then
  apt-get install -y ufw
  ufw allow OpenSSH
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable
  ufw status verbose
else
  echo "Skipped UFW configuration. Configure firewall rules manually before exposing this host."
fi

mkdir -p /opt/veritech-scan/backups
chown -R "$DEPLOY_USER":"$DEPLOY_USER" /opt/veritech-scan || true

cat <<'EOF'

== Bootstrap complete ==

Next manual steps:

1. Log out and back in as the deploy user (or run `newgrp docker`) so the
   docker group membership takes effect.

2. Clone the private repository:
     git clone git@github.com:<your-org>/veritech-scan.git /opt/veritech-scan/app

3. SSH hardening (apply yourself, after confirming your current session
   still works — do NOT do this over the only session you have open):
     - Ensure your SSH public key is in ~/.ssh/authorized_keys for the
       deploy user and that you can log in with it.
     - In /etc/ssh/sshd_config, set:
         PasswordAuthentication no
         PermitRootLogin no
       Then: sudo systemctl restart ssh
     - Test a NEW connection in a separate terminal before closing your
       current session, to avoid locking yourself out.

4. Continue with docs/oracle-deployment.md for `.env.production`
   configuration, building images, running migrations, and DNS cutover.

EOF
