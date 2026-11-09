"""Outbox processor tests — uses FakePeaceCoin so no network is touched."""

import uuid
from typing import TYPE_CHECKING

import falcon.util
import pytest
from sqlalchemy import select

from iconomy.core.db import Database
from iconomy.indexer.models import OnchainIntent, OnchainIntentKind, OnchainIntentStatus
from iconomy.indexer.outbox import OutboxProcessor

if TYPE_CHECKING:
    from iconomy.peacecoin.fake import FakePeaceCoin


def _enqueue_send(
    database: Database,
    *,
    from_address: str,
    to_address: str,
    amount_wei: int,
    message: str = "mensagem longa o bastante",
    sentiment: int = 0,
) -> uuid.UUID:
    intent_id = uuid.uuid4()

    async def enqueue() -> None:
        async with database.session() as session:
            session.add(
                OnchainIntent(
                    id=intent_id,
                    kind=OnchainIntentKind.SEND_WITH_MESSAGE,
                    idempotency_key=str(intent_id),
                    status=OnchainIntentStatus.PENDING,
                    payload={
                        "from": from_address,
                        "to": to_address,
                        "amount_wei": str(amount_wei),
                        "message": message,
                        "sentiment": sentiment,
                    },
                )
            )

    falcon.util.async_to_sync(enqueue)
    return intent_id


def _get_intent(database: Database, intent_id: uuid.UUID) -> OnchainIntent:
    async def q() -> OnchainIntent:
        async with database.session() as session:
            return (
                await session.execute(select(OnchainIntent).where(OnchainIntent.id == intent_id))
            ).scalar_one()

    return falcon.util.async_to_sync(q)


def test_tick_is_a_noop_when_queue_is_empty(database: Database, peacecoin: "FakePeaceCoin") -> None:
    processor = OutboxProcessor(database, peacecoin)
    assert falcon.util.async_to_sync(processor.tick) == 0


def test_tick_submits_pending_intent_and_marks_submitted(
    database: Database, peacecoin: "FakePeaceCoin"
) -> None:
    sender = "0x" + "1" * 40
    recipient = "0x" + "2" * 40
    peacecoin.credit(sender, 1_000)
    intent_id = _enqueue_send(database, from_address=sender, to_address=recipient, amount_wei=100)

    processor = OutboxProcessor(database, peacecoin)
    assert falcon.util.async_to_sync(processor.tick) == 1

    intent = _get_intent(database, intent_id)
    assert intent.status == OnchainIntentStatus.SUBMITTED
    assert intent.tx_hash is not None
    assert intent.tx_hash.startswith("0x")
    # ARIGATO moved tokens.
    assert falcon.util.async_to_sync(peacecoin.get_balance, recipient) == 100


def test_tick_marks_failed_when_adapter_raises(
    database: Database, peacecoin: "FakePeaceCoin"
) -> None:
    sender = "0x" + "3" * 40
    recipient = "0x" + "4" * 40
    # No credit — fake adapter will raise ValueError("insufficient balance").
    intent_id = _enqueue_send(database, from_address=sender, to_address=recipient, amount_wei=50)

    processor = OutboxProcessor(database, peacecoin)
    falcon.util.async_to_sync(processor.tick)

    # Insufficient balance is treated as transient (state may still arrive), so
    # the intent stays retryable with the reason recorded.
    intent = _get_intent(database, intent_id)
    assert intent.status == OnchainIntentStatus.PENDING
    assert intent.attempts == 1
    assert intent.failure_reason is not None
    assert "insufficient" in intent.failure_reason


def test_tick_skips_already_submitted_intents(
    database: Database, peacecoin: "FakePeaceCoin"
) -> None:
    sender = "0x" + "5" * 40
    recipient = "0x" + "6" * 40
    peacecoin.credit(sender, 100)
    intent_id = _enqueue_send(database, from_address=sender, to_address=recipient, amount_wei=10)

    processor = OutboxProcessor(database, peacecoin)
    # First tick submits.
    falcon.util.async_to_sync(processor.tick)
    first = _get_intent(database, intent_id)
    assert first.status == OnchainIntentStatus.SUBMITTED

    # Second tick finds nothing new; recipient balance stays put.
    assert falcon.util.async_to_sync(processor.tick) == 0


def test_tick_raises_on_unsupported_kind(database: Database, peacecoin: "FakePeaceCoin") -> None:
    intent_id = uuid.uuid4()

    async def enqueue() -> None:
        async with database.session() as session:
            session.add(
                OnchainIntent(
                    id=intent_id,
                    kind=OnchainIntentKind.ADMIN_MINT,  # not wired yet
                    idempotency_key=str(intent_id),
                    status=OnchainIntentStatus.PENDING,
                    payload={},
                )
            )

    falcon.util.async_to_sync(enqueue)

    processor = OutboxProcessor(database, peacecoin)
    falcon.util.async_to_sync(processor.tick)

    # An unknown kind cannot be fixed by retrying, so it fails on attempt one.
    intent = _get_intent(database, intent_id)
    assert intent.status == OnchainIntentStatus.FAILED
    assert intent.attempts == 1
    assert "unsupported" in (intent.failure_reason or "")


# Decay keeper tests here too — shares the same fixtures and style.


