"""Build the right PeaceCoin adapter and signer for a Settings instance."""

from iconomy.config import Settings
from iconomy.peacecoin.adapter import PeaceCoinAdapter
from iconomy.peacecoin.chain import ChainPeaceCoin
from iconomy.peacecoin.fake import FakePeaceCoin
from iconomy.peacecoin.signer import InMemoryKeyStore, SignerService


def build_signer(settings: Settings) -> SignerService:
    key = settings.peacecoin_relayer_private_key
    raw: bytes | None = None
    if key is not None:
        value = key.get_secret_value().strip()
        if value:
            raw = bytes.fromhex(value.removeprefix("0x"))
    return SignerService(InMemoryKeyStore(), relayer_private_key=raw)


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
