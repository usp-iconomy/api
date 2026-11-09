"""Read-model of issued SBTs ("Token Alma"), materialised by the indexer from
`SBTIssued`. The chain is the source of truth; this table exists so
`GET /achievements` and the Tipo 4 prerequisite check do not need an RPC call.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from iconomy.core.db import Base


class SoulToken(Base):
    """One row per on-chain SBT.

    `course_id` is the string the contract stores, not a foreign key: the
    on-chain identifier is a free-form string and courses created outside the
    platform would have no matching row.
    """

    __tablename__ = "soul_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    sbt_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    holder_address: Mapped[str] = mapped_column(String(42), index=True)
    holder_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), default=None, index=True
    )
    course_id: Mapped[str] = mapped_column(String(80), index=True)
    # Denormalised at index time so the achievements list needs no join.
    course_title: Mapped[str | None] = mapped_column(String(200), default=None)
    # Named `token_metadata` because `metadata` is reserved on SQLAlchemy
    # declarative classes (`Base.metadata`); the column keeps the plain name.
    token_metadata: Mapped[str] = mapped_column("metadata", Text)
    has_gps: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
