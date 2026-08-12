import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.scan import ScanRequest


class RateLimitExceeded(Exception):
    pass


def enforce_scan_creation_rate_limit(db: Session, user_id: uuid.UUID) -> None:
    """Rolling-hour count of scans this user has created, backed by
    Postgres (no Redis in this architecture). Keeps scan creation
    invite-only-scale and prevents the app from being used as a bulk
    scanning tool.
    """
    settings = get_settings()
    limit = settings.scan_create_rate_limit_per_hour
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

    count = (
        db.query(ScanRequest)
        .filter(ScanRequest.user_id == user_id, ScanRequest.created_at >= cutoff)
        .count()
    )

    if count >= limit:
        raise RateLimitExceeded(
            f"Scan creation limit reached ({limit} per hour). Please try again later."
        )
