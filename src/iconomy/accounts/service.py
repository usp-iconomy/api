from iconomy.accounts.models import User, UserRole
from iconomy.accounts.repository import UserRepository
from iconomy.core.db import Database
from iconomy.core.errors import ConflictError, ForbiddenError, NotFoundError
from iconomy.core.logging import get_logger
from iconomy.core.security.tokens import Identity
from iconomy.peacecoin.adapter import PeaceCoinAdapter

logger = get_logger(__name__)


class AccountService:
    def __init__(
        self,
        database: Database,
        *,
        institutional_domain: str,
        peacecoin: PeaceCoinAdapter,
    ) -> None:
        self._database = database
        self._institutional_domain = institutional_domain.strip().lower()
        self._peacecoin = peacecoin

    def _is_institutional(self, email: str) -> bool:
        domain = email.rpartition("@")[2]
        return domain == self._institutional_domain or domain.endswith(
            f".{self._institutional_domain}"
        )

    async def resolve(self, identity: Identity) -> User:
        """Return the local member, creating it on first sight.

        Provisioning happens here rather than at sign-up so that members who
        arrive through a federated provider — the USP single sign-on, one day —
        need no separate registration step.
        """
        async with self._database.session() as session:
            users = UserRepository(session)

            user = await users.get_by_subject(identity.subject)
            if user is None:
                user = await self._provision(users, identity)
            else:
                self._refresh_from_identity(user, identity)

            if not user.is_active:
                raise ForbiddenError("This account has been disabled.")

            # Back-fill the wallet when a prior sign-in happened before the
            # chain adapter was reachable. Idempotent: no-op once set.
            await self._ensure_wallet(user)

            # The session does not autoflush, so pending edits must reach the
            # database before `refresh` reads the row back.
            await session.flush()
            await session.refresh(user)
            return user

    async def _provision(self, users: UserRepository, identity: Identity) -> User:
        clash = await users.get_by_email(identity.email)
        if clash is not None:
            logger.warning(
                "email_belongs_to_another_subject",
                email=identity.email,
                subject=identity.subject,
            )
            raise ConflictError("This e-mail already belongs to another account.")

        user = await users.add(
            User(
                external_subject=identity.subject,
                email=identity.email,
                name=identity.name,
                is_institutional=self._is_institutional(identity.email),
            )
        )
        await self._ensure_wallet(user)
        logger.info(
            "member_provisioned",
            subject=identity.subject,
            institutional=user.is_institutional,
            has_wallet=user.wallet_address is not None,
        )
        return user

    async def _ensure_wallet(self, user: User) -> None:
        if user.wallet_address:
            return
        try:
            user.wallet_address = await self._peacecoin.create_wallet()
        except Exception as exc:
            logger.warning(
                "wallet_provisioning_deferred",
                subject=user.external_subject,
                error=str(exc),
            )

    def _refresh_from_identity(self, user: User, identity: Identity) -> None:
        if user.email != identity.email:
            user.email = identity.email
            user.is_institutional = self._is_institutional(identity.email)
        if user.name != identity.name:
            user.name = identity.name

    async def choose_role(self, subject: str, role: UserRole) -> User:
        async with self._database.session() as session:
            users = UserRepository(session)

            user = await users.get_by_subject(subject)
            if user is None:
                raise NotFoundError("No member matches this identity.")
            if not user.is_active:
                raise ForbiddenError("This account has been disabled.")
            if user.role is not None:
                raise ConflictError(
                    "A role has already been chosen for this account.",
                    role=user.role.value,
                )

            user.role = role
            await session.flush()
            await session.refresh(user)
            logger.info("role_chosen", subject=subject, role=role.value)
            return user
