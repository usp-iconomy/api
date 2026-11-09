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


async def test_signer_account_for_rebuilds_from_store() -> None:
    signer = SignerService(InMemoryKeyStore(), relayer_private_key=None)
    address = await signer.mint_member_account()

    account = await signer.account_for(address)

    assert account is not None
    assert account.address == address


async def test_signer_account_for_unknown_address_is_none() -> None:
    signer = SignerService(InMemoryKeyStore(), relayer_private_key=None)
    assert await signer.account_for("0x0000000000000000000000000000000000000001") is None


async def test_signer_relayer_account_without_key_raises() -> None:
    signer = SignerService(InMemoryKeyStore(), relayer_private_key=None)
    with pytest.raises(RuntimeError, match="Relayer key"):
        _ = signer.relayer_account


async def test_fake_send_with_message_applies_arigato_bonus() -> None:
    adapter = FakePeaceCoin()
    sender = await adapter.create_wallet()
    recipient = await adapter.create_wallet()
    adapter.credit(sender, 1_000)

    tx_hash = await adapter.send_with_message(
        sender, recipient, 100, "mensagem longa o bastante", 0
    )

    # ARIGATO: bonus = amount^2 / balance = 100*100/1000 = 10
    # sender ends with 1000 - 100 + 10 = 910, recipient receives 100.
    assert await adapter.get_balance(sender) == 910
    assert await adapter.get_balance(recipient) == 100
    assert tx_hash.startswith("0x") and len(tx_hash) == 66


async def test_fake_send_with_message_rejects_short_message() -> None:
    adapter = FakePeaceCoin()
    s = await adapter.create_wallet()
    r = await adapter.create_wallet()
    with pytest.raises(ValueError, match="at least 10"):
        await adapter.send_with_message(s, r, 1, "curta", 0)


async def test_fake_send_with_message_rejects_self_transfer() -> None:
    adapter = FakePeaceCoin()
    s = await adapter.create_wallet()
    adapter.credit(s, 100)
    with pytest.raises(ValueError, match="self-transfer"):
        await adapter.send_with_message(s, s, 1, "mensagem longa o bastante", 0)


async def test_fake_send_with_message_rejects_insufficient_balance() -> None:
    adapter = FakePeaceCoin()
    s = await adapter.create_wallet()
    r = await adapter.create_wallet()
    with pytest.raises(ValueError, match="insufficient"):
        await adapter.send_with_message(s, r, 100, "mensagem longa o bastante", 0)


async def test_fake_apply_decay_batch_reduces_balances_by_ten_percent() -> None:
    adapter = FakePeaceCoin()
    a = await adapter.create_wallet()
    b = await adapter.create_wallet()
    adapter.credit(a, 1_000)
    adapter.credit(b, 500)

    await adapter.apply_decay_batch([a, b])

    assert await adapter.get_balance(a) == 900
    assert await adapter.get_balance(b) == 450


async def test_fake_apply_decay_floors_at_zero() -> None:
    adapter = FakePeaceCoin()
    a = await adapter.create_wallet()
    # balance stays at zero after decay; no underflow.
    await adapter.apply_decay_batch([a])
    assert await adapter.get_balance(a) == 0


# --- Gas drip (D2 custodial) ------------------------------------------------


def _chain_adapter_with_balance(balance_wei: int, *, relayer: bytes | None):
    """ChainPeaceCoin whose RPC reports a fixed ETH balance for any address."""
    from unittest.mock import MagicMock

    from iconomy.peacecoin.chain import ChainPeaceCoin

    signer = SignerService(InMemoryKeyStore(), relayer_private_key=relayer)
    adapter = ChainPeaceCoin(
        rpc_url="http://unused",
        token_address="0xeCc07c56B92eb6FcF1Fe276d306D236285721F5B",
        signer=signer,
    )

    sent: list[object] = []

    class _Eth:
        async def get_balance(self, address: str) -> int:
            return balance_wei

        async def send_raw_transaction(self, raw: object) -> object:
            sent.append(raw)
            raise AssertionError("drip should not reach the network in this test")

    fake = MagicMock()
    fake.eth = _Eth()
    adapter._w3 = fake  # type: ignore[assignment]
    return adapter, signer, sent


async def test_ensure_gas_is_a_noop_when_balance_is_sufficient() -> None:
    from iconomy.peacecoin.chain import GAS_DRIP_THRESHOLD_WEI

    adapter, _signer, sent = _chain_adapter_with_balance(GAS_DRIP_THRESHOLD_WEI, relayer=None)
    # No relayer configured, but the balance is fine so no drip is attempted.
    await adapter._ensure_gas("0x" + "1" * 40)
    assert sent == []


async def test_ensure_gas_raises_a_clear_error_without_a_relayer() -> None:
    adapter, _signer, _sent = _chain_adapter_with_balance(0, relayer=None)
    with pytest.raises(RuntimeError, match="no relayer is configured"):
        await adapter._ensure_gas("0x" + "1" * 40)
