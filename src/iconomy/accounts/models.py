import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from iconomy.core.db import Base


class UserRole(StrEnum):
    STUDENT = "student"
    TEACHER = "teacher"
    ADMIN = "admin"
    DONOR = "donor"


SELF_ASSIGNABLE_ROLES = (UserRole.STUDENT, UserRole.TEACHER, UserRole.DONOR)


class User(Base):
    """Keycloak owns identity; this table owns what the identity means
    inside the domain. `external_subject` is the `sub` claim.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    external_subject: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(150))
    role: Mapped[UserRole | None] = mapped_column(
        Enum(
            UserRole,
            name="user_role",
            values_callable=lambda enum: [member.value for member in enum],
        ),
        default=None,
    )
    is_institutional: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Custodial Peace Coin wallet (RF-01). Null until first provisioning
    # or when the adapter is unavailable at sign-in.
    wallet_address: Mapped[str | None] = mapped_column(String(42), unique=True, default=None)
    community: Mapped[str | None] = mapped_column(String(80), default=None)
    skills_offered: Mapped[list[str]] = mapped_column(
        ARRAY(String(80)), server_default="{}", default=list
    )
    skills_wanted: Mapped[list[str]] = mapped_column(
        ARRAY(String(80)), server_default="{}", default=list
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
