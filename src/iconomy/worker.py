from typing import Any, ClassVar

from arq import cron
from arq.connections import RedisSettings

from iconomy.config import get_settings
from iconomy.core.db import Database
from iconomy.core.logging import configure_logging, get_logger

logger = get_logger("worker")


async def heartbeat(ctx: dict[str, Any]) -> str:
    healthy = await ctx["database"].ping()
    logger.info("heartbeat", database=healthy)
    return "ok"


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, pretty=settings.is_local)
    ctx["settings"] = settings
    ctx["database"] = Database(str(settings.database_url), echo=settings.database_echo)
    logger.info("worker_startup")


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["database"].dispose()
    logger.info("worker_shutdown")


class WorkerSettings:
    functions: ClassVar[list[Any]] = [heartbeat]
    cron_jobs: ClassVar[list[Any]] = [cron(heartbeat, minute=0, run_at_startup=False)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(str(get_settings().redis_url))
