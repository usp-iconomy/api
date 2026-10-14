"""On-chain PeaceCoin adapter — reads UAIFAIToken via web3 and mints
member accounts through the SignerService (pilot: custodial).
"""

from __future__ import annotations

from typing import Any

from web3 import AsyncHTTPProvider, AsyncWeb3
from web3.contract import AsyncContract

from iconomy.core.logging import get_logger
from iconomy.peacecoin.signer import SignerService

logger = get_logger(__name__)

# Minimal UAIFAIToken ABI — only what Fase A needs.
# Full ABI lives next to the contract (uaifai-core); we embed the subset we
# actually call so this module does not depend on an artifact file.
TOKEN_ABI: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "balanceOf",
        "stateMutability": "view",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "type": "function",
        "name": "version",
        "stateMutability": "pure",
        "inputs": [],
        "outputs": [{"name": "", "type": "string"}],
    },
]


class ChainPeaceCoin:
    """UAIFAIToken on Sepolia (D4: reads go to the chain for Fase A; later
    phases will route reads through the indexer's read-models)."""

    def __init__(
        self,
        *,
        rpc_url: str,
        token_address: str,
        signer: SignerService,
        request_timeout: float = 10.0,
    ) -> None:
        self._w3 = AsyncWeb3(
            AsyncHTTPProvider(rpc_url, request_kwargs={"timeout": request_timeout})
        )
        self._token_address = AsyncWeb3.to_checksum_address(token_address)
        self._signer = signer
        self._contract: AsyncContract | None = None

    def _token(self) -> AsyncContract:
        if self._contract is None:
            self._contract = self._w3.eth.contract(address=self._token_address, abi=TOKEN_ABI)
        return self._contract

    async def create_wallet(self) -> str:
        return await self._signer.mint_member_account()

    async def get_balance(self, address: str) -> int:
        checksum = AsyncWeb3.to_checksum_address(address)
        return int(await self._token().functions.balanceOf(checksum).call())

    async def health(self) -> bool:
        try:
            await self._w3.eth.chain_id
            return True
        except Exception as exc:
            logger.warning("peacecoin_chain_unreachable", error=str(exc))
            return False
