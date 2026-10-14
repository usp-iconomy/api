import uuid
from datetime import datetime

from pydantic import EmailStr, field_validator

from iconomy.accounts.models import SELF_ASSIGNABLE_ROLES, UserRole
from iconomy.core.schemas import Schema


class UserResponse(Schema):
    id: uuid.UUID
    email: EmailStr
    name: str
    role: UserRole | None
    is_institutional: bool
    wallet_address: str | None
    community: str | None
    skills_offered: list[str]
    skills_wanted: list[str]
    created_at: datetime

    @property
    def onboarding_required(self) -> bool:
        return self.role is None


class CurrentUserResponse(Schema):
    user: UserResponse
    onboarding_required: bool
    email_verified: bool


class ChooseRoleRequest(Schema):
    role: UserRole

    @field_validator("role")
    @classmethod
    def _must_be_self_assignable(cls, value: UserRole) -> UserRole:
        if value not in SELF_ASSIGNABLE_ROLES:
            allowed = ", ".join(role.value for role in SELF_ASSIGNABLE_ROLES)
            raise ValueError(f"role must be one of: {allowed}")
        return value
