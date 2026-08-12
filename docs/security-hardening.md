# Security hardening

This complements `docs/threat-model.md` (what the system defends against
and why) with concrete configuration and operational hardening — what's
already in place, and what to add before scaling past an MVP.

## Already in place

- **TLS everywhere in production.** Caddy automatically issues and renews
  Let's Encrypt certificates and terminates TLS; only Caddy has public
  ports (80/443). See `Caddyfile`.
- **Security headers** on every response via Caddy:
  `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, and the
  `Server` header is stripped.
- **Conservative request body limit** (5MB) at the proxy layer — this app
  never accepts file uploads.
- **Non-root containers.** `api`, `worker`, and `web` all run as a
  dedicated unprivileged user (`appuser` / `appgroup`), not root — see each
  `Dockerfile`.
- **No unnecessary public surface.** `postgres`, `redis`, and `worker` are
  never published to the host in `docker-compose.prod.yml`; only `caddy`
  binds 80/443.
- **Password hashing** via `bcrypt` (`app/security/passwords.py`), never
  plaintext or reversible encryption.
- **JWT sessions** delivered as `httponly`, `samesite=lax` cookies
  (`secure=true` in production — `app/api/v1/auth.py`), not exposed to
  client-side JavaScript.
- **Ownership checks on every scan-scoped endpoint** — see
  `docs/threat-model.md`'s "User / data isolation" section.
- **Rate limiting on scan creation** to prevent the app being used as a
  bulk/anonymous scanning tool.
- **UFW configured to allow only SSH, HTTP, HTTPS** by `bootstrap-server.sh`.
- **Secrets never committed**: `.env`, `.env.production`, database dumps,
  screenshots, and report exports are all in `.gitignore`.

## Recommended before handling real client engagement data

1. **SSH hardening** — `bootstrap-server.sh` deliberately does not do this
   automatically (see that script's comments). After confirming key-based
   login works:
   - `PasswordAuthentication no` and `PermitRootLogin no` in
     `/etc/ssh/sshd_config`, then `systemctl restart ssh`.
   - Consider moving SSH off port 22 and/or adding `fail2ban`.
2. **Off-server encrypted backups** — see `docs/backup-and-recovery.md`.
   This is the single most important gap before real client data is stored
   here.
3. **Stronger authorization-attestation verification.** The MVP relies on a
   logged self-attestation checkbox. A meaningful next step is a
   domain-ownership challenge (DNS TXT record or well-known file, similar to
   ACME) before a scan against a new domain is allowed to proceed —
   especially if the invite-only boundary is ever loosened.
4. **Secrets management.** `.env.production` currently holds plaintext
   secrets on disk. For a larger deployment, move to a secrets manager
   (Oracle Vault, `sops`-encrypted files in git, etc.) rather than a bare
   `.env` file, and rotate `JWT_SECRET` / `POSTGRES_PASSWORD` on a schedule
   (see `docs/operations.md`'s "Rotating secrets").
5. **Dependency scanning.** Add `pip-audit` / `npm audit` (or Dependabot) to
   CI once CI exists — none is configured yet in this MVP.
6. **Structured audit logging of scan submissions.** `scan_events` already
   gives a per-scan timeline; consider a separate immutable audit log for
   "who submitted a scan against which domain and when" if this product
   needs to answer authorization disputes later.
7. **Multi-factor authentication** for admin accounts once the user base
   grows beyond a small invite list.
8. **Content-Security-Policy on the web app itself.** Caddy's headers cover
   the proxy layer; the Next.js app doesn't currently set its own CSP.
   Given the app has no third-party scripts and a small, known API surface,
   a strict CSP (`default-src 'self'`) is a reasonable low-risk addition —
   track this alongside the `missing_csp` rule this product itself flags on
   *scanned* sites (see `docs/rules-engine.md`) for consistency.
9. **Full `robots.txt` enforcement**, if the product's scope ever expands
   beyond "records robots.txt as evidence" — see the explicit non-goal in
   `docs/threat-model.md`.

## Reporting a vulnerability

This is an internal MVP without a public bug bounty. If you find a security
issue in this codebase, report it directly to the maintainers rather than
opening a public GitHub issue.
