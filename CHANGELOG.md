# Changelog

All notable changes to this project are documented in this file.

## v2 — 2026-08-13

### Added

- **Report generation timing.** The scan detail page's "Collection tasks"
  card now shows how long each task took to run, plus a "Total report
  generation time" row once the scan finishes. No backend changes were
  needed — `ScanJob.started_at`/`finished_at` were already recorded and
  returned by the API; this just surfaces them. New `formatDuration()`
  helper in `apps/web/src/lib/utils.ts`.

### Fixed

- **Collection tasks card described a stale, smaller rule catalog.** The
  per-task descriptions and count (`(4 of 13 checks)`, etc.) were written
  when the rules engine had 13 rules; it has since grown to 24
  (`RULE_CATALOG` in `rules/definitions.py`) and several tasks now feed
  checks their label never mentioned — `robots_sitemap` also drives the
  xmlrpc.php/wp-json exposure checks, `dns_email_posture` also drives
  domain-registration expiry, `browser_render` also drives three
  accessibility checks plus mixed-content detection, `http_checks` also
  drives TLS certificate expiry, and `technology_detection` (previously
  labeled purely informational) drives the no-analytics-detected check.
  Rewrote each task's description in `TASK_AREA_MAP`
  (`apps/web/src/app/scans/[scanId]/page.tsx`) to list what it actually
  feeds, and dropped the "(N of 13 checks)" counts — the live "Rules
  engine coverage" table below already shows the real, current total, so
  a second, hardcoded count in the task list served no purpose and would
  only go stale again. Corrected the matching "13 rules"/"all 13 rules"
  references in `README.md` to 24.

## v1 — 2026-08-12

### Added

- **Rules engine coverage in every report.** The report previously only
  listed rules that fired — a rule that checked cleanly left no trace, so
  there was no way to see that the deterministic engine actually ran all
  13 rules. Added a static `RULE_CATALOG` (`rules/definitions.py`)
  describing what each rule checks, cross-referenced against a scan's
  actual findings in `report_builder._build_rules_checked()`. Every
  report now shows a "Rules engine coverage" table (HTML export and
  dashboard): all 13 rules, what each one checks, and its outcome — fired
  with severity, or "No finding raised." Also added the DKIM rule's first
  test coverage (`tests/backend/test_rules_engine.py`), which had none.
- **Crawl cross-checked against robots.txt and sitemap.** "Crawl and
  indexability" now reports three things the previous version never
  compared: pages the crawl reached that aren't declared in the sitemap,
  sitemap URLs that weren't reached within the scan's page budget, and
  (informational only, since this scan has never enforced robots.txt)
  pages reached despite matching a `Disallow` rule for `User-agent: *`.
  `robots_sitemap.py` now parses robots.txt Disallow rules and retains the
  full sitemap URL list (previously capped at a 10-URL sample); the
  comparison itself is new in `report_builder._build_sitemap_check`.
- **DKIM discovery.** `dns_checks.py` probes 16 common ESP-default
  selectors (Google Workspace, Microsoft 365, Mailchimp, SendGrid, etc.)
  against `<selector>._domainkey.<domain>` and surfaces any hits in the DNS
  and email posture table plus a new informational
  `dkim_selector_found` rule. A miss is reported as "not proof of
  absence" rather than a false negative, since DKIM — unlike SPF/DMARC —
  has no fixed, well-known record location. Adds `dkim_selector` to
  `dns_observations` (migration `20fcb897e807`).
- **Third-party dependency listing.** The "Third-party dependencies"
  section (previously just a bare count buried in Performance) now lists
  every hostname observed while rendering the homepage, with request
  count, category, and — for ~35 well-known vendors including Meta Pixel,
  Google Analytics/Tag Manager, Stripe, HubSpot, and Intercom — a friendly
  vendor name (`dependency_classification.py`), in both the HTML export
  and the dashboard.
