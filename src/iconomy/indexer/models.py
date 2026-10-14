"""Outbox + indexer tables (IMPLEMENTATION.md §7.A5, D4/D5)."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from iconomy.core.db import Base


class OnchainIntentKind(StrEnum):
    """What the API asked the relayer to do (expands in later phases)."""

    SEND_WITH_MESSAGE = "send_with_message"
    REDEEM_DISTRIBUTION_CODE = "redeem_distribution_code"
    ISSUE_SBT = "issue_sbt"
    ADMIN_MINT = "admin_mint"


class OnchainIntentStatus(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class OnchainIntent(Base):
    """Transactional outbox: an API action's wish for a chain mutation.

    A worker drains it, submits via SignerService and reconciles on the
    corresponding chain event. Idempotent via `idempotency_key`.
    """

    __tablename__ = "onchain_intents"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    kind: Mapped[OnchainIntentKind] = mapped_column(
        Enum(
            OnchainIntentKind,
            name="onchain_intent_kind",
            values_callable=lambda enum: [m.value for m in enum],
        ),
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    status: Mapped[OnchainIntentStatus] = mapped_column(
        Enum(
            OnchainIntentStatus,
            name="onchain_intent_status",
            values_callable=lambda enum: [m.value for m in enum],
        ),
        default=OnchainIntentStatus.PENDING,
        server_default=OnchainIntentStatus.PENDING.value,
    )
    tx_hash: Mapped[str | None] = mapped_column(String(66), default=None)
    failure_reason: Mapped[str | None] = mapped_column(String(500), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class IndexerCursor(Base):
    """Last block processed per contract. One row per (contract) address."""

    __tablename__ = "indexer_cursor"

    contract: Mapped[str] = mapped_column(String(42), primary_key=True)
    last_block: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
