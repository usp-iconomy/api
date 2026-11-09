"""Distribution codes (RF-09 scholarships), as both a management record and a
read-model of the on-chain code.

The plain code lives here because the contract only stores
`keccak256(plainCode)` — without it nobody could ever hand the code to a
member. The chain holds the authoritative redemption count; `redemptions_used`
is the indexer's copy.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from iconomy.core.db import Base

UINT256_DIGITS = 78


class DistributionCodeStatus(StrEnum):
    # Intent queued, `createDistributionCode` not confirmed yet — the code
    # cannot be redeemed while in this state.
    PENDING = "pending"
    ACTIVE = "active"
    EXPIRED = "expired"
    EXHAUSTED = "exhausted"


class DistributionCode(Base):
    __tablename__ = "distribution_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Assigned by the contract; filled when `DistributionCodeCreated` is indexed.
    onchain_code_id: Mapped[int | None] = mapped_column(Integer, default=None, index=True)
    code_hash: Mapped[str] = mapped_column(String(66), unique=True)
    plain_code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    # String rather than FK: matches the on-chain `courseId`, which is free-form.
    course_id: Mapped[str | None] = mapped_column(String(80), default=None, index=True)
    tokens_per_redeem: Mapped[int] = mapped_column(Numeric(precision=UINT256_DIGITS, scale=0))
    max_redeems: Mapped[int] = mapped_column(Integer)
    redemptions_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[DistributionCodeStatus] = mapped_column(
        Enum(
            DistributionCodeStatus,
            name="distribution_code_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=DistributionCodeStatus.PENDING,
        server_default=DistributionCodeStatus.PENDING.value,
        index=True,
    )
    created_by: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"))
    intent_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("onchain_intents.id"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
