from datetime import datetime, timezone

from sqlalchemy.orm import Session, joinedload

from app.config import get_settings
from app.models.finding import Finding, FindingEvidence
from app.models.observation import DNSObservation, HTTPObservation, PerformanceObservation, TechnologyObservation
from app.models.page import Page
from app.models.scan import JOB_STATUS_FAILED, ScanJob, ScanRequest
from app.schemas.evidence import EvidenceItemOut, FindingOut
from app.schemas.report import FindingSeverityCounts, LimitationOut, ReportOut

KNOWN_LIMITATIONS = [
    "This is a bounded, rate-limited public-web pre-screen, not a penetration test or "
    "vulnerability scan. Absence of a finding is not proof of absence of risk.",
    "The crawler records robots.txt as evidence but does not implement full robots.txt "
    "enforcement in the MVP.",
    "DKIM discovery is not implemented in the MVP; only SPF and DMARC are assessed.",
    "The browser renderer inspects only the homepage, not the full crawled page set.",
    "Google PageSpeed Insights metrics are only present when GOOGLE_PAGESPEED_API_KEY is configured.",
]


def build_report(db: Session, scan: ScanRequest) -> ReportOut:
    settings = get_settings()

    severity_rank = {"high": 0, "medium": 1, "low": 2, "info": 3}
    findings = (
        db.query(Finding)
        .options(joinedload(Finding.evidence_links).joinedload(FindingEvidence.evidence_item))
        .filter(Finding.scan_request_id == scan.id)
        .all()
    )
    findings.sort(key=lambda f: (severity_rank.get(f.severity, 9), f.created_at))

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
            if o.record_type not in ("SPF", "DMARC")
        ],
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

    performance = {}
    if perf_obs:
        performance = {
            "provider": perf_obs.provider,
            "configured": perf_obs.configured,
            "response_duration_ms": perf_obs.response_duration_ms,
            "html_bytes": perf_obs.html_bytes,
            "third_party_domain_count": perf_obs.third_party_domain_count,
            "js_resource_count": perf_obs.js_resource_count,
            "lcp_ms": perf_obs.lcp_ms,
            "cls": perf_obs.cls,
            "inp_ms": perf_obs.inp_ms,
            "fcp_ms": perf_obs.fcp_ms,
            "ttfb_ms": perf_obs.ttfb_ms,
            "performance_score": perf_obs.performance_score,
            "accessibility_score": perf_obs.accessibility_score,
            "best_practices_score": perf_obs.best_practices_score,
            "seo_score": perf_obs.seo_score,
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
        dns_email=dns_email,
        http_security=http_security,
        crawl_indexability=crawl_indexability,
        technology=technology,
        performance=performance,
        limitations=limitations,
        generated_at=datetime.now(timezone.utc),
    )
