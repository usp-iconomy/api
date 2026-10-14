"""Key custody — the only place that holds private keys.

Pilot (D2) is custodial: the API keeps per-member keys plus a relayer key. The
`SignerService` is the single door for anything that signs. Replace the store
with a KMS/HSM-backed implementation before scale; call sites do not change.
"""

from typing import Protocol

from eth_account import Account
from eth_account.signers.local import LocalAccount


class KeyStore(Protocol):
    """Where per-member private keys live. Returns None if unknown."""

    async def put(self, address: str, private_key: bytes) -> None: ...

    async def get(self, address: str) -> bytes | None: ...


class InMemoryKeyStore:
    """Default for tests and local runs. Not for production — not persistent."""

    def __init__(self) -> None:
        self._keys: dict[str, bytes] = {}

    async def put(self, address: str, private_key: bytes) -> None:
        self._keys[address.lower()] = private_key

    async def get(self, address: str) -> bytes | None:
        return self._keys.get(address.lower())


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

    async def mint_member_account(self) -> str:
        """Create a new member account and remember its key. Returns address."""
        account = Account.create()
        address: str = account.address
        await self._store.put(address, bytes(account.key))
        return address

    async def has_member(self, address: str) -> bool:
        return await self._store.get(address) is not None