class _StubAdapter:
    """Lets us assert *which* wallets the keeper submitted without touching
    FakePeaceCoin's internal balances."""

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    async def apply_decay_batch(self, wallets: list[str]) -> str:
        self.batches.append(list(wallets))
        return "0x" + "a" * 64

    # Unused by the keeper but required by the Protocol — raise if hit.
    async def create_wallet(self) -> str:
        raise AssertionError

    async def get_balance(self, address: str) -> int:
        raise AssertionError

    async def health(self) -> bool:
        raise AssertionError

    async def send_with_message(self, *a: object, **kw: object) -> str:
        raise AssertionError


def test_decay_keeper_submits_all_wallets_in_one_batch(
    client: object, database: Database, as_member: object
) -> None:
    """Provision three members, then decay keeper picks them up."""
    from iconomy.circulation.decay import DecayKeeper

    _seed_users_with_wallets(database, 3)

    stub = _StubAdapter()
    keeper = DecayKeeper(database, stub)  # type: ignore[arg-type]
    scanned = falcon.util.async_to_sync(keeper.tick)
    assert scanned == 3
    assert len(stub.batches) == 1
    assert len(stub.batches[0]) == 3


def test_decay_keeper_is_a_noop_with_zero_wallets(database: Database) -> None:
    from iconomy.circulation.decay import DecayKeeper

    stub = _StubAdapter()
    keeper = DecayKeeper(database, stub)  # type: ignore[arg-type]
    assert falcon.util.async_to_sync(keeper.tick) == 0
    assert stub.batches == []


def _seed_users_with_wallets(database: Database, count: int) -> None:
    from iconomy.accounts.models import User

    async def seed() -> None:
        async with database.session() as session:
            for i in range(count):
                session.add(
                    User(
                        external_subject=f"sub-{i}",
                        email=f"m{i}@example.org",
                        name=f"Member {i}",
                        wallet_address=f"0x{str(i).rjust(40, '0')}",
                    )
                )

    falcon.util.async_to_sync(seed)


# Larger batches get chunked.
def test_decay_keeper_chunks_large_sets(database: Database) -> None:
    from iconomy.circulation.decay import BATCH_SIZE, DecayKeeper

    _seed_users_with_wallets(database, BATCH_SIZE + 5)

    stub = _StubAdapter()
    keeper = DecayKeeper(database, stub)  # type: ignore[arg-type]
    scanned = falcon.util.async_to_sync(keeper.tick)
    assert scanned == BATCH_SIZE + 5
    assert len(stub.batches) == 2
    assert len(stub.batches[0]) == BATCH_SIZE
    assert len(stub.batches[1]) == 5


# Keep pytest happy when running this module without the fake fixture.
pytestmark = pytest.mark.usefixtures("database")


# --- Retry on transient failures -------------------------------------------


class _FlakyAdapter:
    """Fails `fail_times` times, then succeeds. Stands in for a load-balanced
    RPC that is briefly a block behind."""

    def __init__(self, fail_times: int) -> None:
        self.remaining_failures = fail_times
        self.calls = 0

    async def send_with_message(self, *a: object, **kw: object) -> str:
        self.calls += 1
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise RuntimeError("gas required exceeds allowance (0)")
        return "0x" + "b" * 64

    async def create_wallet(self) -> str:
        raise AssertionError

    async def get_balance(self, address: str) -> int:
        raise AssertionError

    async def health(self) -> bool:
        raise AssertionError

    async def apply_decay_batch(self, wallets: list[str]) -> str:
        raise AssertionError


def test_transient_failure_stays_pending_and_succeeds_on_retry(
    database: Database,
) -> None:
    intent_id = _enqueue_send(
        database,
        from_address="0x" + "7" * 40,
        to_address="0x" + "8" * 40,
        amount_wei=10,
    )
    adapter = _FlakyAdapter(fail_times=1)
    processor = OutboxProcessor(database, adapter)  # type: ignore[arg-type]

    # First tick fails but leaves the intent retryable.
    falcon.util.async_to_sync(processor.tick)
    after_first = _get_intent(database, intent_id)
    assert after_first.status == OnchainIntentStatus.PENDING
    assert after_first.attempts == 1

    # Second tick succeeds.
    falcon.util.async_to_sync(processor.tick)
    after_second = _get_intent(database, intent_id)
    assert after_second.status == OnchainIntentStatus.SUBMITTED
    assert after_second.attempts == 2
    assert after_second.tx_hash is not None


def test_failure_becomes_terminal_once_attempts_are_exhausted(
    database: Database,
) -> None:
    from iconomy.indexer.outbox import MAX_ATTEMPTS

    intent_id = _enqueue_send(
        database,
        from_address="0x" + "9" * 40,
        to_address="0x" + "a" * 40,
        amount_wei=10,
    )
    adapter = _FlakyAdapter(fail_times=MAX_ATTEMPTS + 5)
    processor = OutboxProcessor(database, adapter)  # type: ignore[arg-type]

    for _ in range(MAX_ATTEMPTS):
        falcon.util.async_to_sync(processor.tick)

    intent = _get_intent(database, intent_id)
    assert intent.status == OnchainIntentStatus.FAILED
    assert intent.attempts == MAX_ATTEMPTS

    # A terminal intent is no longer picked up.
    assert falcon.util.async_to_sync(processor.tick) == 0
    assert adapter.calls == MAX_ATTEMPTS
