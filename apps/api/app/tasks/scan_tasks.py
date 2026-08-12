"""The scan orchestrator: one Dramatiq actor that runs each collection area
in order, isolating failures so a single collector failing does not fail the
whole scan (see docs/architecture.md and docs/rules-engine.md).

Each collection area gets its own ScanJob row and its own bounded retry
(`_run_job`), which is what "separate, retryable" means here in a
single-worker (concurrency=1) deployment: independent failure isolation and
bounded retries per area, without the operational complexity of a
multi-actor DAG for a sequential pipeline that must respect one overall
10-minute scan budget.
"""

import time
import uuid
from datetime import datetime, timezone

import dramatiq

import app.tasks.broker  # noqa: F401 -- configures the Dramatiq Redis broker
from app.collectors import browser_render, crawler, dns_checks, http_checks, performance, robots_sitemap, technology
from app.config import get_settings
from app.db import SessionLocal
from app.logging_config import get_logger
from app.models.report import Report
from app.models.scan import (
    JOB_STATUS_FAILED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    SCAN_STATUS_COMPLETED,
    SCAN_STATUS_COMPLETED_WITH_WARNINGS,
    SCAN_STATUS_FAILED,
    SCAN_STATUS_RUNNING,
    ScanJob,
    ScanRequest,
    ScanTarget,
)
from app.rules.engine import run_rules_engine
from app.services.artifact_storage import get_artifact_storage
from app.services.html_export import render_report_html
from app.services.report_builder import build_report
from app.services.scan_orchestrator import record_event

logger = get_logger(__name__)

MAX_ATTEMPTS = 2


def determine_scan_status(jobs) -> tuple[str, str | None]:
    """Pure status-rollup logic, factored out for unit testing: a scan is
    `failed` only if every collection task failed, `completed_with_warnings`
    if some (but not all) failed, else `completed`.
    """
    failed_jobs = [j for j in jobs if j.status == JOB_STATUS_FAILED]
    succeeded_jobs = [j for j in jobs if j.status == JOB_STATUS_SUCCEEDED]

    if not succeeded_jobs:
        return SCAN_STATUS_FAILED, "All collection tasks failed; no evidence was collected."
    if failed_jobs:
        summary = (
            f"{len(failed_jobs)} of {len(jobs)} collection task(s) failed: "
            + ", ".join(j.task_name for j in failed_jobs)
        )
        return SCAN_STATUS_COMPLETED_WITH_WARNINGS, summary
    return SCAN_STATUS_COMPLETED, None


def _run_job(db, scan, task_name, fn):
    """Runs one collection area with a bounded number of attempts. Never
    raises — a permanent failure is recorded on the ScanJob row and the
    orchestrator moves on to the next collection area.
    """
    job = db.query(ScanJob).filter_by(scan_request_id=scan.id, task_name=task_name).first()
    job.status = JOB_STATUS_RUNNING
    job.started_at = datetime.now(timezone.utc)
    db.commit()

    for attempt in range(1, MAX_ATTEMPTS + 1):
        job.attempts = attempt
        db.commit()
        try:
            result = fn()
            job.status = JOB_STATUS_SUCCEEDED
            job.finished_at = datetime.now(timezone.utc)
            record_event(db, scan.id, f"{task_name}_succeeded", f"{task_name.replace('_', ' ').title()} completed.")
            db.commit()
            return result
        except Exception as exc:  # noqa: BLE001 -- collector failures must never crash the scan
            db.rollback()
            logger.warning("collection_task_failed", task=task_name, attempt=attempt, error=str(exc))
            job = db.query(ScanJob).filter_by(scan_request_id=scan.id, task_name=task_name).first()
            job.attempts = attempt
            job.error_message = str(exc)[:2000]
            if attempt >= MAX_ATTEMPTS:
                job.status = JOB_STATUS_FAILED
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
                record_event(
                    db,
                    scan.id,
                    f"{task_name}_failed",
                    f"{task_name.replace('_', ' ').title()} failed after {attempt} attempt(s): {str(exc)[:300]}",
                )
                db.commit()
                return None
            db.commit()

    return None