- **Desktop and mobile PageSpeed Insights scores.** The performance
  section, renamed **"Page speed performance,"** now fetches both
  `strategy=desktop` and `strategy=mobile` runs from PageSpeed Insights
  instead of only mobile, and reports Performance/Accessibility/Best
  Practices/SEO scores plus Core Web Vitals for each side by side.
  `PerformanceObservation` gained `desktop_*`/`mobile_*` columns replacing
  the old unprefixed (silently mobile-only) ones (migration
  `a00440335fda`). Lighthouse's new experimental "Agentic Browsing"
  category was investigated and left out for now — confirmed against
  Google's PSI API reference that it isn't exposed by the hosted API yet.
- **CI/CD: push-to-deploy on `main`.** `.github/workflows/deploy.yml` runs
  the full backend (ruff/mypy/pytest) and frontend (eslint/tsc/tests) suite
  on every push to `main`, then — only if that passes — runs
  `flyctl deploy --remote-only`, then `./scripts/migrate-fly.sh` against the
  image just deployed. Migrations are no longer a manual post-deploy step
  in the normal push-to-main flow; `make fly-migrate` remains available for
  out-of-band deploys (e.g. a manual `make fly-deploy`).
- **Public marketing homepage and brand styling.** `/` now renders a
  Veritech Diligence-branded landing page (hero, product explanation, check
  categories, access section) with "Sign in" and "Request access" calls to
  action; the authenticated dashboard moved to `/dashboard`. The login page
  and dashboard were restyled to match veritechdiligence.com's type and
  color system (Inter / JetBrains Mono / Linden Hill, ink/paper/parchment/
  navy palette, sharp corners).

### Changed

- **Docs brought back in sync with the code.** README (rule count 12→13,
  DNS posture description now includes DKIM, non-goals list no longer
  claims DKIM is out of scope, known-limitations wording rewritten to
  match the actual DKIM/robots.txt behavior, test-coverage claim now
  accurate), `docs/threat-model.md` (removed the stale "DKIM discovery is
  a non-goal" bullet, updated the robots.txt non-goal to describe the new
  sitemap/Disallow cross-check), and `docs/rules-engine.md` (added
  `dkim_selector_found` to the rules table, documented `RULE_CATALOG`) —
  all previously described a pre-DKIM, pre-sitemap-cross-check, 12-rule
  version of the product.
- **Landing page technology-stack row.** The "What it checks" table's
  Technology stack description now lists the specific categories detected
  (CMS/website-builder, e-commerce, frontend frameworks, analytics/tag
  managers, advertising/email marketing, support/chat, payments,
  CDN/hosting, fonts/JS libraries, consent management, forms/scheduling,
  search, captcha, embedded video/maps) instead of a one-line summary.
- **Known-limitations text.** Removed the "Google PageSpeed Insights
  metrics are only present when configured" line; rewrote the DKIM line
  to describe the new best-effort selector-probing scope instead of
  claiming DKIM isn't assessed at all; rewrote the robots.txt line to
  describe the new sitemap/Disallow cross-check instead of just stating
  robots.txt isn't enforced.
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
- **Collection tasks list didn't map to the 13 checks it feeds.** The
  "Collection tasks" card on the scan detail page listed raw pipeline
  stage names (`http_checks`, `dns_email_posture`, ...) with no visible
  link to what they actually investigate, which read as inconsistent with
  the "Rules engine coverage" table's 13 checks below it. Each task now
  shows a one-line description of the check category and count it feeds
  (e.g. "Email deliverability — SPF, DMARC, DKIM (4 of 13 checks)"),
  sourced from the same `RULE_CATALOG` the rules-coverage table reads.

### Fixed

- **Crawl/indexability double-counted trailing-slash URL variants.**
  `/privacy` and `/privacy/` were treated as separate pages when both
  spellings were discovered while crawling, double-counting the same
  page. The crawler (`crawler.py`) now dedupes against a trailing-slash-
  normalized key while still fetching and recording whichever URL variant
  was first discovered.
- **False-positive WooCommerce detection.** The detector matched the bare
  substring "woocommerce" anywhere in a page's HTML, so pages that merely
  *mention* WooCommerce in marketing copy (e.g. describing it as a
  service the business supports) were flagged as running it. Now requires
  actual WooCommerce fingerprints — plugin asset paths, the
  `woocommerce_params` JS object, WooCommerce CSS classes, or the
  `wc-ajax=` endpoint (`technology.py`).
