"""Fase A: skeleton. Reads only the chain head and advances the cursor;
event consumption into read-models lands in Fase B (TokensSentWithMessage) and
Fase C/D (SBTIssued, DistributionCodeRedeemed, DecayApplied).
"""

from __future__ import annotations

from sqlalchemy import select
from web3 import AsyncHTTPProvider, AsyncWeb3

from iconomy.core.db import Database
from iconomy.core.logging import get_logger
from iconomy.indexer.models import IndexerCursor

logger = get_logger(__name__)

# How many blocks of head confirmations to wait before considering a block
# "indexable". Keeps us resilient to short re-orgs on Sepolia (reth tends to
# finalize within a couple of blocks).
CONFIRMATIONS = 3


class ChainIndexer:
    def __init__(
        self,
        database: Database,
        *,
        rpc_url: str,
        contracts: list[str],
    ) -> None:
        self._database = database
        self._w3 = AsyncWeb3(AsyncHTTPProvider(rpc_url, request_kwargs={"timeout": 10.0}))
        self._contracts = [AsyncWeb3.to_checksum_address(addr) for addr in contracts]

    async def tick(self) -> None:
        """One pass. Advances the cursor; the actual event handlers land later."""
        try:
            latest = await self._w3.eth.block_number
        except Exception as exc:
            logger.warning("indexer_rpc_unreachable", error=str(exc))
            return

        safe = max(latest - CONFIRMATIONS, 0)

        async with self._database.session() as session:
            for contract in self._contracts:
                row = (
                    await session.execute(
                        select(IndexerCursor).where(IndexerCursor.contract == contract)
                    )
                ).scalar_one_or_none()
                if row is None:
                    row = IndexerCursor(contract=contract, last_block=safe)
                    session.add(row)
                    logger.info("indexer_cursor_initialised", contract=contract, block=safe)
                    continue

                if safe > row.last_block:
                    # Fase A: no event handlers yet. Just log and advance.
                    logger.info(
                        "indexer_cursor_advanced",
                        contract=contract,
                        from_block=row.last_block,
                        to_block=safe,
                    )
                    row.last_block = safe
