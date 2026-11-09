"""Indexer tick + event handlers. The tick is mocked at the web3 layer; the
event handlers (`_apply_sent`) are called directly with prepared data so we
exercise the SQL side without constructing raw log dicts."""

import uuid
from datetime import UTC, datetime
from typing import cast
from unittest.mock import MagicMock

import falcon.util
from sqlalchemy import select

from iconomy.accounts.models import User
from iconomy.circulation.models import CirculationEvent, Sentiment
from iconomy.core.db import Database
from iconomy.indexer.models import (
    IndexerCursor,
    OnchainIntent,
    OnchainIntentKind,
    OnchainIntentStatus,
)
from iconomy.indexer.service import (
    CONFIRMATIONS,
    ChainIndexer,
    SentEventData,
)

TOKEN = "0xeCc07c56B92eb6FcF1Fe276d306D236285721F5B"


def _indexer(database: Database, head: int) -> ChainIndexer:
    """ChainIndexer wired with a mock web3 that always returns `head` and no logs."""
    indexer = ChainIndexer(database, rpc_url="http://unused", token_address=TOKEN)
    fake = MagicMock()

    class _Eth:
        @property
        def block_number(self) -> object:
            async def _coro() -> int:
                return head

            return _coro()

    fake.eth = _Eth()
    indexer._w3 = cast("object", fake)  # type: ignore[assignment]

    # No logs for the mocked branch — the tick exits after advancing the cursor.
    async def _no_logs(*a: object, **kw: object) -> tuple[list, list]:  # type: ignore[type-arg]
        return [], []

    indexer._fetch_logs = _no_logs  # type: ignore[assignment,method-assign]
    return indexer


def _read_cursor(database: Database) -> IndexerCursor | None:
    async def read() -> IndexerCursor | None:
        async with database.session() as session:
            return (
                await session.execute(select(IndexerCursor).where(IndexerCursor.contract == TOKEN))
            ).scalar_one_or_none()

    return falcon.util.async_to_sync(read)


def _seed_cursor(database: Database, last_block: int) -> None:
    async def seed() -> None:
        async with database.session() as session:
            session.add(IndexerCursor(contract=TOKEN, last_block=last_block))

    falcon.util.async_to_sync(seed)


def test_first_tick_initialises_cursor_at_safe_head(database: Database) -> None:
    head = 100
    indexer = _indexer(database, head)

    falcon.util.async_to_sync(indexer.tick)

    row = _read_cursor(database)
    assert row is not None
    assert row.last_block == head - CONFIRMATIONS


def test_subsequent_tick_advances_cursor(database: Database) -> None:
    _seed_cursor(database, 100)

    indexer = _indexer(database, 200)
    falcon.util.async_to_sync(indexer.tick)

    row = _read_cursor(database)
    assert row is not None
    assert row.last_block == 200 - CONFIRMATIONS


def test_tick_does_not_rewind_when_head_is_below_cursor(database: Database) -> None:
    _seed_cursor(database, 500)

    indexer = _indexer(database, 400)
    falcon.util.async_to_sync(indexer.tick)

    row = _read_cursor(database)
    assert row is not None
    assert row.last_block == 500


# --- Event handler tests (direct) -------------------------------------------


def _seed_user(database: Database, email: str, wallet: str) -> uuid.UUID:
    user_id = uuid.uuid4()

    async def seed() -> None:
        async with database.session() as session:
            session.add(
                User(
                    id=user_id,
                    external_subject=f"sub-{email}",
                    email=email,
                    name=email.split("@")[0],
                    wallet_address=wallet,
                )
            )

    falcon.util.async_to_sync(seed)
    return user_id


def test_apply_sent_inserts_row_and_resolves_user_ids(database: Database) -> None:
    sender_wallet = "0x" + "a" * 40
    recipient_wallet = "0x" + "b" * 40
    sender_id = _seed_user(database, "s@example.org", sender_wallet)
    recipient_id = _seed_user(database, "r@example.org", recipient_wallet)

    indexer = _indexer(database, 999)
    event = SentEventData(
        tx_hash="0x" + "e" * 64,
        block_number=42,
        log_index=0,
        occurred_at=datetime(2026, 10, 18, 12, 0, tzinfo=UTC),
        from_address=sender_wallet,
        to_address=recipient_wallet,
        amount=100 * 10**18,
        bonus=10 * 10**18,
        message="Obrigada!",
        sentiment=Sentiment.POSITIVE.value,
    )

    async def run() -> int:
        async with database.session() as session:
            return await indexer._apply_sent(session, event)

    assert falcon.util.async_to_sync(run) == 1

    # Row materialised with user ids resolved.
    async def read_row() -> CirculationEvent:
        async with database.session() as session:
            return (
                await session.execute(
                    select(CirculationEvent).where(CirculationEvent.tx_hash == event.tx_hash)
                )
            ).scalar_one()

    row = falcon.util.async_to_sync(read_row)
    assert row.sender_user_id == sender_id
    assert row.recipient_user_id == recipient_id
    assert int(row.amount) == 100 * 10**18
    assert row.sentiment == Sentiment.POSITIVE.value