- **Technology tables in the HTML export had inconsistent column
  widths.** Each technology category (analytics, cdn security, marketing,
  ...) rendered as its own `<table>` with browser-computed auto layout,
  so columns didn't line up between categories. Gave them a shared
  `.tech-table` class with fixed 30/50/20% column widths.
- `apps/api/.env` and `apps/web/.env` symlinks to the repo-root `.env`.
  Pydantic-settings (`apps/api/app/config.py`) and Next.js both resolve
  `.env` relative to their own working directory, but `make migrate`,
  `make seed`, and `make dev` all `cd` into `apps/api`/`apps/web` before
  running. Without the symlinks, the root `.env` was silently ignored and
  commands fell back to `config.py`'s hardcoded defaults — including a
  `postgres` hostname that only resolves inside Docker — causing
  `make migrate` to fail with `nodename nor servname provided, or not
  known` even when a correctly filled-out root `.env` was present.
- **Crawl stopped after 1 page whenever the site redirected between apex
  and `www`.** `hostname` comparisons in the crawler and crawl policy used
  strict string equality, so a target entered as `example.com` that
  redirects to `www.example.com` (or vice versa) tripped the
  off-origin-redirect guard on the very first request: the homepage body
  was never fetched, no links were discovered, and the crawl ended having
  fetched exactly 1 page regardless of the selected page budget (10/25/50).
  Added `is_same_origin_hostname()` (`crawl_policy.py`), which treats
  `www.` and the bare apex domain as the same origin, and applied it to
  the redirect-follow check and internal-link classification in
  `crawler.py` in addition to `is_crawlable_url`.
- **Third-party dependency count inflated by the same www/apex mismatch.**
  `browser_render.py`'s third-party classification still compared hostnames
  with strict string equality, so a same-site request served from `www.`
  (when the scan target was the bare apex, or vice versa) was miscounted
  as a third-party dependency — inflating that count and risking a false
  `excessive_third_party_domains` finding. Now reuses the same
  `is_same_origin_hostname()` helper.
- **Technology detection missed real, positively-identified stacks (e.g.
  WordPress/WooCommerce sites behind a CDN or bot-challenge page).**
  Detection only ever scanned the raw pre-JS HTTP response
  (`http_checks`'s `html_text`), which optimizers like Cloudflare Rocket
  Loader (which defers/rewrites `<script>` tags) or a JS-gated
  bot-protection challenge can strip of every fingerprint before a real
  browser ever executes anything. `browser_render.py` now captures the
  fully rendered DOM (`page.content()`) and `technology.py`'s
  `run_technology_detection` scans it — plus a robots.txt excerpt, which
  often reveals platform-specific paths (e.g. `Disallow: /wp-admin/`) even
  when the page itself doesn't — alongside the raw response. Combining
  sources only widens what can be found; each rule still fires at most
  once regardless of how many needles match.
- **Desktop PageSpeed Insights scores were silently blank while mobile
  populated.** `GooglePageSpeedProvider`'s hardcoded 30-second httpx
  timeout was too short for PSI's real-world response times (commonly
  30-60s+, especially on a cold cache), so the desktop `runPagespeed` call
  would time out and fail with no error surfaced anywhere — not in the UI,
  not in logs. Raised the timeout to 90s and added one retry with backoff
  (`performance.py`).
- **Report page showed misleading "clean" results before a scan had
  actually finished collecting evidence** — e.g. "No finding raised" on
  every rule, empty technology/dependency lists — indistinguishable from a
  genuinely clean scan. The dashboard polls `/report` continuously while a
  scan runs, but findings only exist once the `rules_engine` job (the
  last pipeline step) completes, so every section rendered its normal
  "nothing here" state regardless of whether the underlying collection
  task had even started. The scan detail page now checks each section's
  job status and shows a "Pending — hasn't finished collecting yet" state
  instead; the rules-coverage table also now says "OK" rather than "No
  finding raised" for a rule that genuinely ran clean, reserving "Pending"
  for checks that haven't run yet.
