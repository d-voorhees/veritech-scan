"""Collector 4: DNS and email posture (SPF / DMARC).

DKIM discovery is intentionally out of scope for the MVP — see
`docs/rules-engine.md` for the documented extension point (user-supplied
selector checks).
"""

import uuid
from datetime import datetime, timezone

import dns.exception
import dns.resolver

from app.models.evidence import EvidenceItem
from app.models.observation import DNSObservation

RECORD_TYPES = ("A", "AAAA", "CNAME", "MX", "NS", "TXT")


def _resolve(resolver: dns.resolver.Resolver, name: str, record_type: str) -> tuple[list[str], bool, str | None]:
    try:
        answer = resolver.resolve(name, record_type)
        return [rdata.to_text() for rdata in answer], True, None
    except dns.resolver.NXDOMAIN:
        return [], True, "Domain does not exist."
    except dns.resolver.NoAnswer:
        return [], True, None
    except dns.exception.DNSException as exc:
        return [], False, str(exc)


def _parse_dmarc(record_text: str) -> dict:
    tags = {}
    for part in record_text.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        tags[key.strip().lower()] = value.strip()
    return {
        "policy": tags.get("p"),
        "rua": tags.get("rua"),
        "pct": tags.get("pct"),
    }


def run_dns_and_email_checks(
    db, scan_request_id: uuid.UUID, hostname: str, resolver: dns.resolver.Resolver | None = None
) -> dict:
    if resolver is None:
        resolver = dns.resolver.Resolver()
        resolver.lifetime = 5
        resolver.timeout = 5

    summary: dict = {"records": {}, "spf_present": False, "dmarc_present": False}

    for record_type in RECORD_TYPES:
        values, lookup_successful, error_message = _resolve(resolver, hostname, record_type)
        db.add(
            DNSObservation(
                scan_request_id=scan_request_id,
                record_type=record_type,
                name=hostname,
                values=values,
                lookup_successful=lookup_successful,
                error_message=error_message,
            )
        )
        summary["records"][record_type] = values

    # --- SPF: derived from TXT records already fetched above. -----------------
    txt_values = summary["records"].get("TXT", [])
    spf_records = [v.strip('"') for v in txt_values if v.strip('"').lower().startswith("v=spf1")]
    spf_record = spf_records[0] if spf_records else None

    db.add(
        DNSObservation(
            scan_request_id=scan_request_id,
            record_type="SPF",
            name=hostname,
            values=spf_records,
            lookup_successful=True,
            spf_record=spf_record,
        )
    )
    summary["spf_present"] = spf_record is not None
    summary["spf_record"] = spf_record

    # --- DMARC: separate query against _dmarc.<domain> --------------------------
    dmarc_name = f"_dmarc.{hostname}"
    dmarc_values, dmarc_lookup_successful, dmarc_error = _resolve(resolver, dmarc_name, "TXT")
    dmarc_records = [v.strip('"') for v in dmarc_values if v.strip('"').lower().startswith("v=dmarc1")]
    dmarc_record = dmarc_records[0] if dmarc_records else None
    dmarc_tags = _parse_dmarc(dmarc_record) if dmarc_record else {}

    db.add(
        DNSObservation(
            scan_request_id=scan_request_id,
            record_type="DMARC",
            name=dmarc_name,
            values=dmarc_records,
            lookup_successful=dmarc_lookup_successful,
            error_message=dmarc_error,
            dmarc_record=dmarc_record,
            dmarc_policy=dmarc_tags.get("policy"),
            dmarc_pct=dmarc_tags.get("pct"),
            dmarc_rua=dmarc_tags.get("rua"),
        )
    )
    summary["dmarc_present"] = dmarc_record is not None
    summary["dmarc_lookup_successful"] = dmarc_lookup_successful
    summary["dmarc_record"] = dmarc_record
    summary["dmarc_policy"] = dmarc_tags.get("policy")

    db.flush()

    dns_evidence = EvidenceItem(
        scan_request_id=scan_request_id,
        category="dns",
        source_type="dns_lookup",
        source_url_or_identifier=hostname,
        captured_at=datetime.now(timezone.utc),
        confidence="high",
        normalized_payload_json={"records": summary["records"]},
        human_readable_summary=(
            f"Resolved DNS records for {hostname}: "
            + ", ".join(f"{k}={len(v)}" for k, v in summary["records"].items())
        ),
        raw_response_reference=None,
    )
    db.add(dns_evidence)

    email_evidence = EvidenceItem(
        scan_request_id=scan_request_id,
        category="email_posture",
        source_type="spf_dmarc_lookup",
        source_url_or_identifier=f"{hostname} / {dmarc_name}",
        captured_at=datetime.now(timezone.utc),
        confidence="high",
        normalized_payload_json={
            "spf_present": summary["spf_present"],
            "spf_record": spf_record,
            "dmarc_present": summary["dmarc_present"],
            "dmarc_lookup_successful": dmarc_lookup_successful,
            "dmarc_record": dmarc_record,
            "dmarc_policy": dmarc_tags.get("policy"),
            "dmarc_pct": dmarc_tags.get("pct"),
            "dmarc_rua": dmarc_tags.get("rua"),
        },
        human_readable_summary=(
            f"SPF record {'present' if summary['spf_present'] else 'not present'}. "
            f"DMARC record {'present' if summary['dmarc_present'] else 'not present'}"
            + (f" with policy p={dmarc_tags.get('policy')}." if dmarc_tags.get("policy") else ".")
        ),
        raw_response_reference=None,
    )
    db.add(email_evidence)
    db.flush()

    summary["evidence_id"] = email_evidence.id
    summary["dns_evidence_id"] = dns_evidence.id
    return summary
