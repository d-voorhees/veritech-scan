from datetime import datetime, timezone
from urllib.parse import urlsplit

from sqlalchemy.orm import Session, joinedload

from app.collectors.dependency_classification import known_vendor_name
from app.collectors.dns_checks import COMMON_DKIM_SELECTORS
from app.config import get_settings
from app.models.evidence import EvidenceItem
from app.models.finding import Finding, FindingEvidence
from app.models.observation import (
    DNSObservation,
    HTTPObservation,
    PerformanceObservation,
    TechnologyObservation,
    ThirdPartyDependency,
)
from app.models.page import Page
from app.models.scan import JOB_STATUS_FAILED, ScanJob, ScanRequest
from app.rules.definitions import RULE_CATALOG
from app.schemas.evidence import EvidenceItemOut, FindingOut
from app.schemas.report import FindingSeverityCounts, LimitationOut, ReportOut

SITEMAP_CROSS_CHECK_SAMPLE_LIMIT = 20


def _path_key(url: str) -> str:
    """Path identity for cross-referencing crawled pages against sitemap/robots
    URLs — same trailing-slash collapsing as the crawler's own dedupe key."""
    path = urlsplit(url).path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path


def _build_sitemap_check(
    pages: list[Page], robots_evidence: EvidenceItem | None, sitemap_evidence: EvidenceItem | None
) -> dict:
    """Cross-references the crawled page set against what robots.txt and the
    sitemap claim. All three collectors run independently, so this comparison
    only happens here, once all their evidence is available together."""
    disallow_rules: list[str] = (robots_evidence.normalized_payload_json.get("disallow_rules") if robots_evidence else None) or []
    sitemap_urls: list[str] = (sitemap_evidence.normalized_payload_json.get("discovered_urls") if sitemap_evidence else None) or []
    sitemap_file_count = (sitemap_evidence.normalized_payload_json.get("sitemap_count") if sitemap_evidence else None) or 0

    crawled_by_path = {
        _path_key(p.final_url or p.url): (p.final_url or p.url) for p in pages if p.status_code and p.status_code < 400
    }
    sitemap_by_path = {_path_key(u): u for u in sitemap_urls}

    crawled_not_in_sitemap = sorted(url for key, url in crawled_by_path.items() if key not in sitemap_by_path)
    sitemap_not_crawled = sorted(url for key, url in sitemap_by_path.items() if key not in crawled_by_path)
    crawled_but_disallowed = sorted(
        url for key, url in crawled_by_path.items() if any(rule and key.startswith(rule) for rule in disallow_rules)
    )

    return {
        "sitemap_declared_count": len(sitemap_urls),
        "sitemap_file_count": sitemap_file_count,
        "disallow_rule_count": len(disallow_rules),
        "disallow_rules": disallow_rules,
        "crawled_not_in_sitemap_count": len(crawled_not_in_sitemap),
        "crawled_not_in_sitemap_sample": crawled_not_in_sitemap[:SITEMAP_CROSS_CHECK_SAMPLE_LIMIT],
        "sitemap_not_crawled_count": len(sitemap_not_crawled),
        "sitemap_not_crawled_sample": sitemap_not_crawled[:SITEMAP_CROSS_CHECK_SAMPLE_LIMIT],
        "crawled_but_disallowed_count": len(crawled_but_disallowed),
        "crawled_but_disallowed_sample": crawled_but_disallowed[:SITEMAP_CROSS_CHECK_SAMPLE_LIMIT],
    }


def _build_rules_checked(findings: list[Finding]) -> dict:
    """Maps every rule in the static RULE_CATALOG against this scan's actual
    findings, so the report can show "N rules checked, M raised a finding"
    instead of only ever listing the rules that happened to fire."""
    fired_by_rule_key = {f.rule.rule_key: f for f in findings if f.rule}

    rules: list[dict] = []
    for rule_key, meta in RULE_CATALOG.items():
        finding = fired_by_rule_key.get(rule_key)
        rules.append(
            {
                "rule_key": rule_key,
                "category": meta["category"],
                "check": meta["check"],
                "fired": finding is not None,
                "severity": finding.severity if finding else None,
                "title": finding.title if finding else None,
                "finding_id": str(finding.id) if finding else None,
            }
        )

    return {
        "total_count": len(rules),
        "fired_count": sum(1 for r in rules if r["fired"]),
        "rules": rules,
    }


