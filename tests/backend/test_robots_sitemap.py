import respx
from httpx import Response

from app.collectors.robots_sitemap import run_robots_and_sitemap_checks
from app.models.evidence import EvidenceItem


@respx.mock
def test_exposure_probes_recorded_as_evidence(db, scan_request):
    respx.get("https://example.com/robots.txt").mock(return_value=Response(404))
    respx.get("https://example.com/sitemap.xml").mock(return_value=Response(404))
    respx.get("https://example.com/xmlrpc.php").mock(
        return_value=Response(405, text="XML-RPC server accepts POST requests only.")
    )
    respx.get("https://example.com/wp-json/").mock(
        return_value=Response(200, json={"name": "Example", "namespaces": ["wp/v2"]})
    )

    summary = run_robots_and_sitemap_checks(db, scan_request.id, "https://example.com/", max_pages=10)

    assert summary["exposure_checks"]["xmlrpc"]["status_code"] == 405
    assert summary["exposure_checks"]["wp_json"]["status_code"] == 200

    evidence = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.scan_request_id == scan_request.id, EvidenceItem.category == "exposure")
        .first()
    )
    assert evidence is not None
    assert "namespaces" in evidence.normalized_payload_json["wp_json"]["body_excerpt"]


@respx.mock
def test_robots_body_excerpt_surfaced_for_technology_detection(db, scan_request):
    respx.get("https://example.com/robots.txt").mock(
        return_value=Response(200, text="User-agent: *\nDisallow: /wc-logs/\n")
    )
    respx.get("https://example.com/sitemap.xml").mock(return_value=Response(404))
    respx.get("https://example.com/xmlrpc.php").mock(return_value=Response(404))
    respx.get("https://example.com/wp-json/").mock(return_value=Response(404))

    summary = run_robots_and_sitemap_checks(db, scan_request.id, "https://example.com/", max_pages=10)

    assert "wc-logs" in summary["robots_body_excerpt"]
