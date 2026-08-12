import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models.evidence import EvidenceItem
from app.models.observation import DNSObservation, HTTPObservation, PerformanceObservation, ThirdPartyDependency
from app.models.page import Page
from app.models.scan import ScanRequest


@dataclass
class RuleContext:
    db: Session
    scan: ScanRequest
    dns_observations: list[DNSObservation]
    http_observation: HTTPObservation | None
    pages: list[Page]
    homepage: Page | None
    third_party_deps: list[ThirdPartyDependency]
    performance: PerformanceObservation | None
    evidence_ids: dict[str, uuid.UUID | None] = field(default_factory=dict)

    def dns_by_type(self, record_type: str) -> DNSObservation | None:
        return next((o for o in self.dns_observations if o.record_type == record_type), None)


def build_rule_context(db: Session, scan: ScanRequest) -> RuleContext:
    dns_observations = (
        db.query(DNSObservation).filter(DNSObservation.scan_request_id == scan.id).all()
    )
    http_observation = (
        db.query(HTTPObservation)
        .filter(HTTPObservation.scan_request_id == scan.id)
        .order_by(HTTPObservation.created_at)
        .first()
    )
    pages = db.query(Page).filter(Page.scan_request_id == scan.id).order_by(Page.created_at).all()
    homepage = pages[0] if pages else None
    third_party_deps = (
        db.query(ThirdPartyDependency).filter(ThirdPartyDependency.scan_request_id == scan.id).all()
    )
    performance = (
        db.query(PerformanceObservation)
        .filter(PerformanceObservation.scan_request_id == scan.id)
        .order_by(PerformanceObservation.created_at)
        .first()
    )

    def first_evidence_id(category: str, source_type: str | None = None) -> uuid.UUID | None:
        q = db.query(EvidenceItem).filter(
            EvidenceItem.scan_request_id == scan.id, EvidenceItem.category == category
        )
        if source_type:
            q = q.filter(EvidenceItem.source_type == source_type)
        item = q.order_by(EvidenceItem.captured_at).first()
        return item.id if item else None

    evidence_ids = {
        "email_posture": first_evidence_id("email_posture", "spf_dmarc_lookup"),
        "http": first_evidence_id("http", "http_response"),
        "sitemap": first_evidence_id("robots_sitemap", "sitemap_xml"),
        "crawl": first_evidence_id("crawl", "bounded_crawl"),
        "homepage_snapshot": first_evidence_id("crawl", "page_snapshot"),
        "performance": first_evidence_id("performance", "performance_measurement"),
    }

    return RuleContext(
        db=db,
        scan=scan,
        dns_observations=dns_observations,
        http_observation=http_observation,
        pages=pages,
        homepage=homepage,
        third_party_deps=third_party_deps,
        performance=performance,
        evidence_ids=evidence_ids,
    )
