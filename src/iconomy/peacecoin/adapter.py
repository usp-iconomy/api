from typing import Protocol


class PeaceCoinAdapter(Protocol):
    """Minimum surface the API uses to reach the UAIFAI ledger.

    Expands in later phases (sendWithMessage, redeem, SBT, circulation).
    Addresses are 0x-prefixed EIP-55 checksummed strings. Amounts are integer
    wei-like units (18 decimals), never floats.
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
