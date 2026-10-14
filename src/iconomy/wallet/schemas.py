from typing import Literal

from iconomy.core.schemas import Schema

ReputationStars = Literal[1, 2, 3, 4, 5]


class WalletSummary(Schema):
    """Shape expected by the web client (see `front/src/types/domain.ts`).

    Fase A fills `token_balance` from the chain; counts and reputation remain
    provisional until the indexer lands in Fase B/D.
    """

    token_balance: int
    circulation_count: int
    soul_token_count: int
    reputation_stars: ReputationStars
    reputation_label: str
