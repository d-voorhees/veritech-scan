"""Collector 6: local, rules-based technology detection.

Every positive match is explainable — it cites the exact header, HTML
substring, or script pattern that triggered it — and gets its own evidence
item. No vendor API calls, no unsupported claims.
"""

import re
import uuid
from datetime import datetime, timezone

from app.models.evidence import EvidenceItem
from app.models.observation import TechnologyObservation

# Each rule: (technology_name, category, confidence, detector)
# detector(html, headers_lower) -> matched detection-method string, or None.


def _html_contains(html: str, *needles: str):
    def _detector(_html: str, _headers: dict) -> str | None:
        for needle in needles:
            if needle.lower() in _html.lower():
                return f'HTML contains "{needle}"'
        return None

    return _detector


def _header_contains(header_name: str, *needles: str):
    def _detector(_html: str, headers: dict) -> str | None:
        value = headers.get(header_name.lower(), "")
        for needle in needles:
            if needle.lower() in value.lower():
                return f'Response header {header_name} contains "{needle}"'
        return None

    return _detector


def _header_present(header_name: str):
    def _detector(_html: str, headers: dict) -> str | None:
        if header_name.lower() in headers:
            return f"Response header {header_name} is present"
        return None

    return _detector


def _regex(pattern: str, description: str):
    compiled = re.compile(pattern, re.IGNORECASE)

    def _detector(html: str, _headers: dict) -> str | None:
        if compiled.search(html or ""):
            return description
        return None

    return _detector


def _any_of(*detectors):
    def _detector(html: str, headers: dict) -> str | None:
        for d in detectors:
            result = d(html, headers)
            if result:
                return result
        return None

    return _detector


DETECTION_RULES = [
    ("WordPress", "cms", "high", _any_of(
        _html_contains("wp-content", "wp-includes"),
        _regex(r'name=["\']generator["\']\s+content=["\']WordPress', "meta generator tag references WordPress"),
    )),
    ("Shopify", "ecommerce_platform", "high", _any_of(
        _html_contains("cdn.shopify.com", "Shopify.theme"),
        _header_present("x-shopify-stage"),
    )),
    ("Webflow", "website_builder", "high", _any_of(
        _html_contains("webflow.com", "w-webflow-badge"),
        _regex(r'name=["\']generator["\']\s+content=["\']Webflow', "meta generator tag references Webflow"),
    )),
    ("Wix", "website_builder", "high", _any_of(
        _html_contains("wixstatic.com", "wix.com"),
        _regex(r'name=["\']generator["\']\s+content=["\']Wix', "meta generator tag references Wix"),
    )),
    ("Squarespace", "website_builder", "high", _html_contains("squarespace.com", "static1.squarespace.com")),
    ("Next.js", "frontend_framework", "high", _html_contains("/_next/static", "__NEXT_DATA__")),
    ("React", "frontend_framework", "medium", _html_contains("data-reactroot", "react-dom")),
    ("Vue", "frontend_framework", "medium", _regex(r"data-v-[0-9a-f]{6,}|__vue__", "Vue-style scoped attribute or runtime marker found")),
    ("Angular", "frontend_framework", "high", _regex(r"\bng-version=", "ng-version attribute found")),
    ("Google Analytics", "analytics", "high", _html_contains("google-analytics.com", "gtag(", "ga('create'")),
    ("Google Tag Manager", "tag_manager", "high", _html_contains("googletagmanager.com/gtm.js")),
    ("Cloudflare", "cdn_security", "medium", _any_of(
        _header_contains("server", "cloudflare"),
        _header_present("cf-ray"),
    )),
    ("Stripe", "payment", "high", _html_contains("js.stripe.com")),
    ("HubSpot", "marketing", "high", _html_contains("hs-scripts.com", "hubspot")),
    ("Intercom", "customer_support_chat", "high", _html_contains("widget.intercom.io", "Intercom(")),
    ("Segment", "analytics", "medium", _html_contains("cdn.segment.com")),
]


def run_technology_detection(db, scan_request_id: uuid.UUID, html_text: str | None, headers: dict) -> dict:
    html_text = html_text or ""
    headers_lower = {k.lower(): v for k, v in (headers or {}).items()}

    detected: list[dict] = []
    for name, category, confidence, detector in DETECTION_RULES:
        method = detector(html_text, headers_lower)
        if not method:
            continue

        evidence = EvidenceItem(
            scan_request_id=scan_request_id,
            category="technology",
            source_type="technology_detection",
            source_url_or_identifier=name,
            captured_at=datetime.now(timezone.utc),
            confidence=confidence,
            normalized_payload_json={"technology_name": name, "category": category, "detection_method": method},
            human_readable_summary=f"Detected {name} ({category}) via: {method}.",
            raw_response_reference=None,
        )
        db.add(evidence)
        db.flush()

        db.add(
            TechnologyObservation(
                scan_request_id=scan_request_id,
                technology_name=name,
                category=category,
                detection_method=method,
                confidence=confidence,
                evidence_item_id=evidence.id,
            )
        )
        detected.append({"technology_name": name, "category": category, "confidence": confidence})

    db.flush()
    return {"detected": detected, "count": len(detected)}
