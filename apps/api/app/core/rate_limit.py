import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.magic_link_token import MagicLinkToken
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


def enforce_magic_link_request_rate_limit(db: Session, requested_ip: str | None) -> None:
    """Rolling-hour count of magic-link requests from one IP, so the
    request-link endpoint can't be used to spam arbitrary email addresses.
    An unknown IP (requested_ip is None) is never rate-limited here — that
    would rate-limit every unknown-IP caller as one shared bucket.
    """
    if not requested_ip:
        return

    settings = get_settings()
    limit = settings.magic_link_request_rate_limit_per_hour
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

    count = (
        db.query(MagicLinkToken)
        .filter(MagicLinkToken.requested_ip == requested_ip, MagicLinkToken.created_at >= cutoff)
        .count()
    )

    if count >= limit:
        raise RateLimitExceeded(
            f"Too many sign-in link requests ({limit} per hour). Please try again later."
        )
