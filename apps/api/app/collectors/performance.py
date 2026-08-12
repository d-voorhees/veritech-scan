"""Collector 7: performance adapter.

`PerformanceProvider` is the seam for adding paid/external performance APIs
later without touching the orchestrator. The local provider always runs and
never depends on external services; Google PageSpeed Insights is optional
and skipped gracefully when unconfigured.
"""

import abc
import uuid
from datetime import datetime, timezone

import httpx

from app.config import get_settings
from app.models.evidence import EvidenceItem
from app.models.observation import PerformanceObservation


class PerformanceProvider(abc.ABC):
    name: str

    @abc.abstractmethod
    def collect(self, final_url: str, context: dict) -> dict:
        """Returns a dict of PerformanceObservation-shaped fields."""


class LocalPerformanceProvider(PerformanceProvider):
    name = "local"

    def collect(self, final_url: str, context: dict) -> dict:
        return {
            "provider": "local",
            "configured": True,
            "response_duration_ms": context.get("response_duration_ms"),
            "html_bytes": context.get("html_bytes"),
            "third_party_domain_count": context.get("third_party_domain_count"),
            "js_resource_count": context.get("js_resource_count"),
        }


class GooglePageSpeedProvider(PerformanceProvider):
    name = "google_pagespeed"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def collect(self, final_url: str, context: dict) -> dict:
        params = {
            "url": final_url,
            "key": self.api_key,
            "strategy": "mobile",
            "category": ["PERFORMANCE", "ACCESSIBILITY", "BEST_PRACTICES", "SEO"],
        }
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    "https://www.googleapis.com/pagespeedonline/v5/runPagespeed", params=params
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            return {"provider": "google_pagespeed", "configured": True, "error": str(exc)}

        lighthouse = data.get("lighthouseResult", {})
        categories = lighthouse.get("categories", {})
        audits = lighthouse.get("audits", {})

        def score(cat_key: str) -> int | None:
            cat = categories.get(cat_key)
            if not cat or cat.get("score") is None:
                return None
            return round(cat["score"] * 100)

        def metric(audit_key: str) -> float | None:
            audit = audits.get(audit_key)
            if not audit:
                return None
            return audit.get("numericValue")

        return {
            "provider": "google_pagespeed",
            "configured": True,
            "lcp_ms": metric("largest-contentful-paint"),
            "cls": metric("cumulative-layout-shift"),
            "inp_ms": metric("interaction-to-next-paint"),
            "fcp_ms": metric("first-contentful-paint"),
            "ttfb_ms": metric("server-response-time"),
            "performance_score": score("performance"),
            "accessibility_score": score("accessibility"),
            "best_practices_score": score("best-practices"),
            "seo_score": score("seo"),
        }


def run_performance_checks(db, scan_request_id: uuid.UUID, final_url: str, context: dict) -> dict:
    settings = get_settings()
    providers: list[PerformanceProvider] = [LocalPerformanceProvider()]
    if settings.google_pagespeed_api_key:
        providers.append(GooglePageSpeedProvider(settings.google_pagespeed_api_key))

    results = []
    for provider in providers:
        data = provider.collect(final_url, context)
        results.append(data)

    merged: dict = {}
    for r in results:
        merged.update({k: v for k, v in r.items() if v is not None})

    observation = PerformanceObservation(
        scan_request_id=scan_request_id,
        provider="+".join(p.name for p in providers),
        configured=any(p.name == "google_pagespeed" for p in providers),
        response_duration_ms=merged.get("response_duration_ms"),
        html_bytes=merged.get("html_bytes"),
        third_party_domain_count=merged.get("third_party_domain_count"),
        js_resource_count=merged.get("js_resource_count"),
        lcp_ms=merged.get("lcp_ms"),
        cls=merged.get("cls"),
        inp_ms=merged.get("inp_ms"),
        fcp_ms=merged.get("fcp_ms"),
        ttfb_ms=merged.get("ttfb_ms"),
        performance_score=merged.get("performance_score"),
        accessibility_score=merged.get("accessibility_score"),
        best_practices_score=merged.get("best_practices_score"),
        seo_score=merged.get("seo_score"),
    )
    db.add(observation)
    db.flush()

    pagespeed_configured = any(p.name == "google_pagespeed" for p in providers)
    summary = (
        "Local performance measurements recorded. "
        + (
            f"Google PageSpeed Insights performance score: {merged.get('performance_score')}."
            if pagespeed_configured and merged.get("performance_score") is not None
            else "Google PageSpeed Insights was not configured for this scan; only local measurements are available."
        )
    )

    evidence = EvidenceItem(
        scan_request_id=scan_request_id,
        category="performance",
        source_type="performance_measurement",
        source_url_or_identifier=final_url,
        captured_at=datetime.now(timezone.utc),
        confidence="high",
        normalized_payload_json=merged,
        human_readable_summary=summary,
        raw_response_reference=None,
    )
    db.add(evidence)
    db.flush()

    merged["performance_configured"] = pagespeed_configured
    return merged
