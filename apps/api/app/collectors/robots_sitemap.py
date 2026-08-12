"""Collector 2: robots.txt and sitemap discovery.

Purely observational — this collector never crawls more than the user's
selected max page count, and it does not implement (or claim to implement)
full robots.txt enforcement. See docs/threat-model.md.
"""

import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit

import httpx

from app.collectors.user_agent import USER_AGENT
from app.config import get_settings
from app.models.evidence import EvidenceItem

SAMPLE_URL_LIMIT = 10


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _fetch(client: httpx.Client, url: str) -> tuple[int | None, str | None, str | None]:
    """Returns (status_code, text, error_message)."""
    try:
        resp = client.get(url)
        return resp.status_code, resp.text, None
    except httpx.HTTPError as exc:
        return None, None, str(exc)


def _parse_sitemap_xml(xml_text: str) -> tuple[str, list[str], list[str]]:
    """Returns (kind, urls, parse_errors) where kind is 'urlset', 'sitemapindex', or 'unknown'."""
    urls: list[str] = []
    errors: list[str] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        return "unknown", [], [f"XML parse error: {exc}"]

    kind = _strip_ns(root.tag)
    for child in root:
        if _strip_ns(child.tag) not in ("url", "sitemap"):
            continue
        loc_el = next((c for c in child if _strip_ns(c.tag) == "loc"), None)
        if loc_el is not None and loc_el.text:
            urls.append(loc_el.text.strip())
        else:
            errors.append(f"Entry missing <loc> under <{_strip_ns(child.tag)}>")

    return kind, urls, errors


def run_robots_and_sitemap_checks(db, scan_request_id: uuid.UUID, canonical_url: str, max_pages: int) -> dict:
    settings = get_settings()
    parts = urlsplit(canonical_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    robots_url = urljoin(origin + "/", "robots.txt")

    summary: dict = {
        "robots_status_code": None,
        "robots_retrieval_error": None,
        "sitemap_urls_declared": [],
        "sitemap_count": 0,
        "discovered_url_count": 0,
        "sample_urls": [],
        "parsing_errors": [],
        "retrieval_errors": [],
    }

    with httpx.Client(
        timeout=settings.scan_page_timeout_seconds,
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as client:
        status_code, robots_text, error = _fetch(client, robots_url)
        summary["robots_status_code"] = status_code
        summary["robots_retrieval_error"] = error

        declared_sitemaps: list[str] = []
        if robots_text:
            for line in robots_text.splitlines():
                line = line.strip()
                if line.lower().startswith("sitemap:"):
                    declared_sitemaps.append(line.split(":", 1)[1].strip())
        summary["sitemap_urls_declared"] = declared_sitemaps

        robots_evidence = EvidenceItem(
            scan_request_id=scan_request_id,
            category="robots_sitemap",
            source_type="robots_txt",
            source_url_or_identifier=robots_url,
            captured_at=datetime.now(timezone.utc),
            confidence="high",
            normalized_payload_json={
                "status_code": status_code,
                "declared_sitemaps": declared_sitemaps,
                "retrieval_error": error,
                "body_excerpt": (robots_text or "")[:4000],
            },
            human_readable_summary=(
                f"robots.txt retrieval returned {status_code}."
                if status_code
                else f"robots.txt retrieval failed: {error}"
            )
            + f" Declared {len(declared_sitemaps)} sitemap URL(s). "
            "Recorded as evidence only — this scan does not implement full robots.txt enforcement.",
            raw_response_reference=None,
        )
        db.add(robots_evidence)

        sitemap_candidates = list(declared_sitemaps)
        if not sitemap_candidates:
            sitemap_candidates.append(urljoin(origin + "/", "sitemap.xml"))

        discovered_urls: list[str] = []
        parsing_errors: list[str] = []
        retrieval_errors: list[str] = []
        sitemap_count = 0

        for sitemap_url in sitemap_candidates[:5]:
            status_code, xml_text, error = _fetch(client, sitemap_url)
            if error or not xml_text or (status_code and status_code >= 400):
                retrieval_errors.append(f"{sitemap_url}: {error or f'HTTP {status_code}'}")
                continue

            sitemap_count += 1
            kind, urls, errors = _parse_sitemap_xml(xml_text)
            parsing_errors.extend(f"{sitemap_url}: {e}" for e in errors)

            if kind == "sitemapindex":
                # Follow up to 3 child sitemaps to keep this bounded.
                for child_sitemap_url in urls[:3]:
                    c_status, c_xml, c_error = _fetch(client, child_sitemap_url)
                    if c_error or not c_xml:
                        retrieval_errors.append(f"{child_sitemap_url}: {c_error or f'HTTP {c_status}'}")
                        continue
                    sitemap_count += 1
                    _, child_urls, child_errors = _parse_sitemap_xml(c_xml)
                    parsing_errors.extend(f"{child_sitemap_url}: {e}" for e in child_errors)
                    discovered_urls.extend(child_urls)
            else:
                discovered_urls.extend(urls)

            if len(discovered_urls) >= max_pages * 5:
                break

        summary["sitemap_count"] = sitemap_count
        summary["discovered_url_count"] = len(discovered_urls)
        summary["sample_urls"] = discovered_urls[:SAMPLE_URL_LIMIT]
        summary["parsing_errors"] = parsing_errors
        summary["retrieval_errors"] = retrieval_errors

        sitemap_evidence = EvidenceItem(
            scan_request_id=scan_request_id,
            category="robots_sitemap",
            source_type="sitemap_xml",
            source_url_or_identifier=", ".join(sitemap_candidates[:5]) or "none",
            captured_at=datetime.now(timezone.utc),
            confidence="high" if sitemap_count else "medium",
            normalized_payload_json={
                "sitemap_count": sitemap_count,
                "discovered_url_count": len(discovered_urls),
                "sample_urls": discovered_urls[:SAMPLE_URL_LIMIT],
                "parsing_errors": parsing_errors,
                "retrieval_errors": retrieval_errors,
            },
            human_readable_summary=(
                f"Found {sitemap_count} sitemap file(s) declaring {len(discovered_urls)} URL(s)."
                if sitemap_count
                else "No sitemap could be retrieved from robots.txt or the /sitemap.xml fallback."
            ),
            raw_response_reference=None,
        )
        db.add(sitemap_evidence)
        db.flush()

    return summary
