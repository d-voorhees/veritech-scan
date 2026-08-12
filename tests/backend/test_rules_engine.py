from datetime import datetime, timezone

from app.models.evidence import EvidenceItem
from app.models.finding import Finding, FindingEvidence
from app.models.observation import DNSObservation, HTTPObservation, PerformanceObservation, ThirdPartyDependency
from app.models.page import Page
from app.rules.engine import run_rules_engine


def _evidence(db, scan, category, source_type, summary="test evidence"):
    item = EvidenceItem(
        scan_request_id=scan.id,
        category=category,
        source_type=source_type,
        source_url_or_identifier="https://example.com/",
        captured_at=datetime.now(timezone.utc),
        confidence="high",
        normalized_payload_json={},
        human_readable_summary=summary,
    )
    db.add(item)
    db.flush()
    return item


def test_missing_dmarc_and_spf_produce_findings(db, scan_request):
    _evidence(db, scan_request, "email_posture", "spf_dmarc_lookup")
    db.add(DNSObservation(scan_request_id=scan_request.id, record_type="SPF", name="example.com", values=[], lookup_successful=True, spf_record=None))
    db.add(DNSObservation(scan_request_id=scan_request.id, record_type="DMARC", name="_dmarc.example.com", values=[], lookup_successful=True, dmarc_record=None))
    db.commit()

    run_rules_engine(db, scan_request)

    titles = {f.title for f in db.query(Finding).filter(Finding.scan_request_id == scan_request.id).all()}
    assert "No DMARC record found" in titles
    assert "No SPF record found" in titles


def test_dmarc_policy_none_produces_low_severity_finding(db, scan_request):
    _evidence(db, scan_request, "email_posture", "spf_dmarc_lookup")
    db.add(
        DNSObservation(
            scan_request_id=scan_request.id, record_type="DMARC", name="_dmarc.example.com",
            values=["v=DMARC1; p=none"], lookup_successful=True,
            dmarc_record="v=DMARC1; p=none", dmarc_policy="none",
        )
    )
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title == "DMARC policy set to p=none")
        .first()
    )
    assert finding is not None
    assert finding.severity == "low"
    assert finding.confidence == "high"


def test_homepage_not_https_is_high_severity(db, scan_request):
    _evidence(db, scan_request, "http", "http_response")
    db.add(
        HTTPObservation(
            scan_request_id=scan_request.id, url="http://example.com/", final_url="http://example.com/",
            status_code=200, redirect_chain=[], headers={}, is_https=False,
        )
    )
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.title == "Homepage served without HTTPS")
        .first()
    )
    assert finding is not None
    assert finding.severity == "high"


def test_https_with_full_security_headers_produces_no_security_findings(db, scan_request):
    _evidence(db, scan_request, "http", "http_response")
    db.add(
        HTTPObservation(
            scan_request_id=scan_request.id, url="https://example.com/", final_url="https://example.com/",
            status_code=200, redirect_chain=[], headers={}, is_https=True,
            strict_transport_security="max-age=63072000", content_security_policy="default-src 'self'",
        )
    )
    db.commit()

    run_rules_engine(db, scan_request)

    findings = db.query(Finding).filter(Finding.scan_request_id == scan_request.id).all()
    security_titles = {f.title for f in findings if f.category == "security_posture"}
    assert security_titles == set()


def test_excessive_third_party_domains_rule(db, scan_request):
    for i in range(11):
        db.add(
            ThirdPartyDependency(
                scan_request_id=scan_request.id, hostname=f"tracker{i}.example", category="uncategorized",
                request_count=1, classification_method="test",
            )
        )
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "dependency_management")
        .first()
    )
    assert finding is not None
    assert finding.severity == "medium"


def test_excessive_crawl_errors_rule(db, scan_request):
    crawl_evidence = _evidence(db, scan_request, "crawl", "bounded_crawl")
    for i in range(6):
        db.add(
            Page(
                scan_request_id=scan_request.id, url=f"https://example.com/broken-{i}",
                status_code=404,
            )
        )
    db.add(Page(scan_request_id=scan_request.id, url="https://example.com/", status_code=200))
    db.commit()

    run_rules_engine(db, scan_request)

    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "site_reliability")
        .first()
    )
    assert finding is not None
    assert finding.evidence_links[0].evidence_item_id == crawl_evidence.id


def test_pagespeed_rule_only_fires_when_configured(db, scan_request):
    db.add(
        PerformanceObservation(
            scan_request_id=scan_request.id, provider="local", configured=False, performance_score=30,
        )
    )
    db.commit()
    run_rules_engine(db, scan_request)
    assert (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "performance")
        .first()
        is None
    )


def test_pagespeed_rule_fires_when_configured_and_below_threshold(db, scan_request):
    _evidence(db, scan_request, "performance", "performance_measurement")
    db.add(
        PerformanceObservation(
            scan_request_id=scan_request.id, provider="google_pagespeed", configured=True, performance_score=25,
        )
    )
    db.commit()
    run_rules_engine(db, scan_request)
    finding = (
        db.query(Finding)
        .filter(Finding.scan_request_id == scan_request.id, Finding.category == "performance")
        .first()
    )
    assert finding is not None
    assert finding.severity == "medium"


def test_every_finding_links_to_at_least_one_evidence_item(db, scan_request):
    _evidence(db, scan_request, "email_posture", "spf_dmarc_lookup")
    db.add(DNSObservation(scan_request_id=scan_request.id, record_type="SPF", name="example.com", values=[], lookup_successful=True, spf_record=None))
    db.commit()

    run_rules_engine(db, scan_request)

    findings = db.query(Finding).filter(Finding.scan_request_id == scan_request.id).all()
    assert len(findings) > 0
    for f in findings:
        links = db.query(FindingEvidence).filter(FindingEvidence.finding_id == f.id).all()
        assert len(links) >= 1


def test_rules_engine_is_idempotent_on_rerun(db, scan_request):
    _evidence(db, scan_request, "email_posture", "spf_dmarc_lookup")
    db.add(DNSObservation(scan_request_id=scan_request.id, record_type="SPF", name="example.com", values=[], lookup_successful=True, spf_record=None))
    db.commit()

    first_ids = set(run_rules_engine(db, scan_request))
    db.commit()
    second_ids = set(run_rules_engine(db, scan_request))
    db.commit()

    findings = db.query(Finding).filter(Finding.scan_request_id == scan_request.id).all()
    assert len(findings) == len(second_ids)
    assert first_ids != second_ids  # old findings were cleared and recreated
