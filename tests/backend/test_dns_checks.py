import dns.exception
import dns.resolver

from app.collectors.dns_checks import _parse_dmarc, run_dns_and_email_checks
from app.models.observation import DNSObservation


class FakeRData:
    def __init__(self, text):
        self._text = text

    def to_text(self):
        return self._text


class FakeResolver:
    """records: {(name, record_type): [raw_text, ...]}. Missing keys raise
    NoAnswer (a normal "record absent" outcome, not a lookup failure).
    """

    def __init__(self, records=None, nxdomain_for=None, servfail_for=None):
        self.records = records or {}
        self.nxdomain_for = nxdomain_for or set()
        self.servfail_for = servfail_for or set()
        self.lifetime = 5
        self.timeout = 5

    def resolve(self, name, record_type):
        if name in self.servfail_for:
            raise dns.exception.DNSException("SERVFAIL")
        if name in self.nxdomain_for:
            raise dns.resolver.NXDOMAIN()
        key = (name, record_type)
        if key not in self.records:
            raise dns.resolver.NoAnswer()
        return [FakeRData(v) for v in self.records[key]]


def test_parse_dmarc_extracts_policy_rua_pct():
    tags = _parse_dmarc("v=DMARC1; p=quarantine; rua=mailto:dmarc@example.com; pct=50")
    assert tags["policy"] == "quarantine"
    assert tags["rua"] == "mailto:dmarc@example.com"
    assert tags["pct"] == "50"


def test_parse_dmarc_handles_missing_optional_tags():
    tags = _parse_dmarc("v=DMARC1; p=none")
    assert tags["policy"] == "none"
    assert tags["rua"] is None
    assert tags["pct"] is None


def test_spf_and_dmarc_present(db, scan_request):
    resolver = FakeResolver(
        records={
            ("example.com", "TXT"): ['"v=spf1 include:_spf.google.com ~all"'],
            ("_dmarc.example.com", "TXT"): ['"v=DMARC1; p=quarantine; rua=mailto:dmarc@example.com"'],
        }
    )
    summary = run_dns_and_email_checks(db, scan_request.id, "example.com", resolver=resolver)

    assert summary["spf_present"] is True
    assert "v=spf1" in summary["spf_record"]
    assert summary["dmarc_present"] is True
    assert summary["dmarc_policy"] == "quarantine"


def test_missing_spf_and_dmarc_are_recorded_as_absent_not_failed(db, scan_request):
    resolver = FakeResolver(nxdomain_for={"_dmarc.example.com"})
    summary = run_dns_and_email_checks(db, scan_request.id, "example.com", resolver=resolver)

    assert summary["spf_present"] is False
    assert summary["dmarc_present"] is False
    # NXDOMAIN on the _dmarc subdomain is a normal "no record published"
    # outcome, not a DNS lookup failure.
    assert summary["dmarc_lookup_successful"] is True


def test_dns_servfail_is_recorded_as_lookup_failure(db, scan_request):
    resolver = FakeResolver(servfail_for={"example.com"})
    scan_id = scan_request.id
    run_dns_and_email_checks(db, scan_id, "example.com", resolver=resolver)

    a_obs = (
        db.query(DNSObservation)
        .filter(DNSObservation.scan_request_id == scan_id, DNSObservation.record_type == "A")
        .first()
    )
    assert a_obs.lookup_successful is False
    assert a_obs.error_message
