import falcon
import falcon.asgi
from redis.asyncio import Redis

from iconomy.core.cache import ping_redis
from iconomy.core.db import Database


class LivenessResource:
    async def on_get(self, req: falcon.asgi.Request, resp: falcon.asgi.Response) -> None:
        resp.media = {"status": "alive"}


class ReadinessResource:
    def __init__(self, database: Database, redis: Redis, *, version: str) -> None:
        self._database = database
        self._redis = redis
        self._version = version

    async def on_get(self, req: falcon.asgi.Request, resp: falcon.asgi.Response) -> None:
        checks = {
            "database": await self._database.ping(),
            "redis": await ping_redis(self._redis),
        }
        ready = all(checks.values())

        resp.status = falcon.HTTP_200 if ready else falcon.HTTP_503
        resp.media = {
            "status": "ready" if ready else "degraded",
            "version": self._version,
            "checks": checks,
        }
