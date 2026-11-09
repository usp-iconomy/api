"""Key custody — the only place that holds private keys.

Pilot (D2) is custodial: the API keeps per-member keys plus a relayer key. The
`SignerService` is the single door for anything that signs. Replace the store
with a KMS/HSM-backed implementation before scale; call sites do not change.
"""

from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken
from eth_account import Account
from eth_account.signers.local import LocalAccount

from iconomy.core.db import Database
from iconomy.peacecoin.models import WalletKey


class KeyStore(Protocol):
    """Where per-member private keys live. Returns None if unknown."""

    async def put(self, address: str, private_key: bytes) -> None: ...

    async def get(self, address: str) -> bytes | None: ...


class InMemoryKeyStore:
    """For tests only. Keys vanish with the process, which means any wallet
    provisioned against it becomes unsignable after a restart — use
    `DatabaseKeyStore` anywhere state must outlive the process."""

    def __init__(self) -> None:
        self._keys: dict[str, bytes] = {}

    async def put(self, address: str, private_key: bytes) -> None:
        self._keys[address.lower()] = private_key

    async def get(self, address: str) -> bytes | None:
        return self._keys.get(address.lower())


class DatabaseKeyStore:
    """Persists member keys in Postgres, encrypted with a Fernet key held in
    configuration. Survives restarts and redeploys, which `InMemoryKeyStore`
    does not."""

    def __init__(self, database: Database, *, encryption_key: str) -> None:
        self._database = database
        self._fernet = Fernet(encryption_key.encode())

    async def put(self, address: str, private_key: bytes) -> None:
        token = self._fernet.encrypt(private_key)
        async with self._database.session() as session:
            # Re-provisioning the same address overwrites rather than failing,
            # so a retried provisioning stays idempotent.
            await session.merge(WalletKey(address=address.lower(), ciphertext=token))

    async def get(self, address: str) -> bytes | None:
        async with self._database.session() as session:
            row = await session.get(WalletKey, address.lower())
            if row is None:
                return None
            ciphertext = row.ciphertext
        try:
            return self._fernet.decrypt(ciphertext)
        except InvalidToken:
            # Wrong encryption key for this ciphertext — louder than returning
            # None, which would look like "wallet not provisioned".
            raise RuntimeError(
                f"cannot decrypt the stored key for {address}: "
                "peacecoin_key_encryption_key does not match the one used to store it"
            ) from None


class SignerService:
    """Isolates the relayer key and holds the per-member key store.

    Relayer: gas payer / tx broadcaster. Member keys: sign domain actions
    (`sendWithMessage`, redeem…). This class never exposes raw keys outside.
    """

    def __init__(self, store: KeyStore, *, relayer_private_key: bytes | None) -> None:
        self._store = store
        self._relayer: LocalAccount | None = (
            Account.from_key(relayer_private_key) if relayer_private_key else None
        )

    @property
    def has_relayer(self) -> bool:
        return self._relayer is not None

    @property
    def relayer_address(self) -> str | None:
        return self._relayer.address if self._relayer is not None else None

    @property
    def relayer_account(self) -> LocalAccount:
        """The admin/keeper account. Required for owner-only on-chain calls."""
        if self._relayer is None:
            raise RuntimeError(
                "Relayer key is not configured (settings.peacecoin_relayer_private_key)."
            )
        return self._relayer

    async def mint_member_account(self) -> str:
        """Create a new member account and remember its key. Returns address."""
        account = Account.create()
        address: str = account.address
        await self._store.put(address, bytes(account.key))
        return address

    async def has_member(self, address: str) -> bool:
        return await self._store.get(address) is not None

    async def account_for(self, address: str) -> LocalAccount | None:
        """Rebuild the member's local account from the stored key, or None."""
        key = await self._store.get(address)
        if key is None:
            return None
        account: LocalAccount = Account.from_key(key)
        return account
