import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.url_safety import validate_target
from app.logging_config import get_logger
from app.models.scan import (
    JOB_STATUS_PENDING,
    SCAN_STATUS_FAILED,
    SCAN_STATUS_QUEUED,
    SCAN_STATUS_STARTING,
    ScanEvent,
    ScanJob,
    ScanRequest,
    ScanTarget,
)
from app.models.user import User
from app.schemas.scan import ScanCreateRequest
from app.services.fly_machines import FlyMachinesClient, FlyMachinesError

logger = get_logger(__name__)

# Ordered collection pipeline. Each becomes a ScanJob row and a retryable
# stage run by the scan-runner (see app/runner/run.py). Order here only
# drives the initial job rows / UI ordering — execution order is enforced
# by the runner.
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


def request_scan_runner(db: Session, scan: ScanRequest) -> None:
    """Requests an on-demand scan-runner for `scan` (flow steps 3->4 of the
    scan initiation flow). In production this creates a real Fly Machine
    via the Fly Machines API; in local development (no FLY_API_TOKEN
    configured) it spawns the same runner code as a plain background
    subprocess instead, so there is no persistent worker in either
    environment and no Fly account is required to develop locally.

    On any failure to start a runner, marks the scan `failed` with a clear
    event/failure_summary and re-raises FlyMachinesError so the API layer
    can return a clean error — a scan is never left `queued` while
    appearing to be running.
    """
    settings = get_settings()
    record_event(db, scan.id, "runner_requested", f"Scan runner requested for scan {scan.id}.")
    db.commit()

    if not settings.is_production and not settings.fly_api_token:
        _spawn_local_runner_subprocess(scan.id)
        scan.status = SCAN_STATUS_STARTING
        scan.retry_count += 1
        record_event(db, scan.id, "runner_machine_created", "Local dev runner subprocess started (no Fly Machine).")
        db.commit()
        return

    try:
        client = FlyMachinesClient(
            api_token=settings.fly_api_token, app_name=settings.fly_app_name, base_url=_fly_api_base_url()
        )
        machine = client.create_machine(
            name=f"scan-runner-{scan.id}",
            region=settings.fly_primary_region,
            image=_current_image_ref(settings.fly_app_name),
            env={"SCAN_ID": str(scan.id)},
            # The image's ENTRYPOINT is already /app/scripts/entrypoint.sh
            # (see Dockerfile) — cmd becomes its argument(s), not a second
            # copy of the script path (that doubling crash-looped the
            # web/API Machine the first time this was deployed).
            cmd=["scan-runner"],
            metadata={"role": "scan-runner", "scan_id": str(scan.id)},
        )
    except FlyMachinesError as exc:
        scan.status = SCAN_STATUS_FAILED
        scan.failure_summary = f"Failed to start scan runner: {exc}"
        record_event(db, scan.id, "runner_creation_failed", scan.failure_summary)
        db.commit()
        raise

    scan.status = SCAN_STATUS_STARTING
    scan.runner_machine_id = machine.get("id")
    scan.retry_count += 1
    record_event(db, scan.id, "runner_machine_created", f"Fly Machine {machine.get('id')} created for this scan.")
    db.commit()


def _fly_api_base_url() -> str:
    return os.environ.get("FLY_API_HOSTNAME", "https://api.machines.dev/v1")


def _current_image_ref(fly_app_name: str) -> str:
    """The web/API Machine's own running image, re-used to launch the
    scan-runner Machine. Fly injects FLY_IMAGE_REF into every Machine's
    environment with the exact image reference it's running (e.g.
    `registry.fly.io/<app>:deployment-<id>`) — see
    https://fly.io/docs/machines/runtime-environment/. Falls back to the
    app's `:latest` tag if unset (e.g. running outside a Fly Machine).
    """
    return os.environ.get("FLY_IMAGE_REF") or f"registry.fly.io/{fly_app_name}:latest"


def _spawn_local_runner_subprocess(scan_id: uuid.UUID) -> None:
    """Local-dev only: runs the scan-runner as a detached background
    process on the developer's own machine, using the same `python -m
    app.runner` entrypoint the Fly Machine uses in production.
    """
    env = {**os.environ, "SCAN_ID": str(scan_id)}
    try:
        subprocess.Popen(  # noqa: S603 -- trusted, fixed argv; not shell=True
            [sys.executable, "-m", "app.runner"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        logger.error("local_runner_spawn_failed", scan_id=str(scan_id), error=str(exc))
        raise FlyMachinesError(f"Failed to spawn local scan-runner subprocess: {exc}") from exc
