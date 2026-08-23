import asyncio
import time
from typing import Protocol

import httpx
import jwt

from iconomy.core.errors import UpstreamError
from iconomy.core.logging import get_logger

logger = get_logger(__name__)


class KeySource(Protocol):
    async def get(self, kid: str, *, force_refresh: bool = False) -> jwt.PyJWK | None: ...


class RemoteKeySource:
    def __init__(self, uri: str, *, client: httpx.AsyncClient, cache_seconds: int) -> None:
        self._uri = uri
        self._client = client
        self._cache_seconds = cache_seconds
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    async def get(self, kid: str, *, force_refresh: bool = False) -> jwt.PyJWK | None:
        if force_refresh or self._is_stale():
            await self._refresh(force=force_refresh)
        return self._keys.get(kid)

    def _is_stale(self) -> bool:
        return not self._keys or (time.monotonic() - self._fetched_at) > self._cache_seconds

    async def _refresh(self, *, force: bool) -> None:
        async with self._lock:
            # Another coroutine may have refreshed while this one waited.
            if not force and not self._is_stale():
                return
            try:
                response = await self._client.get(self._uri)
                response.raise_for_status()
                document = response.json()
            except (httpx.HTTPError, ValueError) as ex:
                logger.warning("jwks_unavailable", uri=self._uri, error=str(ex))
                raise UpstreamError("The identity provider is unavailable.") from ex

            keys = jwt.PyJWKSet.from_dict(document).keys
            self._keys = {key.key_id: key for key in keys if key.key_id is not None}
            self._fetched_at = time.monotonic()
            logger.info("jwks_refreshed", keys=len(self._keys))
