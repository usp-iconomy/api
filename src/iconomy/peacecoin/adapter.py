from typing import Protocol


class PeaceCoinAdapter(Protocol):
    """What the API uses to reach the UAIFAI ledger.

    Addresses are 0x-prefixed EIP-55 checksummed strings. Amounts are integer
    wei-like units (18 decimals), never floats. Mutating calls return the
    submitted transaction hash — the indexer is what tells the API the tx
    actually landed.
    """

    async def create_wallet(self) -> str:
        """Provision a new wallet and return its address."""
        ...

    async def get_balance(self, address: str) -> int:
        """Return the UAIFAI balance of `address` in wei-like units."""
        ...

    async def health(self) -> bool:
        """True when the adapter can reach its backing store (chain or memory)."""
        ...

    async def send_with_message(
        self,
        from_address: str,
        to_address: str,
        amount: int,
        message: str,
        sentiment: int,
    ) -> str:
        """Submit `sendWithMessage(to, amount, message, sentiment)` on behalf
        of `from_address`. The adapter owns the sender's key in custodial mode.
        Returns the transaction hash.
        """
        ...

    async def apply_decay_batch(self, wallets: list[str]) -> str:
        """Submit `applyDecayBatch(wallets)` as owner. Returns the tx hash."""
        ...
