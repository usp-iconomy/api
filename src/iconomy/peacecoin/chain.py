"""On-chain PeaceCoin adapter — reads UAIFAIToken via web3 and mints
member accounts through the SignerService (pilot: custodial).
"""

from __future__ import annotations

import asyncio
from typing import Any

from eth_typing import ChecksumAddress
from web3 import AsyncHTTPProvider, AsyncWeb3
from web3.contract import AsyncContract
from web3.types import TxParams, Wei

from iconomy.core.hexutil import to_hex_string
from iconomy.core.logging import get_logger
from iconomy.peacecoin.signer import SignerService

logger = get_logger(__name__)

# Gas drip (D2 custodial): the relayer funds member wallets on demand so they
# can sign their own `sendWithMessage`. Below the threshold we top up to the
# drip amount — generous enough for a handful of transfers on Sepolia, where
# gas is fractions of a gwei.
GAS_DRIP_THRESHOLD_WEI = 5 * 10**14  # 0.0005 ETH
GAS_DRIP_AMOUNT_WEI = 2 * 10**15  # 0.002 ETH
GAS_DRIP_TIMEOUT_SECONDS = 180
# Load-balanced RPCs can answer the next call from a node a block behind, so we
# confirm the drip is visible before relying on it.
GAS_VISIBILITY_ATTEMPTS = 10
GAS_VISIBILITY_DELAY_SECONDS = 2.0
# Padding over `estimate_gas`, in basis points.
GAS_BUFFER_BPS = 2_000

