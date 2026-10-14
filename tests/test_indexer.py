from typing import cast
from unittest.mock import MagicMock

import falcon.util
from sqlalchemy import select

from iconomy.core.db import Database
from iconomy.indexer.models import IndexerCursor
from iconomy.indexer.service import CONFIRMATIONS, ChainIndexer

CONTRACT = "0xeCc07c56B92eb6FcF1Fe276d306D236285721F5B"


def _indexer_with_head(database: Database, head: int) -> ChainIndexer:
    indexer = ChainIndexer(database, rpc_url="http://unused", contracts=[CONTRACT])
    fake = MagicMock()

    class _Eth:
        @property
        def block_number(self) -> object:
            async def _coro() -> int:
                return head

            return _coro()

    fake.eth = _Eth()
    indexer._w3 = cast("object", fake)  # type: ignore[assignment]
    return indexer


def _read_cursor(database: Database) -> IndexerCursor | None:
    async def read() -> IndexerCursor | None:
        async with database.session() as session:
            return (
                await session.execute(
                    select(IndexerCursor).where(IndexerCursor.contract == CONTRACT)
                )
            ).scalar_one_or_none()

    return falcon.util.async_to_sync(read)


def _seed_cursor(database: Database, last_block: int) -> None:
    async def seed() -> None:
        async with database.session() as session:
            session.add(IndexerCursor(contract=CONTRACT, last_block=last_block))

    falcon.util.async_to_sync(seed)


def test_first_tick_initialises_cursor_at_safe_head(database: Database) -> None:
    head = 100
    indexer = _indexer_with_head(database, head)

    falcon.util.async_to_sync(indexer.tick)

    row = _read_cursor(database)
    assert row is not None
    assert row.last_block == head - CONFIRMATIONS


def test_subsequent_tick_advances_cursor(database: Database) -> None:
    _seed_cursor(database, 100)

    indexer = _indexer_with_head(database, 200)
    falcon.util.async_to_sync(indexer.tick)

    row = _read_cursor(database)
    assert row is not None
    assert row.last_block == 200 - CONFIRMATIONS


def test_tick_does_not_rewind_when_head_is_below_cursor(database: Database) -> None:
    _seed_cursor(database, 500)

    indexer = _indexer_with_head(database, 400)
    falcon.util.async_to_sync(indexer.tick)

    row = _read_cursor(database)
    assert row is not None
    assert row.last_block == 500
