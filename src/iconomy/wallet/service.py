from iconomy.accounts.service import AccountService
from iconomy.core.errors import AppError
from iconomy.core.security.tokens import Identity
from iconomy.peacecoin.adapter import PeaceCoinAdapter
from iconomy.wallet.schemas import ReputationStars, WalletSummary

# One UAIFAI = 10^18 wei-like units (contract has 18 decimals).
TOKEN_DECIMALS = 18
WEI_PER_TOKEN = 10**TOKEN_DECIMALS


class WalletUnavailableError(AppError):
    status = "503 Service Unavailable"
    code = "wallet_unavailable"
    title = "Wallet is not yet provisioned"


class WalletService:
    """Thin orchestrator — no table of its own in Fase A."""

    def __init__(self, accounts: AccountService, peacecoin: PeaceCoinAdapter) -> None:
        self._accounts = accounts
        self._peacecoin = peacecoin

    async def summary_for(self, identity: Identity) -> WalletSummary:
        user = await self._accounts.resolve(identity)
        if not user.wallet_address:
            raise WalletUnavailableError("Your wallet is being provisioned. Try again in a moment.")

        balance_wei = await self._peacecoin.get_balance(user.wallet_address)
        tokens_whole = balance_wei // WEI_PER_TOKEN

        stars, label = _reputation_stub(tokens_whole)
        return WalletSummary(
            token_balance=tokens_whole,
            # The indexer feeds these in Fase B/D (RF-08, RF-14).
            circulation_count=0,
            soul_token_count=0,
            reputation_stars=stars,
            reputation_label=label,
        )


def _reputation_stub(tokens: int) -> tuple[ReputationStars, str]:
    """Provisional (Fase A). Replaced in Fase D once the indexer serves RF-15."""
    if tokens >= 10_000:
        return 5, "Semeadora"
    if tokens >= 1_000:
        return 4, "Tecelã"
    if tokens >= 100:
        return 3, "Caminhante"
    if tokens >= 10:
        return 2, "Aprendiz"
    return 1, "Recém-chegada"
