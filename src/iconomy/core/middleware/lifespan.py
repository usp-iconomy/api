from collections.abc import Mapping
from typing import Any

from redis.asyncio import Redis

from iconomy.core.cache import ping_redis
from iconomy.core.db import Database
from iconomy.core.logging import get_logger

logger = get_logger(__name__)


class LifespanMiddleware:
    def __init__(self, database: Database, redis: Redis) -> None:
        self._database = database
        self._redis = redis

    async def process_startup(self, scope: Mapping[str, Any], event: Mapping[str, Any]) -> None:
        checks = {
            "database": await self._database.ping(),
            "redis": await ping_redis(self._redis),
        }
        if all(checks.values()):
            logger.info("startup", **checks)
        else:
            logger.warning("startup_degraded", **checks)

    async def process_shutdown(self, scope: Mapping[str, Any], event: Mapping[str, Any]) -> None:
        try:
            await self._database.dispose()
            await self._redis.aclose()
        except Exception:
            logger.warning("shutdown_incomplete", exc_info=True)
        logger.info("shutdown")