KNOWN_LIMITATIONS = [
    "This is a bounded, rate-limited public-web pre-screen, not a penetration test or "
    "vulnerability scan. Absence of a finding is not proof of absence of risk.",
    "The crawler does not enforce robots.txt while fetching pages. It separately cross-references "
    "the crawled page set against robots.txt Disallow rules for User-agent: * (plain prefix "
    "matching only — wildcard and end-anchor patterns are not evaluated) and against declared "
    "sitemap URLs, reported under Crawl and indexability.",
    f"DKIM discovery probes {len(COMMON_DKIM_SELECTORS)} common ESP-default selectors (Google Workspace, "
    "Microsoft 365, Mailchimp, SendGrid, etc.); a domain signing only with a custom selector will not be "
    "found, so a missing DKIM result is not proof of absence.",
    "The browser renderer inspects only the homepage, not the full crawled page set.",
]


def build_report(db: Session, scan: ScanRequest) -> ReportOut:
    settings = get_settings()

    severity_rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
    findings = (
        db.query(Finding)
        .options(
            joinedload(Finding.evidence_links).joinedload(FindingEvidence.evidence_item),
            joinedload(Finding.rule),
        )
        .filter(Finding.scan_request_id == scan.id)
        .all()
    )
    findings.sort(key=lambda f: (severity_rank.get(f.severity, 9), f.created_at))
    rules_checked = _build_rules_checked(findings)

    severity_counts = FindingSeverityCounts()
    finding_outs: list[FindingOut] = []
    for f in findings:
        evidence = [link.evidence_item for link in f.evidence_links]
        finding_outs.append(
            FindingOut(
                id=f.id,
                category=f.category,
                severity=f.severity,
                confidence=f.confidence,
                title=f.title,
                impact=f.impact,
                recommended_next_step=f.recommended_next_step,
                status=f.status,
                rule_version=f.rule_version,
                created_at=f.created_at,
                evidence=[EvidenceItemOut.model_validate(e) for e in evidence],
            )
        )
        if f.severity in severity_counts.model_fields:
            setattr(severity_counts, f.severity, getattr(severity_counts, f.severity) + 1)

    pages = db.query(Page).filter(Page.scan_request_id == scan.id).all()
    http_obs = (
        db.query(HTTPObservation)
        .filter(HTTPObservation.scan_request_id == scan.id)
        .order_by(HTTPObservation.created_at)
        .first()
    )
    dns_obs = db.query(DNSObservation).filter(DNSObservation.scan_request_id == scan.id).all()
    tech_obs = db.query(TechnologyObservation).filter(TechnologyObservation.scan_request_id == scan.id).all()
    third_party_obs = (
        db.query(ThirdPartyDependency)
        .filter(ThirdPartyDependency.scan_request_id == scan.id)
        .order_by(ThirdPartyDependency.request_count.desc())
        .all()
    )
    robots_evidence = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.scan_request_id == scan.id,
            EvidenceItem.category == "robots_sitemap",
            EvidenceItem.source_type == "robots_txt",
        )
        .order_by(EvidenceItem.captured_at)
        .first()
    )
    sitemap_evidence = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.scan_request_id == scan.id,
            EvidenceItem.category == "robots_sitemap",
            EvidenceItem.source_type == "sitemap_xml",
        )
        .order_by(EvidenceItem.captured_at)
        .first()
    )
    perf_obs = (
        db.query(PerformanceObservation)
        .filter(PerformanceObservation.scan_request_id == scan.id)
        .order_by(PerformanceObservation.created_at)
        .first()
    )

    failed_jobs = (
        db.query(ScanJob)
        .filter(ScanJob.scan_request_id == scan.id, ScanJob.status == JOB_STATUS_FAILED)
        .all()
    )
    limitations = [
        LimitationOut(task_name=job.task_name, message=job.error_message or "This collection task failed.")
        for job in failed_jobs
    ] + [LimitationOut(task_name="general", message=msg) for msg in KNOWN_LIMITATIONS]

    dns_email = {
        "records": [
            {
                "record_type": o.record_type,
                "name": o.name,
                "record_values": o.values,
                "lookup_successful": o.lookup_successful,
                "error_message": o.error_message,
            }
            for o in dns_obs
            if o.record_type not in ("SPF", "DMARC", "DKIM")
        ],
        "dkim_selectors_found": [o.dkim_selector for o in dns_obs if o.record_type == "DKIM" and o.dkim_selector],
        "dkim_probed_count": len(COMMON_DKIM_SELECTORS),
        "spf": next(
            (
                {"record": o.spf_record, "lookup_successful": o.lookup_successful, "error_message": o.error_message}
                for o in dns_obs
                if o.record_type == "SPF"
            ),
            None,
        ),
        "dmarc": next(
            (
                {
                    "record": o.dmarc_record,
                    "policy": o.dmarc_policy,
                    "pct": o.dmarc_pct,
                    "rua": o.dmarc_rua,
                    "lookup_successful": o.lookup_successful,
                    "error_message": o.error_message,
                }
                for o in dns_obs
                if o.record_type == "DMARC"
            ),
            None,
        ),
    }

    http_security = {}
    if http_obs:
        http_security = {
            "final_url": http_obs.final_url,
            "status_code": http_obs.status_code,
            "is_https": http_obs.is_https,
            "redirect_chain": http_obs.redirect_chain,
            "strict_transport_security": http_obs.strict_transport_security,
            "content_security_policy": http_obs.content_security_policy,
            "x_content_type_options": http_obs.x_content_type_options,
            "x_frame_options": http_obs.x_frame_options,
            "referrer_policy": http_obs.referrer_policy,
            "permissions_policy": http_obs.permissions_policy,
            "server_header": http_obs.server_header,
            "response_duration_ms": http_obs.response_duration_ms,
        }

    error_pages = [p for p in pages if p.status_code and p.status_code >= 400]
    crawl_indexability = {
        "pages_scanned": len(pages),
        "error_page_count": len(error_pages),
        "pages": [
            {
                "url": p.url,
                "status_code": p.status_code,
                "title": p.title,
                "canonical_url": p.canonical_url,
                "meta_description_present": bool(p.meta_description),
                "h1_count": p.h1_count,
                "fetch_error": p.fetch_error,
            }
            for p in pages
        ],
        "sitemap_check": _build_sitemap_check(pages, robots_evidence, sitemap_evidence),
    }

    technology = {
        "technologies": [
            {
                "technology_name": t.technology_name,
                "category": t.category,
                "detection_method": t.detection_method,
                "confidence": t.confidence,
            }
            for t in tech_obs
        ]
    }

    third_party_dependencies = {
        "domains": [
            {
                "hostname": d.hostname,
                "vendor_name": known_vendor_name(d.hostname),
                "category": d.category,
                "request_count": d.request_count,
                "classification_method": d.classification_method,
            }
            for d in third_party_obs
        ]
    }

    performance = {}
    if perf_obs:
        performance = {
            "provider": perf_obs.provider,
            "configured": perf_obs.configured,
            "response_duration_ms": perf_obs.response_duration_ms,
            "html_bytes": perf_obs.html_bytes,
            "third_party_domain_count": perf_obs.third_party_domain_count,
            "js_resource_count": perf_obs.js_resource_count,
            "desktop": {
                "lcp_ms": perf_obs.desktop_lcp_ms,
                "cls": perf_obs.desktop_cls,
                "inp_ms": perf_obs.desktop_inp_ms,
                "fcp_ms": perf_obs.desktop_fcp_ms,
                "ttfb_ms": perf_obs.desktop_ttfb_ms,
                "performance_score": perf_obs.desktop_performance_score,
                "accessibility_score": perf_obs.desktop_accessibility_score,
                "best_practices_score": perf_obs.desktop_best_practices_score,
                "seo_score": perf_obs.desktop_seo_score,
            },
            "mobile": {
                "lcp_ms": perf_obs.mobile_lcp_ms,
                "cls": perf_obs.mobile_cls,
                "inp_ms": perf_obs.mobile_inp_ms,
                "fcp_ms": perf_obs.mobile_fcp_ms,
                "ttfb_ms": perf_obs.mobile_ttfb_ms,
                "performance_score": perf_obs.mobile_performance_score,
                "accessibility_score": perf_obs.mobile_accessibility_score,
                "best_practices_score": perf_obs.mobile_best_practices_score,
                "seo_score": perf_obs.mobile_seo_score,
            },
        }

    return ReportOut(
        scan_id=scan.id,
        product_name=settings.product_name,
        parent_brand=settings.parent_brand,
        report_name=settings.report_name,
        domain=scan.normalized_domain,
        original_input=scan.original_input,
        notes=scan.notes,
        status=scan.status,
        max_pages=scan.max_pages,
        authorization_confirmed_at=scan.authorization_confirmed_at,
        started_at=scan.started_at,
        completed_at=scan.completed_at,
        pages_scanned=len(pages),
        is_demo=scan.is_demo,
        severity_counts=severity_counts,
        findings=finding_outs,
        rules_checked=rules_checked,
        dns_email=dns_email,
        http_security=http_security,
        crawl_indexability=crawl_indexability,
        technology=technology,
        third_party_dependencies=third_party_dependencies,
        performance=performance,
        limitations=limitations,
        generated_at=datetime.now(timezone.utc),
    )
