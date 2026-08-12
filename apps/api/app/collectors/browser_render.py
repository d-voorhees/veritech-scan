"""Collector 5: browser rendering and third-party dependency inventory.

Homepage only, one ephemeral browser context per scan. Never submits forms,
authenticates, retains cookies beyond the context's lifetime, or stores
request bodies / user data. See docs/threat-model.md.
"""

import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from app.collectors.dependency_classification import classify_hostname
from app.collectors.user_agent import USER_AGENT
from app.config import get_settings
from app.models.evidence import EvidenceItem
from app.models.observation import ThirdPartyDependency
from app.services.artifact_storage import get_artifact_storage


def run_browser_render(
    db, scan_request_id: uuid.UUID, canonical_url: str, hostname: str, route_handler=None
) -> dict:
    """`route_handler`, when provided, is registered via `page.route("**/*", ...)`
    before navigation. Production callers never pass it; tests use it to
    render a fully offline fixture page through the real Chromium engine.
    """
    settings = get_settings()
    console_errors: list[str] = []
    requests_seen: list[dict] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        # Ephemeral context: no storage_state loaded or saved, discarded at
        # the end of this scan step. Cookies set during the visit exist only
        # for the lifetime of this context.
        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 900},
            ignore_https_errors=False,
        )
        page = context.new_page()
        page.set_default_timeout(settings.scan_page_timeout_seconds * 1000)

        if route_handler is not None:
            page.route("**/*", route_handler)

        page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
        page.on(
            "request",
            lambda req: requests_seen.append({"url": req.url, "resource_type": req.resource_type}),
        )

        fetch_error = None
        final_title = None
        final_url = canonical_url
        screenshot_bytes = None
        try:
            page.goto(canonical_url, wait_until="networkidle")
            final_url = page.url
            final_title = page.title()
            screenshot_bytes = page.screenshot(full_page=False)
        except PlaywrightError as exc:
            fetch_error = str(exc)

        context.close()
        browser.close()

    client_side_redirect = final_url != canonical_url

    js_resource_count = sum(1 for r in requests_seen if r["resource_type"] == "script")
    request_hostnames: dict[str, int] = {}
    for r in requests_seen:
        h = urlsplit(r["url"]).hostname
        if h:
            request_hostnames[h] = request_hostnames.get(h, 0) + 1

    third_party_hosts = {h: count for h, count in request_hostnames.items() if h != hostname}

    screenshot_reference = None
    if screenshot_bytes:
        storage = get_artifact_storage()
        screenshot_reference = storage.save(
            f"{scan_request_id}/homepage-screenshot.png", screenshot_bytes
        )

    for host, count in third_party_hosts.items():
        category, method = classify_hostname(host)
        db.add(
            ThirdPartyDependency(
                scan_request_id=scan_request_id,
                hostname=host,
                category=category,
                request_count=count,
                classification_method=method,
            )
        )

    evidence = EvidenceItem(
        scan_request_id=scan_request_id,
        category="browser_render",
        source_type="playwright_render",
        source_url_or_identifier=canonical_url,
        captured_at=datetime.now(timezone.utc),
        confidence="high" if not fetch_error else "low",
        normalized_payload_json={
            "final_url": final_url,
            "final_title": final_title,
            "client_side_redirect": client_side_redirect,
            "console_error_count": len(console_errors),
            "console_errors": console_errors[:20],
            "js_resource_count": js_resource_count,
            "third_party_domain_count": len(third_party_hosts),
            "third_party_domains": third_party_hosts,
            "screenshot_reference": screenshot_reference,
            "fetch_error": fetch_error,
        },
        human_readable_summary=(
            f"Rendered homepage in an ephemeral browser context; observed {len(third_party_hosts)} "
            f"third-party request domain(s) and {len(console_errors)} JavaScript console error(s)."
            if not fetch_error
            else f"Browser rendering failed: {fetch_error}"
        ),
        raw_response_reference=screenshot_reference,
    )
    db.add(evidence)
    db.flush()

    return {
        "final_url": final_url,
        "final_title": final_title,
        "client_side_redirect": client_side_redirect,
        "js_resource_count": js_resource_count,
        "third_party_domain_count": len(third_party_hosts),
        "screenshot_reference": screenshot_reference,
        "fetch_error": fetch_error,
        "evidence_id": evidence.id,
    }
