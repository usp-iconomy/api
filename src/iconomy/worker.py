from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from iconomy.circulation.decay import DecayKeeper
from iconomy.config import Settings, get_settings
from iconomy.core.db import Database
from iconomy.core.logging import configure_logging, get_logger
from iconomy.indexer.outbox import OutboxProcessor
from iconomy.indexer.service import ChainIndexer
from iconomy.peacecoin import PeaceCoinAdapter, SignerService, build_adapter, build_signer

logger = get_logger("worker")


async def heartbeat(ctx: dict[str, Any]) -> str:
    healthy = await ctx["database"].ping()
    logger.info("heartbeat", database=healthy)
    return "ok"


async def index_chain_events(ctx: dict[str, Any]) -> None:
    indexer: ChainIndexer | None = ctx.get("indexer")
    if indexer is None:
        return
    await indexer.tick()


async def process_pending_intents(ctx: dict[str, Any]) -> int:
    outbox: OutboxProcessor | None = ctx.get("outbox")
    if outbox is None:
        return 0
    return await outbox.tick()


async def decay_keeper(ctx: dict[str, Any]) -> int:
    keeper: DecayKeeper | None = ctx.get("decay_keeper")
    if keeper is None:
        return 0
    return await keeper.tick()


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, pretty=settings.is_local)
    ctx["settings"] = settings
    ctx["database"] = Database(str(settings.database_url), echo=settings.database_echo)
    ctx["signer"] = build_signer(settings, ctx["database"])
    ctx["peacecoin"] = _build_peacecoin(settings, ctx["signer"])
    ctx["outbox"] = OutboxProcessor(ctx["database"], ctx["peacecoin"]) if ctx["peacecoin"] else None
    ctx["decay_keeper"] = (
        DecayKeeper(ctx["database"], ctx["peacecoin"]) if ctx["peacecoin"] else None
    )
    ctx["indexer"] = _build_indexer(settings, ctx["database"])
    logger.info(
        "worker_startup",
        indexer_enabled=ctx["indexer"] is not None,
        outbox_enabled=ctx["outbox"] is not None,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["database"].dispose()
    logger.info("worker_shutdown")


def _build_peacecoin(settings: Settings, signer: SignerService) -> PeaceCoinAdapter | None:
    """Only wire the adapter if the chain config is complete. The outbox and
    decay keeper opt out when it is missing — their cron becomes a no-op."""
    if settings.peacecoin_adapter != "chain":
        # Fake adapter cannot submit to a real chain; outbox needs chain here.
        # (Fase B dev runs call the fake adapter directly from HTTP tests.)
        return None
    if settings.peacecoin_rpc_url is None or settings.peacecoin_token_address is None:
        logger.warning("outbox_disabled_missing_chain_config")
        return None
    return build_adapter(settings, signer)


def _build_indexer(settings: Settings, database: Database) -> ChainIndexer | None:
    if settings.peacecoin_adapter != "chain":
        return None
    if settings.peacecoin_rpc_url is None:
        logger.warning("indexer_disabled_missing_rpc_url")
        return None
    if settings.peacecoin_token_address is None:
        logger.warning("indexer_disabled_missing_token_address")
        return None
    sbt = settings.peacecoin_sbt_registry_address
    extras = [sbt] if sbt else []
    return ChainIndexer(
        database,
        rpc_url=str(settings.peacecoin_rpc_url),
        token_address=settings.peacecoin_token_address,
        extra_cursors=extras,
    )


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        heartbeat,
        index_chain_events,
        process_pending_intents,
        decay_keeper,
    ]
    cron_jobs: ClassVar[list[Any]] = [
        cron(heartbeat, minute=0, run_at_startup=False),
        # Indexer every 15 seconds (RF-08 budget: ≤30s).
        cron(index_chain_events, second={0, 15, 30, 45}, run_at_startup=False),
        # Outbox every 20 seconds (10, 30, 50 interleave with the indexer).
        cron(process_pending_intents, second={10, 30, 50}, run_at_startup=False),
        # Decay daily at 03:00 UTC (RN-01).
        cron(decay_keeper, hour=3, minute=0, run_at_startup=False),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(str(get_settings().redis_url))