@dramatiq.actor(max_retries=0, time_limit=11 * 60 * 1000)
def run_scan(scan_id: str) -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        scan = db.get(ScanRequest, uuid.UUID(scan_id))
        if not scan:
            logger.error("scan_not_found", scan_id=scan_id)
            return

        target = db.query(ScanTarget).filter_by(scan_request_id=scan.id).first()
        if target is None:
            # create_scan() always writes a ScanTarget alongside the
            # ScanRequest — this would indicate a data integrity bug, not a
            # user-facing condition.
            logger.error("scan_target_missing", scan_id=scan_id)
            record_event(db, scan.id, "scan_failed", "Internal error: scan target record is missing.")
            scan.status = SCAN_STATUS_FAILED
            scan.failure_summary = "Internal error: scan target record is missing."
            db.commit()
            return

        scan.status = SCAN_STATUS_RUNNING
        scan.started_at = datetime.now(timezone.utc)
        record_event(db, scan.id, "scan_started", f"Scan started for {scan.normalized_domain}.")
        db.commit()

        deadline = time.monotonic() + settings.scan_max_total_minutes * 60

        def time_remaining() -> bool:
            return time.monotonic() < deadline

        http_result = None
        browser_result = None

        if time_remaining():
            http_result = _run_job(
                db, scan, "http_checks", lambda: http_checks.run_http_checks(db, scan.id, target.canonical_url)
            )

        if time_remaining():
            _run_job(
                db,
                scan,
                "robots_sitemap",
                lambda: robots_sitemap.run_robots_and_sitemap_checks(
                    db, scan.id, target.canonical_url, scan.max_pages
                ),
            )

        if time_remaining():
            _run_job(
                db,
                scan,
                "crawl",
                lambda: crawler.run_crawl(db, scan.id, target.canonical_url, target.hostname, scan.max_pages),
            )

        if time_remaining():
            _run_job(
                db, scan, "dns_email_posture", lambda: dns_checks.run_dns_and_email_checks(db, scan.id, target.hostname)
            )

        if time_remaining():
            browser_result = _run_job(
                db,
                scan,
                "browser_render",
                lambda: browser_render.run_browser_render(db, scan.id, target.canonical_url, target.hostname),
            )

        if time_remaining():
            _run_job(
                db,
                scan,
                "technology_detection",
                lambda: technology.run_technology_detection(
                    db, scan.id, (http_result or {}).get("html_text"), (http_result or {}).get("headers", {})
                ),
            )

        if time_remaining():
            perf_context = {
                "response_duration_ms": (http_result or {}).get("response_duration_ms"),
                "html_bytes": (http_result or {}).get("html_bytes"),
                "third_party_domain_count": (browser_result or {}).get("third_party_domain_count"),
                "js_resource_count": (browser_result or {}).get("js_resource_count"),
            }
            _run_job(
                db,
                scan,
                "performance",
                lambda: performance.run_performance_checks(
                    db, scan.id, (http_result or {}).get("final_url", target.canonical_url), perf_context
                ),
            )

        # Always run the rules engine against whatever evidence was
        # collected, even if the deadline passed partway through collection.
        _run_job(db, scan, "rules_engine", lambda: run_rules_engine(db, scan))

        db.refresh(scan)
        jobs = db.query(ScanJob).filter_by(scan_request_id=scan.id).all()
        scan.status, scan.failure_summary = determine_scan_status(jobs)

        scan.completed_at = datetime.now(timezone.utc)
        record_event(db, scan.id, "scan_completed", f"Scan finished with status: {scan.status}.")
        db.commit()

        try:
            report = build_report(db, scan)
            html = render_report_html(report)
            storage = get_artifact_storage()
            path = storage.save(f"{scan.id}/report.html", html.encode("utf-8"))
            db.add(
                Report(
                    scan_request_id=scan.id,
                    format="html",
                    storage_path=path,
                    generated_at=datetime.now(timezone.utc),
                )
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("report_generation_failed", scan_id=scan_id, error=str(exc))
            db.rollback()

    finally:
        db.close()
