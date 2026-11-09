"""Enrolments and the evidence behind each one (RF-04).

Every row records *which* access criterion let the member in and the value it
had at that moment, so a later change to the course — or to the member's
circulation — never retroactively invalidates an enrolment.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from iconomy.core.db import Base
from iconomy.courses.models import AccessType

# Circulation is stored in wei-like units, which overflow int64.
UINT256_DIGITS = 78


class EnrollmentStatus(StrEnum):
    ACTIVE = "active"
    # Criteria met and the SBT intent is queued; the indexer flips it to
    # COMPLETED once `SBTIssued` lands. Keeps the completion cron idempotent.
    COMPLETING = "completing"
    COMPLETED = "completed"
    DROPPED = "dropped"


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("user_id", "course_id", name="uq_enrollment_user_course"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("courses.id"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    access_type: Mapped[AccessType] = mapped_column(
        Enum(
            AccessType,
            name="course_access_type",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    status: Mapped[EnrollmentStatus] = mapped_column(
        Enum(
            EnrollmentStatus,
            name="enrollment_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        default=EnrollmentStatus.ACTIVE,
        server_default=EnrollmentStatus.ACTIVE.value,
        index=True,
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Evidence for the criterion used, one column per access type.
    circulation_at_enroll: Mapped[int | None] = mapped_column(
        Numeric(precision=UINT256_DIGITS, scale=0), default=None
    )
    distribution_code_id: Mapped[int | None] = mapped_column(Integer, default=None)
    prerequisite_sbt_id: Mapped[int | None] = mapped_column(Integer, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