def test_apply_sent_is_idempotent_on_tx_hash(database: Database) -> None:
    indexer = _indexer(database, 999)
    event = SentEventData(
        tx_hash="0x" + "f" * 64,
        block_number=1,
        log_index=0,
        occurred_at=datetime(2026, 10, 1, tzinfo=UTC),
        from_address="0x" + "1" * 40,
        to_address="0x" + "2" * 40,
        amount=1,
        bonus=0,
        message="mensagem longa o bastante",
        sentiment=0,
    )

    async def run_twice() -> list[int]:
        async with database.session() as session:
            first = await indexer._apply_sent(session, event)
        async with database.session() as session:
            second = await indexer._apply_sent(session, event)
        return [first, second]

    assert falcon.util.async_to_sync(run_twice) == [1, 0]


def test_apply_sent_marks_submitted_intent_as_confirmed(database: Database) -> None:
    intent_id = uuid.uuid4()
    tx_hash = "0x" + "9" * 64

    async def seed() -> None:
        async with database.session() as session:
            session.add(
                OnchainIntent(
                    id=intent_id,
                    kind=OnchainIntentKind.SEND_WITH_MESSAGE,
                    idempotency_key=str(intent_id),
                    status=OnchainIntentStatus.SUBMITTED,
                    tx_hash=tx_hash,
                    payload={},
                )
            )

    falcon.util.async_to_sync(seed)

    indexer = _indexer(database, 999)
    event = SentEventData(
        tx_hash=tx_hash.upper(),  # casing differs — reconcile is case-insensitive
        block_number=5,
        log_index=0,
        occurred_at=datetime(2026, 10, 1, tzinfo=UTC),
        from_address="0x" + "3" * 40,
        to_address="0x" + "4" * 40,
        amount=1,
        bonus=0,
        message="mensagem longa o bastante",
        sentiment=0,
    )

    async def run() -> None:
        async with database.session() as session:
            await indexer._apply_sent(session, event)

    falcon.util.async_to_sync(run)

    async def read_intent() -> OnchainIntent:
        async with database.session() as session:
            return (
                await session.execute(select(OnchainIntent).where(OnchainIntent.id == intent_id))
            ).scalar_one()

    intent = falcon.util.async_to_sync(read_intent)
    assert intent.status == OnchainIntentStatus.CONFIRMED


def test_apply_sent_leaves_user_ids_null_for_unknown_addresses(database: Database) -> None:
    indexer = _indexer(database, 999)
    event = SentEventData(
        tx_hash="0x" + "7" * 64,
        block_number=1,
        log_index=0,
        occurred_at=datetime(2026, 10, 1, tzinfo=UTC),
        from_address="0x" + "5" * 40,
        to_address="0x" + "6" * 40,
        amount=10,
        bonus=0,
        message="mensagem longa o bastante",
        sentiment=0,
    )

    async def run() -> None:
        async with database.session() as session:
            await indexer._apply_sent(session, event)

    falcon.util.async_to_sync(run)

    async def row() -> CirculationEvent:
        async with database.session() as session:
            return (
                await session.execute(
                    select(CirculationEvent).where(CirculationEvent.tx_hash == event.tx_hash)
                )
            ).scalar_one()

    r = falcon.util.async_to_sync(row)
    assert r.sender_user_id is None
    assert r.recipient_user_id is None


def test_tick_fast_forwards_when_cursor_lag_exceeds_rpc_window(database: Database) -> None:
    """A cursor weeks behind cannot be caught up block-by-block (public RPCs
    prune history), so the indexer jumps to near-head and logs the gap."""
    from iconomy.indexer.service import MAX_CURSOR_LAG_BLOCKS, RESYNC_WINDOW_BLOCKS

    head = 1_000_000
    stale = head - CONFIRMATIONS - MAX_CURSOR_LAG_BLOCKS - 1
    _seed_cursor(database, stale)

    indexer = _indexer(database, head)
    falcon.util.async_to_sync(indexer.tick)

    row = _read_cursor(database)
    assert row is not None
    # Fast-forwarded to RESYNC_WINDOW behind the safe head, then the empty
    # fetch advanced it the rest of the way to the safe head.
    safe = head - CONFIRMATIONS
    assert row.last_block >= safe - RESYNC_WINDOW_BLOCKS
    assert row.last_block <= safe


def test_tick_keeps_cursor_when_fetch_fails(database: Database) -> None:
    """A transient RPC error must not skip the range."""
    _seed_cursor(database, 100)
    indexer = _indexer(database, 200)

    async def _boom(*a: object, **kw: object) -> tuple[list, list]:  # type: ignore[type-arg]
        raise RuntimeError("rpc exploded")

    indexer._fetch_logs = _boom  # type: ignore[assignment,method-assign]
    assert falcon.util.async_to_sync(indexer.tick) == 0

    row = _read_cursor(database)
    assert row is not None
    assert row.last_block == 100  # unchanged
