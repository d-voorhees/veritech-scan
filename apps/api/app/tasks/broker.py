import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.config import get_settings

_settings = get_settings()
_broker = RedisBroker(url=_settings.redis_url)
dramatiq.set_broker(_broker)
