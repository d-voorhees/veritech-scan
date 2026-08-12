import uuid
from functools import lru_cache

import redis

from app.config import get_settings


@lru_cache
def get_redis_client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


class RateLimitExceeded(Exception):
    pass


def enforce_scan_creation_rate_limit(user_id: uuid.UUID) -> None:
    """Sliding-hour counter per user. Keeps scan creation invite-only-scale
    and prevents the app from being used as a bulk scanning tool.
    """
    settings = get_settings()
    limit = settings.scan_create_rate_limit_per_hour
    key = f"rate_limit:scan_create:{user_id}"

    client = get_redis_client()
    current = client.incr(key)
    if current == 1:
        client.expire(key, 3600)

    if current > limit:
        raise RateLimitExceeded(
            f"Scan creation limit reached ({limit} per hour). Please try again later."
        )
