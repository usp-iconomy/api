"""Custodial key storage (D2).

The pilot keeps member signing keys server-side. They live here encrypted at
rest with a symmetric key held in configuration — never in the database, so a
database dump alone does not yield signing power.

This is the reversible part of D2: migrating to account abstraction or
meta-transactions removes this table instead of rewriting call sites.
"""

from datetime import datetime

from sqlalchemy import DateTime, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from iconomy.core.db import Base


class WalletKey(Base):
    """One row per member wallet. `ciphertext` is a Fernet token."""

    __tablename__ = "wallet_keys"

    # Lowercased address, so lookups never depend on EIP-55 casing.
    address: Mapped[str] = mapped_column(String(42), primary_key=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
