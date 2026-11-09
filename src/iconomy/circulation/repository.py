"""Queries over the circulation read-model."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from iconomy.accounts.models import User
from iconomy.circulation.models import CirculationEvent, Sentiment

SLIDING_WINDOW_DAYS = 30


class EnrichedCirculationEvent(NamedTuple):
    """Row with sender/recipient names resolved by the join."""

    event: CirculationEvent
    sender_name: str
    recipient_name: str


class CirculationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert_event(self, event: CirculationEvent) -> None:
        self._session.add(event)
        await self._session.flush()

    async def list_feed(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        sentiment: Sentiment | None = None,
        since: datetime | None = None,
    ) -> list[EnrichedCirculationEvent]:
        """Public feed, newest first, with sender/recipient names joined in."""
        sender = aliased(User)
        recipient = aliased(User)
        statement = (
            select(
                CirculationEvent,
                func.coalesce(sender.name, "Anônimo"),
                func.coalesce(recipient.name, "Anônimo"),
            )
            .outerjoin(sender, CirculationEvent.sender_user_id == sender.id)
            .outerjoin(recipient, CirculationEvent.recipient_user_id == recipient.id)
            .order_by(CirculationEvent.occurred_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if sentiment is not None:
            statement = statement.where(CirculationEvent.sentiment == sentiment.value)
        if since is not None:
            statement = statement.where(CirculationEvent.occurred_at >= since)

        rows = (await self._session.execute(statement)).all()
        return [EnrichedCirculationEvent(ev, s, r) for ev, s, r in rows]

    async def list_transactions(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EnrichedCirculationEvent]:
        """Member extract: everything they sent or received, newest first."""
        sender = aliased(User)
        recipient = aliased(User)
        statement = (
            select(
                CirculationEvent,
                func.coalesce(sender.name, "Anônimo"),
                func.coalesce(recipient.name, "Anônimo"),
            )
            .outerjoin(sender, CirculationEvent.sender_user_id == sender.id)
            .outerjoin(recipient, CirculationEvent.recipient_user_id == recipient.id)
            .where(
                or_(
                    CirculationEvent.sender_user_id == user_id,
                    CirculationEvent.recipient_user_id == user_id,
                )
            )
            .order_by(CirculationEvent.occurred_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(statement)).all()
        return [EnrichedCirculationEvent(ev, s, r) for ev, s, r in rows]

    async def circulation_30d(self, wallet_address: str) -> int:
        """Sliding window (RN-03): sum of amounts sent in the last 30 days.

        Compares case-insensitively because EIP-55 checksums differ from the
        lowercase hex web3 sometimes returns.
        """
        cutoff = datetime.now(UTC) - timedelta(days=SLIDING_WINDOW_DAYS)
        statement = select(func.coalesce(func.sum(CirculationEvent.amount), 0)).where(
            func.lower(CirculationEvent.sender_address) == wallet_address.lower(),
            CirculationEvent.occurred_at >= cutoff,
        )
        return int((await self._session.execute(statement)).scalar_one())
