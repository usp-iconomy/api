"""Peace Coin / UAIFAI chain adapter.

The API talks to the on-chain ledger (UAIFAIToken + UAIFAISBTRegistry on Sepolia)
through this package, never directly. Everything that signs lives behind
`SignerService`. Everything that calls on-chain code lives behind the
`PeaceCoinAdapter` Protocol.

Pilot assumption (D2): custodial with relayer; isolated here so it is
reversible without touching call sites.
"""

from iconomy.peacecoin.adapter import PeaceCoinAdapter
from iconomy.peacecoin.factory import build_adapter, build_signer
from iconomy.peacecoin.fake import FakePeaceCoin
from iconomy.peacecoin.signer import InMemoryKeyStore, KeyStore, SignerService

__all__ = [
    "FakePeaceCoin",
    "InMemoryKeyStore",
    "KeyStore",
    "PeaceCoinAdapter",
    "SignerService",
    "build_adapter",
    "build_signer",
]
