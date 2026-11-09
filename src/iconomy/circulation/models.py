"""Read-model for circulation events (Fase B, RF-06/08, RN-01).

Materialised by the indexer from `TokensSentWithMessage` logs. Serves the
feed, the personal extract and the 30-day sliding circulation computation
(RN-03 criterion for course access type 2).
"""

import uuid
from datetime import datetime
from enum import IntEnum

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from iconomy.core.db import Base

# Enough digits for uint256 — log10(2**256) ≈ 77.1.
UINT256_DIGITS = 78


class Sentiment(IntEnum):
    """Matches the `sentiment` field of UAIFAIToken.TokensSentWithMessage."""

    NEUTRAL = 0
    POSITIVE = 1
    NEGATIVE = 2


class CirculationEvent(Base):
    """One `sendWithMessage` as the chain saw it, enriched with user ids.

    Resolution of `sender_user_id` / `recipient_user_id` is best-effort — the
    indexer leaves them `None` when the on-chain address does not match any
    `users.wallet_address`, which happens for admin or external wallets.
    """

    __tablename__ = "circulation_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tx_hash: Mapped[str] = mapped_column(String(66), unique=True, index=True)
    block_number: Mapped[int] = mapped_column(BigInteger)
    log_index: Mapped[int] = mapped_column(Integer)
    sender_address: Mapped[str] = mapped_column(String(42), index=True)
    recipient_address: Mapped[str] = mapped_column(String(42), index=True)
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), default=None, index=True
    )
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), default=None, index=True
    )
    # Postgres `numeric(78, 0)` fits any uint256 the chain can emit.
    # SQLAlchemy still exposes it as `int` on Mapped[int].
    amount: Mapped[int] = mapped_column(Numeric(precision=UINT256_DIGITS, scale=0))
    bonus: Mapped[int] = mapped_column(Numeric(precision=UINT256_DIGITS, scale=0))
    message: Mapped[str] = mapped_column(String(2000))
    sentiment: Mapped[int] = mapped_column(
        SmallInteger, default=Sentiment.NEUTRAL.value, server_default="0"
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    course_id: Mapped[str | None] = mapped_column(String(80), default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
