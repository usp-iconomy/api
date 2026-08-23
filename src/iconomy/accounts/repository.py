from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from iconomy.accounts.models import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_subject(self, subject: str) -> User | None:
        statement = select(User).where(User.external_subject == subject)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        statement = select(User).where(User.email == email)
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def add(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        return user
