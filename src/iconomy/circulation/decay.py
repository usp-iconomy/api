"""Decay keeper (RN-01) — periodically applies the on-chain decay to every
known wallet. The contract itself no-ops wallets that have been active in
less than `decayInterval`, so blind-calling the whole set is safe.
"""

from __future__ import annotations

from sqlalchemy import select

from iconomy.accounts.models import User
from iconomy.core.db import Database
from iconomy.core.logging import get_logger
from iconomy.peacecoin.adapter import PeaceCoinAdapter

logger = get_logger(__name__)

BATCH_SIZE = 50


class DecayKeeper:
    def __init__(self, database: Database, peacecoin: PeaceCoinAdapter) -> None:
        self._database = database
        self._peacecoin = peacecoin

    async def tick(self) -> int:
        """Call `applyDecayBatch` on every known wallet, chunked. Returns the
        number of wallets scanned (not the number actually decayed; the
        contract decides which ones are due).
        """
        wallets = await self._load_wallets()
        if not wallets:
            return 0

        for start in range(0, len(wallets), BATCH_SIZE):
            batch = wallets[start : start + BATCH_SIZE]
            try:
                tx_hash = await self._peacecoin.apply_decay_batch(batch)
            except Exception as exc:
                logger.warning(
                    "decay_batch_failed",
                    size=len(batch),
                    error=str(exc),
                )
                continue
            logger.info("decay_batch_submitted", size=len(batch), tx_hash=tx_hash)
        return len(wallets)

    async def _load_wallets(self) -> list[str]:
        async with self._database.session() as session:
            rows = await session.execute(
                select(User.wallet_address).where(User.wallet_address.is_not(None))
            )
            return [addr for (addr,) in rows if addr]
