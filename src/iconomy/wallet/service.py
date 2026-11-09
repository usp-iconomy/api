from iconomy.accounts.service import AccountService
from iconomy.circulation.repository import CirculationRepository
from iconomy.core.db import Database
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
    """Thin orchestrator — no table of its own in Fase A/B."""

    def __init__(
        self,
        database: Database,
        accounts: AccountService,
        peacecoin: PeaceCoinAdapter,
    ) -> None:
        self._database = database
        self._accounts = accounts
        self._peacecoin = peacecoin

    async def summary_for(self, identity: Identity) -> WalletSummary:
        user = await self._accounts.resolve(identity)
        if not user.wallet_address:
            raise WalletUnavailableError("Your wallet is being provisioned. Try again in a moment.")

        balance_wei = await self._peacecoin.get_balance(user.wallet_address)
        tokens_whole = balance_wei // WEI_PER_TOKEN

        # 30-day sliding circulation (RN-03) from the read-model the indexer
        # materialises. Values are wei-like; convert to whole UAIFAI for the
        # UI, same unit as `token_balance`.
        async with self._database.session() as session:
            circulated_wei = await CirculationRepository(session).circulation_30d(
                user.wallet_address
            )
        circulated_tokens = circulated_wei // WEI_PER_TOKEN

        stars, label = _reputation_stub(tokens_whole)
        return WalletSummary(
            token_balance=tokens_whole,
            circulation_count=circulated_tokens,
            # Soul tokens come with Fase C (RF-05).
            soul_token_count=0,
            reputation_stars=stars,
            reputation_label=label,
        )


def _reputation_stub(tokens: int) -> tuple[ReputationStars, str]:
    """Provisional (Fase A/B). Replaced in Fase D once the indexer serves RF-15."""
    if tokens >= 10_000:
        return 5, "Semeadora"
    if tokens >= 1_000:
        return 4, "Tecelã"
    if tokens >= 100:
        return 3, "Caminhante"
    if tokens >= 10:
        return 2, "Aprendiz"
    return 1, "Recém-chegada"
