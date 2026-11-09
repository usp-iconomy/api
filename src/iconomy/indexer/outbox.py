"""Outbox processor — drains pending intents and submits them on-chain.

Called by a worker cron. Uses `SELECT ... FOR UPDATE SKIP LOCKED` so multiple
worker replicas never grab the same intent, and crashes mid-batch leave the
lock behind (the next run picks the row up again).
"""

from __future__ import annotations

from sqlalchemy import select

from iconomy.core.db import Database
from iconomy.core.logging import get_logger
from iconomy.indexer.models import OnchainIntent, OnchainIntentKind, OnchainIntentStatus
from iconomy.peacecoin.adapter import PeaceCoinAdapter

logger = get_logger(__name__)

BATCH_SIZE = 10

# How many times to retry a submission before giving up. Keeps a transient RPC
# fault from permanently failing a member's transfer, while still bounding the
# damage from a genuinely broken intent (bad payload, reverting contract call).
MAX_ATTEMPTS = 5


class PermanentIntentError(Exception):
    """Raised for failures retrying cannot fix — an unknown intent kind, a
    malformed payload. These go straight to FAILED instead of burning retries.
    """


class OutboxProcessor:
    def __init__(self, database: Database, peacecoin: PeaceCoinAdapter) -> None:
        self._database = database
        self._peacecoin = peacecoin

    async def tick(self) -> int:
        """One pass over the queue. Returns how many intents it touched."""
        async with self._database.session() as session:
            statement = (
                select(OnchainIntent)
                .where(OnchainIntent.status == OnchainIntentStatus.PENDING)
                .order_by(OnchainIntent.created_at)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
            intents = list((await session.execute(statement)).scalars())
            for intent in intents:
                await self._submit_one(intent)
        return len(intents)

    async def _submit_one(self, intent: OnchainIntent) -> None:
        intent.attempts += 1
        try:
            tx_hash = await self._dispatch(intent)
        except Exception as exc:
            intent.failure_reason = str(exc)[:500]
            terminal = isinstance(exc, PermanentIntentError) or intent.attempts >= MAX_ATTEMPTS
            # Staying PENDING is what makes the next tick pick it up again.
            intent.status = OnchainIntentStatus.FAILED if terminal else OnchainIntentStatus.PENDING
            logger.warning(
                "intent_submission_failed",
                intent_id=str(intent.id),
                kind=intent.kind.value,
                attempts=intent.attempts,
                will_retry=not terminal,
                error=str(exc),
            )
            return
        intent.status = OnchainIntentStatus.SUBMITTED
        intent.tx_hash = tx_hash
        logger.info(
            "intent_submitted",
            intent_id=str(intent.id),
            kind=intent.kind.value,
            tx_hash=tx_hash,
        )

    async def _dispatch(self, intent: OnchainIntent) -> str:
        """Map intent kind → adapter call. Expands with Fase C/D intents."""
        if intent.kind == OnchainIntentKind.SEND_WITH_MESSAGE:
            p = intent.payload
            return await self._peacecoin.send_with_message(
                p["from"],
                p["to"],
                int(p["amount_wei"]),
                p["message"],
                int(p["sentiment"]),
            )
        raise PermanentIntentError(f"unsupported intent kind: {intent.kind.value}")