# Minimal UAIFAIToken ABI — only what the API actually calls.
# Full ABI lives next to the contract (uaifai-core); we embed the subset we
# use so this module does not depend on an artifact file.
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
    {
        "type": "function",
        "name": "sendWithMessage",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "message", "type": "string"},
            {"name": "sentiment", "type": "uint8"},
        ],
        "outputs": [],
    },
    {
        "type": "function",
        "name": "applyDecayBatch",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "wallets", "type": "address[]"}],
        "outputs": [],
    },
    {
        "type": "event",
        "name": "TokensSentWithMessage",
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "from", "type": "address"},
            {"indexed": True, "name": "to", "type": "address"},
            {"indexed": False, "name": "amount", "type": "uint256"},
            {"indexed": False, "name": "bonus", "type": "uint256"},
            {"indexed": False, "name": "message", "type": "string"},
            {"indexed": False, "name": "sentiment", "type": "uint8"},
        ],
    },
    {
        "type": "event",
        "name": "DecayApplied",
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "wallet", "type": "address"},
            {"indexed": False, "name": "before", "type": "uint256"},
            {"indexed": False, "name": "after_", "type": "uint256"},
        ],
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

    async def send_with_message(
        self,
        from_address: str,
        to_address: str,
        amount: int,
        message: str,
        sentiment: int,
    ) -> str:
        """Signed by the sender's own key — the contract credits the ARIGATO
        bonus to `msg.sender`, so a relayer cannot stand in without a
        meta-transaction. Gas comes from the relayer via `_ensure_gas`.
        """
        sender = await self._signer.account_for(from_address)
        if sender is None:
            raise RuntimeError(f"no local key for sender {from_address}")

        await self._ensure_gas(sender.address)

        fn = self._token().functions.sendWithMessage(
            AsyncWeb3.to_checksum_address(to_address),
            amount,
            message,
            sentiment,
        )
        return await self._build_sign_send(sender, fn)

    async def _ensure_gas(self, address: str) -> None:
        """Top the member's EOA up so it can pay for its own transaction.

        Custodial pilot (D2): members never hold ETH, so the relayer drips a
        small amount on demand. Waits for inclusion, because the member's
        transaction is submitted straight after and would otherwise revert
        with "insufficient funds for gas".
        """
        checksum = AsyncWeb3.to_checksum_address(address)
        balance = await self._w3.eth.get_balance(checksum)
        if balance >= GAS_DRIP_THRESHOLD_WEI:
            return

        if not self._signer.has_relayer:
            raise RuntimeError(
                f"{checksum} has no gas and no relayer is configured to fund it "
                "(set peacecoin_relayer_private_key)"
            )
        relayer = self._signer.relayer_account

        # Never hardcode the limit, not even for a plain transfer: Sepolia has
        # answered `estimate_gas` with ~205k for a value-only send to a fresh
        # address, and a tight 21000 burns the whole allowance and reverts.
        estimate: TxParams = {
            "from": relayer.address,
            "to": checksum,
            "value": Wei(GAS_DRIP_AMOUNT_WEI),
        }
        gas = _with_buffer(await self._w3.eth.estimate_gas(estimate))

        signed = relayer.sign_transaction(
            {
                "to": checksum,
                "value": GAS_DRIP_AMOUNT_WEI,
                "nonce": await self._w3.eth.get_transaction_count(relayer.address, "pending"),
                "chainId": await self._w3.eth.chain_id,
                "gasPrice": await self._w3.eth.gas_price,
                "gas": gas,
            }
        )
        tx_hash = await self._w3.eth.send_raw_transaction(signed.raw_transaction)
        await self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=GAS_DRIP_TIMEOUT_SECONDS)
        logger.info(
            "gas_dripped",
            to=checksum,
            amount_wei=GAS_DRIP_AMOUNT_WEI,
            tx_hash=to_hex_string(tx_hash),
        )
        await self._await_gas_visibility(checksum)

    async def _await_gas_visibility(self, checksum: ChecksumAddress) -> None:
        """Block until the dripped funds are visible to the RPC we will query next.

        Public endpoints load-balance across nodes, so the receipt can come from
        one node while the following `estimate_gas` lands on another that is a
        block behind and still reports a zero balance — which fails with
        "gas required exceeds allowance (0)".
        """
        for _ in range(GAS_VISIBILITY_ATTEMPTS):
            if await self._w3.eth.get_balance(checksum) > 0:
                return
            await asyncio.sleep(GAS_VISIBILITY_DELAY_SECONDS)
        logger.warning(
            "gas_drip_not_visible",
            address=checksum,
            waited_seconds=GAS_VISIBILITY_ATTEMPTS * GAS_VISIBILITY_DELAY_SECONDS,
        )

    async def apply_decay_batch(self, wallets: list[str]) -> str:
        """`UAIFAIToken.applyDecayBatch` is permissionless by design — the
        contract documents it as callable by any off-chain keeper — so the
        relayer signs it without needing to own the contract.
        """
        checksummed = [AsyncWeb3.to_checksum_address(w) for w in wallets]
        fn = self._token().functions.applyDecayBatch(checksummed)
        return await self._build_sign_send(self._signer.relayer_account, fn)

    async def _build_sign_send(
        self, account: Any, fn: Any, *, gas_buffer_bps: int = GAS_BUFFER_BPS
    ) -> str:
        """Build an EIP-1559 tx, sign, submit, return 0x-prefixed hash.

        Over-estimates gas by `gas_buffer_bps` (20 % default) to absorb state
        drift between estimate and inclusion. Unspent gas is refunded.
        """
        nonce = await self._w3.eth.get_transaction_count(account.address, "pending")
        chain_id = await self._w3.eth.chain_id

        tx = await fn.build_transaction(
            {
                "from": account.address,
                "nonce": nonce,
                "chainId": chain_id,
            }
        )
        estimated = await self._w3.eth.estimate_gas(tx)
        tx["gas"] = _with_buffer(estimated, gas_buffer_bps)

        signed = account.sign_transaction(tx)
        tx_hash = await self._w3.eth.send_raw_transaction(signed.raw_transaction)
        return to_hex_string(tx_hash)


def _with_buffer(estimated_gas: int, buffer_bps: int = GAS_BUFFER_BPS) -> int:
    """Pad an estimate so state drift between estimate and inclusion does not
    revert the transaction. Unspent gas is refunded, so padding is cheap."""
    return int(estimated_gas * (10_000 + buffer_bps) / 10_000)
