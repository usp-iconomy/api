from typing import cast

from redis.asyncio import Redis


def create_redis(url: str) -> Redis:
    return cast(Redis, Redis.from_url(url, encoding="utf-8", decode_responses=True))


async def ping_redis(client: Redis) -> bool:
    try:
        return bool(await client.ping())
    except Exception:
        return False
