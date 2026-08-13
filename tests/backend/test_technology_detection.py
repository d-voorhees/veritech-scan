from app.collectors.technology import run_technology_detection
from app.models.evidence import EvidenceItem


def _detected_names(db, scan_request, html_text, headers=None):
    run_technology_detection(db, scan_request.id, html_text, headers or {})
    db.flush()
    rows = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.scan_request_id == scan_request.id, EvidenceItem.category == "technology")
        .all()
    )
    return {row.normalized_payload_json["technology_name"] for row in rows}


def test_hubspot_does_not_fire_on_prose_mention(db, scan_request):
    # A page merely discussing HubSpot (e.g. "we review sites built on Shopify,
    # HubSpot, ...") must not be reported as actually running HubSpot.
    html = "<p>Our review covers Salesforce, HubSpot, Cloudinary, and SAML SSO patterns.</p>"
    assert "HubSpot" not in _detected_names(db, scan_request, html)


def test_hubspot_fires_on_real_embed():
    from app.collectors.technology import DETECTION_RULES

    detector = next(d for name, _, _, d in DETECTION_RULES if name == "HubSpot")
    assert detector('<script src="https://js.hs-scripts.com/12345.js"></script>', {}) is not None
    assert detector("<script>_hsq.push(['setPath', '/']);</script>", {}) is not None
    assert detector("<p>We use HubSpot for CRM.</p>", {}) is None
