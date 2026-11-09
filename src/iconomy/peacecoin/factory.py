"""Build the right PeaceCoin adapter and signer for a Settings instance."""

from iconomy.config import Settings
from iconomy.core.db import Database
from iconomy.core.logging import get_logger
from iconomy.peacecoin.adapter import PeaceCoinAdapter
from iconomy.peacecoin.chain import ChainPeaceCoin
from iconomy.peacecoin.fake import FakePeaceCoin
from iconomy.peacecoin.signer import (
    DatabaseKeyStore,
    InMemoryKeyStore,
    KeyStore,
    SignerService,
)

logger = get_logger(__name__)


def build_signer(settings: Settings, database: Database | None = None) -> SignerService:
    key = settings.peacecoin_relayer_private_key
    raw: bytes | None = None
    if key is not None:
        value = key.get_secret_value().strip()
        if value:
            raw = bytes.fromhex(value.removeprefix("0x"))
    return SignerService(_build_key_store(settings, database), relayer_private_key=raw)


def _build_key_store(settings: Settings, database: Database | None) -> KeyStore:
    """Persist keys whenever we can. Falling back to memory is only safe for
    tests: a restart would strand every member wallet it provisioned."""
    encryption_key = settings.peacecoin_key_encryption_key
    if database is None or encryption_key is None:
        if settings.peacecoin_adapter == "chain":
            logger.warning(
                "key_store_not_persistent",
                detail=("member wallets will be lost on restart; set peacecoin_key_encryption_key"),
            )
        return InMemoryKeyStore()
    return DatabaseKeyStore(database, encryption_key=encryption_key.get_secret_value())


def build_adapter(settings: Settings, signer: SignerService) -> PeaceCoinAdapter:
    choice = settings.peacecoin_adapter
    if choice == "fake":
        return FakePeaceCoin(signer=signer)
    if choice == "chain":
        if settings.peacecoin_rpc_url is None or settings.peacecoin_token_address is None:
            raise RuntimeError(
                "PeaceCoin chain adapter requires peacecoin_rpc_url and peacecoin_token_address."
            )
        return ChainPeaceCoin(
            rpc_url=str(settings.peacecoin_rpc_url),
            token_address=settings.peacecoin_token_address,
            signer=signer,
        )
    # "http" (Peace Coin Explorer) stays open — see IMPLEMENTATION.md §11.
    raise RuntimeError(f"PeaceCoin adapter {choice!r} is not implemented yet.")
