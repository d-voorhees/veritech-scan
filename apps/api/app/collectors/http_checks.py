"""Collector 1: HTTP and redirect checks.

Fetches the canonical target URL, manually following redirects (never
delegating to httpx's auto-follow) so every hop can be revalidated against
the SSRF boundary before it is requested.
"""

import time
import uuid
from datetime import datetime, timezone

import httpx

from app.collectors.user_agent import USER_AGENT
from app.config import get_settings
from app.core.url_safety import UnsafeTargetError, revalidate_redirect_url
from app.models.evidence import EvidenceItem
from app.models.observation import HTTPObservation

MAX_REDIRECTS = 10

SECURITY_HEADER_FIELDS = {
    "strict-transport-security": "strict_transport_security",
    "content-security-policy": "content_security_policy",
    "x-content-type-options": "x_content_type_options",
    "x-frame-options": "x_frame_options",
    "referrer-policy": "referrer_policy",
    "permissions-policy": "permissions_policy",
}


def fetch_with_redirect_revalidation(start_url: str, timeout_seconds: float) -> dict:
    redirect_chain: list[dict] = []
    current_url = start_url
    start_time = time.monotonic()

    with httpx.Client(
        follow_redirects=False,
        timeout=timeout_seconds,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            # Every hop — including the first — is revalidated against the
            # SSRF boundary immediately before it is requested.
            revalidate_redirect_url(current_url)
            response = client.get(current_url)

            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    break
                next_url = str(httpx.URL(current_url).join(location))
                redirect_chain.append(
                    {"from_url": current_url, "status_code": response.status_code, "to_url": next_url}
                )
                current_url = next_url
                continue

            duration_ms = int((time.monotonic() - start_time) * 1000)
            content_type = response.headers.get("content-type", "")
            return {
                "final_url": str(response.url),
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "redirect_chain": redirect_chain,
                "response_duration_ms": duration_ms,
                "content_type": response.headers.get("content-type"),
                "body_bytes": len(response.content),
                "html_text": response.text if "text/html" in content_type else None,
            }

    raise UnsafeTargetError(f"Too many redirects (> {MAX_REDIRECTS}) while fetching {start_url}.")


def run_http_checks(db, scan_request_id: uuid.UUID, canonical_url: str) -> dict:
    settings = get_settings()
    result = fetch_with_redirect_revalidation(canonical_url, settings.scan_page_timeout_seconds)

    headers_lower = {k.lower(): v for k, v in result["headers"].items()}
    is_https = result["final_url"].startswith("https://")

    observation = HTTPObservation(
        scan_request_id=scan_request_id,
        url=canonical_url,
        final_url=result["final_url"],
        status_code=result["status_code"],
        redirect_chain=result["redirect_chain"],
        headers=result["headers"],
        content_type=result["content_type"],
        cache_control=headers_lower.get("cache-control"),
        server_header=headers_lower.get("server"),
        response_duration_ms=result["response_duration_ms"],
        is_https=is_https,
        **{
            field: headers_lower.get(header)
            for header, field in SECURITY_HEADER_FIELDS.items()
        },
    )
    db.add(observation)
    db.flush()

    summary_lines = [f"{result['status_code']} response from {result['final_url']} in {result['response_duration_ms']}ms."]
    if result["redirect_chain"]:
        summary_lines.append(f"Followed {len(result['redirect_chain'])} redirect(s) to reach the final URL.")
    present_security_headers = [h for h in SECURITY_HEADER_FIELDS if h in headers_lower]
    missing_security_headers = [h for h in SECURITY_HEADER_FIELDS if h not in headers_lower]
    summary_lines.append(
        f"Security headers present: {', '.join(present_security_headers) or 'none'}. "
        f"Missing: {', '.join(missing_security_headers) or 'none'}."
    )

    evidence = EvidenceItem(
        scan_request_id=scan_request_id,
        category="http",
        source_type="http_response",
        source_url_or_identifier=result["final_url"],
        captured_at=datetime.now(timezone.utc),
        confidence="high",
        normalized_payload_json={
            "status_code": result["status_code"],
            "final_url": result["final_url"],
            "redirect_chain": result["redirect_chain"],
            "headers": result["headers"],
            "is_https": is_https,
            "response_duration_ms": result["response_duration_ms"],
        },
        human_readable_summary=" ".join(summary_lines),
        raw_response_reference=None,
    )
    db.add(evidence)
    db.flush()

    return {
        "observation_id": observation.id,
        "evidence_id": evidence.id,
        "final_url": result["final_url"],
        "is_https": is_https,
        "status_code": result["status_code"],
        "html_bytes": result["body_bytes"],
        "response_duration_ms": result["response_duration_ms"],
        "html_text": result["html_text"],
        "headers": result["headers"],
    }
