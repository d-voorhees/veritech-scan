import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.url_safety import validate_target
from app.models.scan import JOB_STATUS_PENDING, SCAN_STATUS_QUEUED, ScanEvent, ScanJob, ScanRequest, ScanTarget
from app.models.user import User
from app.schemas.scan import ScanCreateRequest

# Ordered collection pipeline. Each becomes a ScanJob row and a retryable
# Dramatiq task (see app/tasks/scan_tasks.py). Order here only drives the
# initial job rows / UI ordering — execution order is enforced by the
# orchestrator task.
COLLECTION_TASK_NAMES = (
    "http_checks",
    "robots_sitemap",
    "crawl",
    "dns_email_posture",
    "browser_render",
    "technology_detection",
    "performance",
    "rules_engine",
)


def record_event(db: Session, scan_request_id: uuid.UUID, event_type: str, message: str) -> None:
    db.add(ScanEvent(scan_request_id=scan_request_id, event_type=event_type, message=message))


def create_scan(db: Session, user: User, payload: ScanCreateRequest) -> ScanRequest:
    """Validate the target and persist a queued scan + its job skeleton.
    Raises UnsafeTargetError if the target fails SSRF / boundary checks.
    """
    validated = validate_target(payload.target_input)

    scan = ScanRequest(
        user_id=user.id,
        organization_id=user.organization_id,
        normalized_domain=validated.hostname,
        original_input=payload.target_input,
        notes=payload.notes,
        max_pages=payload.max_pages,
        authorization_confirmed_at=datetime.now(timezone.utc),
        status=SCAN_STATUS_QUEUED,
    )
    db.add(scan)
    db.flush()

    db.add(
        ScanTarget(
            scan_request_id=scan.id,
            hostname=validated.hostname,
            canonical_url=validated.canonical_url,
            resolved_ips=validated.resolved_ips,
        )
    )

    for task_name in COLLECTION_TASK_NAMES:
        db.add(ScanJob(scan_request_id=scan.id, task_name=task_name, status=JOB_STATUS_PENDING))

    record_event(db, scan.id, "scan_queued", f"Scan queued for {validated.hostname}.")
    db.commit()
    db.refresh(scan)
    return scan


def enqueue_scan(scan_id: uuid.UUID) -> None:
    from app.tasks.scan_tasks import run_scan

    run_scan.send(str(scan_id))
