"""Exercises the real Chromium render path end-to-end via Playwright route
interception (no real network) — a live counterpart to
test_worker_check.py's bare launch check.
"""

from app.collectors.browser_render import run_browser_render
from app.models.evidence import EvidenceItem
from app.models.observation import ThirdPartyDependency

FIXTURE_HTML = """
<html><head><title>Acme Example</title></head>
<body>
  <h1>Acme Example</h1>
  <script src="https://www.googletagmanager.com/gtag/js?id=G-TEST"></script>
  <script src="https://js.stripe.com/v3/"></script>
</body></html>
"""


def _offline_route_handler(route):
    url = route.request.url
    if url == "https://example.com/":
        route.fulfill(status=200, content_type="text/html", body=FIXTURE_HTML)
    elif "googletagmanager.com" in url or "js.stripe.com" in url:
        route.fulfill(status=200, content_type="application/javascript", body="// stub")
    else:
        route.abort()


def test_browser_render_captures_and_classifies_third_party_domains(db, scan_request):
    result = run_browser_render(
        db, scan_request.id, "https://example.com/", "example.com", route_handler=_offline_route_handler
    )

    assert result["fetch_error"] is None
    assert result["final_title"] == "Acme Example"
    assert result["js_resource_count"] >= 2

    deps = {d.hostname: d.category for d in db.query(ThirdPartyDependency).filter_by(scan_request_id=scan_request.id)}
    assert deps.get("www.googletagmanager.com") == "tag_manager"
    assert deps.get("js.stripe.com") == "payment"

    evidence = (
        db.query(EvidenceItem)
        .filter_by(scan_request_id=scan_request.id, category="browser_render")
        .first()
    )
    assert evidence is not None
    assert evidence.normalized_payload_json["third_party_domain_count"] >= 2


def test_run_browser_render_handles_navigation_failure_gracefully(db, scan_request):
    """A target that cannot be reached must produce a low-confidence
    evidence item rather than raising and crashing the scan.
    """

    def abort_everything(route):
        route.abort()

    result = run_browser_render(
        db, scan_request.id, "https://example.com/", "example.com", route_handler=abort_everything
    )
    assert result["fetch_error"] is not None

    deps = db.query(ThirdPartyDependency).filter_by(scan_request_id=scan_request.id).all()
    assert deps == []

    evidence = (
        db.query(EvidenceItem)
        .filter_by(scan_request_id=scan_request.id, category="browser_render")
        .first()
    )
    assert evidence.confidence == "low"
