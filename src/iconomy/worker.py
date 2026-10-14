from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from iconomy.config import Settings, get_settings
from iconomy.core.db import Database
from iconomy.core.logging import configure_logging, get_logger
from iconomy.indexer.service import ChainIndexer

logger = get_logger("worker")


async def heartbeat(ctx: dict[str, Any]) -> str:
    healthy = await ctx["database"].ping()
    logger.info("heartbeat", database=healthy)
    return "ok"


async def index_chain_events(ctx: dict[str, Any]) -> None:
    indexer: ChainIndexer | None = ctx.get("indexer")
    if indexer is None:
        # settings.peacecoin_adapter != "chain" — nothing to do.
        return
    await indexer.tick()


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, pretty=settings.is_local)
    ctx["settings"] = settings
    ctx["database"] = Database(str(settings.database_url), echo=settings.database_echo)
    ctx["indexer"] = _build_indexer(settings, ctx["database"])
    logger.info("worker_startup", indexer_enabled=ctx["indexer"] is not None)


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["database"].dispose()
    logger.info("worker_shutdown")


def _build_indexer(settings: Settings, database: Database) -> ChainIndexer | None:
    if settings.peacecoin_adapter != "chain":
        return None
    if settings.peacecoin_rpc_url is None:
        logger.warning("indexer_disabled_missing_rpc_url")
        return None
    contracts = [
        addr
        for addr in (
            settings.peacecoin_token_address,
            settings.peacecoin_sbt_registry_address,
        )
        if addr
    ]
    if not contracts:
        logger.warning("indexer_disabled_missing_contract_addresses")
        return None
    return ChainIndexer(database, rpc_url=str(settings.peacecoin_rpc_url), contracts=contracts)


class WorkerSettings:
    functions: ClassVar[list[Any]] = [heartbeat, index_chain_events]
    cron_jobs: ClassVar[list[Any]] = [
        cron(heartbeat, minute=0, run_at_startup=False),
        # Every 15 seconds: 0,15,30,45 of every minute (RF-08 budget: ≤30s).
        cron(index_chain_events, second={0, 15, 30, 45}, run_at_startup=False),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(str(get_settings().redis_url))
