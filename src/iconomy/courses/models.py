"""Course catalogue, the teacher→admin review flow, and completion rules.

Covers RF-03 (course creation with per-access-type fields) and RF-05
(configurable completion criteria that trigger SBT issuance).
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from iconomy.core.db import Base


class AccessType(StrEnum):
    """RF-04. Values match `AccessType` in front/src/types/domain.ts."""

    OPEN = "open"
    CIRCULATION = "circulation"
    DISTRIBUTION_CODE = "distribution_code"
    SBT = "sbt"


class CourseStatus(StrEnum):
    """Lifecycle of the course itself, which outlives any single submission."""

    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    CHANGES_REQUESTED = "changes_requested"
    PUBLISHED = "published"
    REJECTED = "rejected"


class SubmissionStatus(StrEnum):
    """Status of one review round. Mirrors `CourseReviewStatus` on the wire,
    which has no `draft` — a draft has not been submitted yet."""

    PENDING_REVIEW = "pending_review"
    CHANGES_REQUESTED = "changes_requested"
    PUBLISHED = "published"
    REJECTED = "rejected"


class ReviewDecision(StrEnum):
    """What the admin did. Distinct from the resulting status so the history
    records the action, not just where it landed."""

    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    REJECT = "reject"


def _enum(enum_type: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_type,
        name=name,
        values_callable=lambda e: [m.value for m in e],
    )


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    instructor_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), index=True
    )
    workload_hours: Mapped[int] = mapped_column(Integer)
    # A course may combine access types, e.g. open plus a scholarship code.
    access_types: Mapped[list[str]] = mapped_column(ARRAY(String(32)))

    # Conditional on the access types above.
    min_circulation: Mapped[int | None] = mapped_column(Integer, default=None)
    prerequisite_course_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("courses.id"), default=None
    )
    # Filled once `createDistributionCode` confirms on-chain (Tipo 3).
    distribution_code_id: Mapped[int | None] = mapped_column(Integer, default=None)

    issues_sbt: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    in_person: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    status: Mapped[CourseStatus] = mapped_column(
        _enum(CourseStatus, "course_status"),
        default=CourseStatus.DRAFT,
        server_default=CourseStatus.DRAFT.value,
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CourseSubmission(Base):
    """One review round. A course rejected and resubmitted has two rows."""

    __tablename__ = "course_submissions"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("courses.id"), index=True
    )
    submitted_by: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"))
    status: Mapped[SubmissionStatus] = mapped_column(
        _enum(SubmissionStatus, "course_submission_status"),
        default=SubmissionStatus.PENDING_REVIEW,
        server_default=SubmissionStatus.PENDING_REVIEW.value,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CourseReviewEvent(Base):
    """Append-only history. The UI shows it oldest-first."""

    __tablename__ = "course_review_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("course_submissions.id"), index=True
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("users.id"))
    decision: Mapped[ReviewDecision] = mapped_column(
        _enum(ReviewDecision, "course_review_decision")
    )
    # Required for request_changes and reject; the service enforces the length.
    note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CompletionCriteria(Base):
    """RF-05. Every field is optional: a null criterion is not evaluated, so a
    course with none configured completes as soon as the admin says so.

    `min_attendance_pct` and `required_activities` need attendance tracking,
    which arrives with Fase E — they are stored but not yet evaluated.
    """

    __tablename__ = "completion_criteria"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("courses.id"), unique=True
    )
    min_attendance_pct: Mapped[int | None] = mapped_column(Integer, default=None)
    required_activities: Mapped[int | None] = mapped_column(Integer, default=None)
    min_token_sends: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
