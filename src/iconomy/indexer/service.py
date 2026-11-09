"""Chain indexer — materialises on-chain state into Postgres read-models.

Fase B scope:
  - `TokensSentWithMessage` → row in `circulation_events` + intent reconciliation
  - `DecayApplied` → log only (balance cache lands with Fase D)

Fase C/D will add `SBTIssued` and `DistributionCodeRedeemed` on top.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from web3 import AsyncHTTPProvider, AsyncWeb3

from iconomy.accounts.models import User
from iconomy.circulation.models import CirculationEvent
from iconomy.core.db import Database
from iconomy.core.hexutil import to_hex_string
from iconomy.core.logging import get_logger
from iconomy.indexer.models import (
    IndexerCursor,
    OnchainIntent,
    OnchainIntentStatus,
)
from iconomy.peacecoin.chain import TOKEN_ABI

logger = get_logger(__name__)

# Head confirmations before a block is treated as indexable (reorg guard).
CONFIRMATIONS = 3

# Cap per get_logs call so a long gap does not request thousands of blocks.
MAX_BLOCKS_PER_TICK = 2_000

# When the cursor falls further behind than this, catching up block-by-block is
# hopeless: public RPCs prune history (reth answers `pruned history
# unavailable`) and the backlog would take hundreds of ticks. We then skip
# forward to `RESYNC_WINDOW_BLOCKS` behind the head and log the gap loudly, so
# the lost range is auditable. Only reachable after a long outage.
MAX_CURSOR_LAG_BLOCKS = 50_000
RESYNC_WINDOW_BLOCKS = 500


@dataclass(frozen=True)
class SentEventData:
    """Decoded `TokensSentWithMessage`, plus the surrounding tx context."""

    tx_hash: str
    block_number: int
    log_index: int
    occurred_at: datetime
    from_address: str
    to_address: str
    amount: int
    bonus: int
    message: str
    sentiment: int


@dataclass(frozen=True)
class DecayEventData:
    tx_hash: str
    block_number: int
    log_index: int
    wallet: str
    before: int
    after: int


class ChainIndexer:
    """Reads logs from one UAIFAIToken address. Extra read-only cursors can
    be tracked for addresses we do not consume yet (SBT registry on Fase B)."""

    def __init__(
        self,
        database: Database,
        *,
        rpc_url: str,
        token_address: str,
        extra_cursors: list[str] | None = None,
    ) -> None:
        self._database = database
        self._w3 = AsyncWeb3(AsyncHTTPProvider(rpc_url, request_kwargs={"timeout": 10.0}))
        self._token_address = AsyncWeb3.to_checksum_address(token_address)
        self._extra_cursors = [AsyncWeb3.to_checksum_address(a) for a in (extra_cursors or [])]
        self._contract = self._w3.eth.contract(address=self._token_address, abi=TOKEN_ABI)

    async def tick(self) -> int:
        """Returns the number of events materialised this tick."""
        try:
            latest = await self._w3.eth.block_number
        except Exception as exc:
            logger.warning("indexer_rpc_unreachable", error=str(exc))
            return 0
        safe = max(latest - CONFIRMATIONS, 0)

        async with self._database.session() as session:
            # Initialise cursors we have not seen before.
            for addr in [self._token_address, *self._extra_cursors]:
                await self._ensure_cursor(session, addr, safe)

            cursor = await self._get_cursor(session, self._token_address)

            if safe - cursor.last_block > MAX_CURSOR_LAG_BLOCKS:
                skipped_to = safe - RESYNC_WINDOW_BLOCKS
                logger.warning(
                    "indexer_cursor_fast_forwarded",
                    from_block=cursor.last_block,
                    to_block=skipped_to,
                    skipped_blocks=skipped_to - cursor.last_block,
                    reason="cursor lag exceeds what the RPC can serve",
                )
                cursor.last_block = skipped_to

            from_block = cursor.last_block + 1
            if from_block > safe:
                return 0
            to_block = min(safe, from_block + MAX_BLOCKS_PER_TICK - 1)

            try:
                sent_events, decay_events = await self._fetch_logs(from_block, to_block)
            except Exception as exc:
                # Transient RPC failure: leave the cursor alone and retry on the
                # next tick rather than skipping the range.
                logger.warning(
                    "indexer_fetch_failed",
                    from_block=from_block,
                    to_block=to_block,
                    error=str(exc),
                )
                return 0

            applied = 0
            for sent in sent_events:
                applied += await self._apply_sent(session, sent)
            for decay in decay_events:
                logger.info(
                    "decay_applied_indexed",
                    wallet=decay.wallet,
                    before=decay.before,
                    after=decay.after,
                    tx_hash=decay.tx_hash,
                )

            cursor.last_block = to_block
            # Advance the extra cursors too — we are not consuming them yet
            # but we do not want them to lag the main one forever.
            for addr in self._extra_cursors:
                extra = await self._get_cursor(session, addr)
                if to_block > extra.last_block:
                    extra.last_block = to_block
            return applied

    async def _fetch_logs(
        self, from_block: int, to_block: int
    ) -> tuple[list[SentEventData], list[DecayEventData]]:
        sent_raw = await self._contract.events.TokensSentWithMessage.get_logs(
            from_block=from_block, to_block=to_block
        )
        decay_raw = await self._contract.events.DecayApplied.get_logs(
            from_block=from_block, to_block=to_block
        )

        # Cache block timestamps so a batch with many events in the same block
        # only hits `eth_getBlockByNumber` once.
        block_cache: dict[int, datetime] = {}

        async def ts_for(block_number: int) -> datetime:
            if block_number not in block_cache:
                block = await self._w3.eth.get_block(block_number)
                block_cache[block_number] = datetime.fromtimestamp(block["timestamp"], tz=UTC)
            return block_cache[block_number]

        sent = [
            SentEventData(
                tx_hash=to_hex_string(raw["transactionHash"]),
                block_number=int(raw["blockNumber"]),
                log_index=int(raw["logIndex"]),
                occurred_at=await ts_for(int(raw["blockNumber"])),
                from_address=raw["args"]["from"],
                to_address=raw["args"]["to"],
                amount=int(raw["args"]["amount"]),
                bonus=int(raw["args"]["bonus"]),
                message=raw["args"]["message"],
                sentiment=int(raw["args"]["sentiment"]),
            )
            for raw in sent_raw
        ]
        decay = [
            DecayEventData(
                tx_hash=to_hex_string(raw["transactionHash"]),
                block_number=int(raw["blockNumber"]),
                log_index=int(raw["logIndex"]),
                wallet=raw["args"]["wallet"],
                before=int(raw["args"]["before"]),
                after=int(raw["args"]["after_"]),
            )
            for raw in decay_raw
        ]
        return sent, decay

    # The two apply_* methods are also the test seams: inject a prepared
    # SentEventData / DecayEventData and assert the DB side-effects.

    async def _apply_sent(self, session: AsyncSession, event: SentEventData) -> int:
        """Insert the row and confirm any matching outbox intent. Returns 1 on
        a new insert, 0 if the row was already there (idempotency on tx_hash).
        """
        exists = (
            await session.execute(
                select(CirculationEvent.id).where(CirculationEvent.tx_hash == event.tx_hash)
            )
        ).scalar_one_or_none()
        if exists is not None:
            return 0

        sender_user_id = await _resolve_user_id(session, event.from_address)
        recipient_user_id = await _resolve_user_id(session, event.to_address)

        session.add(
            CirculationEvent(
                tx_hash=event.tx_hash,
                block_number=event.block_number,
                log_index=event.log_index,
                sender_address=event.from_address,
                recipient_address=event.to_address,
                sender_user_id=sender_user_id,
                recipient_user_id=recipient_user_id,
                amount=event.amount,
                bonus=event.bonus,
                message=event.message,
                sentiment=event.sentiment,
                occurred_at=event.occurred_at,
            )
        )
        await _reconcile_intent(session, event.tx_hash)
        return 1

    async def _ensure_cursor(self, session: AsyncSession, contract: str, safe: int) -> None:
        row = await self._get_cursor_or_none(session, contract)
        if row is None:
            session.add(IndexerCursor(contract=contract, last_block=safe))
            logger.info("indexer_cursor_initialised", contract=contract, block=safe)
            await session.flush()

    async def _get_cursor(self, session: AsyncSession, contract: str) -> IndexerCursor:
        row = await self._get_cursor_or_none(session, contract)
        assert row is not None, f"cursor for {contract} not initialised"
        return row

    async def _get_cursor_or_none(
        self, session: AsyncSession, contract: str
    ) -> IndexerCursor | None:
        return (
            await session.execute(select(IndexerCursor).where(IndexerCursor.contract == contract))
        ).scalar_one_or_none()


async def _resolve_user_id(session: AsyncSession, address: str) -> uuid.UUID | None:
    """Case-insensitive lookup — EIP-55 vs lowercase hex differ."""
    return (
        await session.execute(
            select(User.id).where(func.lower(User.wallet_address) == address.lower())
        )
    ).scalar_one_or_none()


async def _reconcile_intent(session: AsyncSession, tx_hash: str) -> None:
    """Mark the matching submitted intent as CONFIRMED, if any.

    The outbox stores tx_hash exactly as the adapter returned it; EIP-55
    casing is not guaranteed, so compare case-insensitively.
    """
    await session.execute(
        update(OnchainIntent)
        .where(
            func.lower(OnchainIntent.tx_hash) == tx_hash.lower(),
            OnchainIntent.status == OnchainIntentStatus.SUBMITTED,
        )
        .values(status=OnchainIntentStatus.CONFIRMED)
    )


# Explicit re-export so worker.py's `from iconomy.indexer.service import ChainIndexer`
# still works unchanged.
__all__ = ["CONFIRMATIONS", "ChainIndexer", "DecayEventData", "SentEventData"]


# `Any` is referenced in type hints via dataclass fields read from web3 logs;
# keep the import so mypy does not warn when logs expose `Any`-typed args.
_ = Any
