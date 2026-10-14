"""In-memory PeaceCoin adapter for tests and `env=local` without a chain."""

import secrets
from collections import defaultdict

from iconomy.peacecoin.signer import SignerService


class FakePeaceCoin:
    """Satisfies PeaceCoinAdapter without touching the network.

    Addresses are random hex, not EIP-55 checksummed — tests should not care.
    Balances start at zero; `credit` lets tests seed them.
    """

    def __init__(self, signer: SignerService | None = None) -> None:
        self._balances: dict[str, int] = defaultdict(int)
        self._signer = signer

    async def create_wallet(self) -> str:
        if self._signer is not None:
            return await self._signer.mint_member_account()
        return "0x" + secrets.token_hex(20)

    async def get_balance(self, address: str) -> int:
        return self._balances[address.lower()]

    async def health(self) -> bool:
        return True

    # Test helper, not part of the Protocol.
    def credit(self, address: str, amount: int) -> None:
        self._balances[address.lower()] += amount
