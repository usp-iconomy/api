"""In-memory PeaceCoin adapter for tests and `env=local` without a chain."""

import secrets
from collections import defaultdict

from iconomy.peacecoin.signer import SignerService

# Default decay rate for Fake runs (10%, matches contract default).
DEFAULT_DECAY_BPS = 1000
BPS_DENOMINATOR = 10_000


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

    async def send_with_message(
        self,
        from_address: str,
        to_address: str,
        amount: int,
        message: str,
        sentiment: int,
    ) -> str:
        """Mirror the ARIGATO logic of `UAIFAIToken.sendWithMessage`.

        The on-chain formula is: bonus = (amount * amount) / senderBalance.
        The sender ends with `balance - amount + bonus`; recipient += amount.
        """
        if len(message) < 10:
            raise ValueError("message must have at least 10 characters")
        if from_address.lower() == to_address.lower():
            raise ValueError("self-transfer")
        sender_key = from_address.lower()
        recipient_key = to_address.lower()
        sender_balance = self._balances[sender_key]
        if sender_balance < amount:
            raise ValueError("insufficient balance")
        bonus = (amount * amount) // sender_balance if sender_balance > 0 else 0
        self._balances[sender_key] = sender_balance - amount + bonus
        self._balances[recipient_key] += amount
        return "0x" + secrets.token_hex(32)

    async def apply_decay_batch(self, wallets: list[str]) -> str:
        """Simulate the on-chain decay with a flat 10% reduction. Floors at 0."""
        for addr in wallets:
            key = addr.lower()
            before = self._balances[key]
            after = max(0, before - (before * DEFAULT_DECAY_BPS) // BPS_DENOMINATOR)
            self._balances[key] = after
        return "0x" + secrets.token_hex(32)

    # Test helper, not part of the Protocol.
    def credit(self, address: str, amount: int) -> None:
        self._balances[address.lower()] += amount
