import pytest

from iconomy.peacecoin.fake import FakePeaceCoin
from iconomy.peacecoin.signer import InMemoryKeyStore, SignerService

pytestmark = pytest.mark.asyncio


async def test_fake_health_is_true() -> None:
    adapter = FakePeaceCoin()
    assert await adapter.health() is True


async def test_fake_create_wallet_without_signer_returns_hex_address() -> None:
    adapter = FakePeaceCoin()
    address = await adapter.create_wallet()
    assert address.startswith("0x")
    assert len(address) == 42


async def test_fake_create_wallet_with_signer_persists_in_keystore() -> None:
    store = InMemoryKeyStore()
    signer = SignerService(store, relayer_private_key=None)
    adapter = FakePeaceCoin(signer=signer)

    address = await adapter.create_wallet()

    assert await signer.has_member(address)


async def test_fake_balance_defaults_to_zero_and_credits_add_up() -> None:
    adapter = FakePeaceCoin()
    address = await adapter.create_wallet()

    assert await adapter.get_balance(address) == 0

    adapter.credit(address, 500)
    adapter.credit(address, 250)
    assert await adapter.get_balance(address) == 750


async def test_signer_without_relayer_key_has_no_relayer() -> None:
    signer = SignerService(InMemoryKeyStore(), relayer_private_key=None)
    assert signer.has_relayer is False
    assert signer.relayer_address is None


async def test_signer_with_relayer_key_exposes_address() -> None:
    # Determined by eth_account; the test only checks the shape.
    relayer_key = bytes.fromhex("4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318")
    signer = SignerService(InMemoryKeyStore(), relayer_private_key=relayer_key)

    assert signer.has_relayer is True
    assert signer.relayer_address is not None
    assert signer.relayer_address.startswith("0x")
