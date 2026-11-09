"""DatabaseKeyStore — the custodial key store that must survive restarts.

Uses the sync + `async_to_sync` pattern because the `database` fixture is
session-scoped: driving it straight from an async test would cross event
loops and asyncpg refuses that.
"""

import falcon.util
import pytest
from cryptography.fernet import Fernet

from iconomy.core.db import Database
from iconomy.peacecoin.signer import DatabaseKeyStore, SignerService


def _key() -> str:
    return Fernet.generate_key().decode()


def test_round_trips_a_key(database: Database) -> None:
    store = DatabaseKeyStore(database, encryption_key=_key())
    address = "0x" + "A" * 40
    secret = b"\x01" * 32

    falcon.util.async_to_sync(store.put, address, secret)

    assert falcon.util.async_to_sync(store.get, address) == secret
    # Casing must not matter — the chain hands us EIP-55, callers may not.
    assert falcon.util.async_to_sync(store.get, address.lower()) == secret


def test_survives_a_new_instance(database: Database) -> None:
    """Stands in for an API restart: a fresh store with the same encryption
    key must still read the row."""
    key = _key()
    address = "0x" + "B" * 40
    secret = b"\x02" * 32

    falcon.util.async_to_sync(DatabaseKeyStore(database, encryption_key=key).put, address, secret)
    reborn = DatabaseKeyStore(database, encryption_key=key)

    assert falcon.util.async_to_sync(reborn.get, address) == secret


def test_returns_none_for_unknown_address(database: Database) -> None:
    store = DatabaseKeyStore(database, encryption_key=_key())
    assert falcon.util.async_to_sync(store.get, "0x" + "C" * 40) is None


def test_rejects_a_wrong_encryption_key(database: Database) -> None:
    address = "0x" + "D" * 40
    falcon.util.async_to_sync(
        DatabaseKeyStore(database, encryption_key=_key()).put, address, b"\x03" * 32
    )

    wrong = DatabaseKeyStore(database, encryption_key=_key())
    with pytest.raises(RuntimeError, match="does not match"):
        falcon.util.async_to_sync(wrong.get, address)


def test_overwrites_on_reprovision(database: Database) -> None:
    store = DatabaseKeyStore(database, encryption_key=_key())
    address = "0x" + "E" * 40

    falcon.util.async_to_sync(store.put, address, b"\x04" * 32)
    falcon.util.async_to_sync(store.put, address, b"\x05" * 32)

    assert falcon.util.async_to_sync(store.get, address) == b"\x05" * 32


def test_signer_can_sign_after_restart(database: Database) -> None:
    """The whole point: mint a wallet, drop the SignerService, rebuild it, and
    still recover the signing account."""
    key = _key()
    first = SignerService(DatabaseKeyStore(database, encryption_key=key), relayer_private_key=None)
    address = falcon.util.async_to_sync(first.mint_member_account)

    reborn = SignerService(DatabaseKeyStore(database, encryption_key=key), relayer_private_key=None)
    account = falcon.util.async_to_sync(reborn.account_for, address)

    assert account is not None
    assert account.address == address


# --- Hex normalisation (web3 v7 dropped the 0x prefix from .hex()) ----------


def test_to_hex_string_prefixes_bytes() -> None:
    from iconomy.core.hexutil import to_hex_string

    assert to_hex_string(b"\xab\xcd") == "0xabcd"


def test_to_hex_string_leaves_already_prefixed_strings_alone() -> None:
    from iconomy.core.hexutil import to_hex_string

    assert to_hex_string("0xabcd") == "0xabcd"


def test_to_hex_string_prefixes_bare_strings() -> None:
    from iconomy.core.hexutil import to_hex_string

    assert to_hex_string("abcd") == "0xabcd"
