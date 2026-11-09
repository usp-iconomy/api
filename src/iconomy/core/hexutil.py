"""Hex normalisation shared by the chain adapter and the indexer.

`HexBytes.hex()` stopped emitting the `0x` prefix in web3 v7, so values coming
straight off web3 are not interchangeable with the 0x-prefixed form the rest
of the system (and Etherscan, and the `String(66)` columns) expects.
"""


def to_hex_string(value: object) -> str:
    """Return a 0x-prefixed lowercase hex string for bytes-like or str input."""
    raw = value.hex() if isinstance(value, bytes | bytearray) else str(value)
    return raw if raw.startswith("0x") else f"0x{raw}"
