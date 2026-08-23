from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version

import falcon
import falcon.asgi

from iconomy.api.health import LivenessResource, ReadinessResource
from iconomy.config import Settings, get_settings
from iconomy.core.cache import create_redis
from iconomy.core.db import Database
from iconomy.core.errors import (
    AppError,
    handle_app_error,
    handle_http_error,
    handle_unexpected_error,
)
from iconomy.core.logging import configure_logging
from iconomy.core.middleware.lifespan import LifespanMiddleware
from iconomy.core.middleware.request_context import RequestContextMiddleware


def _version() -> str:
    try:
        return pkg_version("usp-iconomy-api")
    except PackageNotFoundError:
        return "0.0.0-dev"


def create_app(settings: Settings | None = None) -> falcon.asgi.App:
    settings = settings or get_settings()

    configure_logging(level=settings.log_level, pretty=settings.is_local)

    database = Database(str(settings.database_url), echo=settings.database_echo)
    redis = create_redis(str(settings.redis_url))

    app = falcon.asgi.App(
        middleware=[
            RequestContextMiddleware(),
            LifespanMiddleware(database, redis),
        ]
    )
    app.req_options.strip_url_path_trailing_slash = True

    app.add_error_handler(Exception, handle_unexpected_error)
    app.add_error_handler(falcon.HTTPError, handle_http_error)
    app.add_error_handler(AppError, handle_app_error)

    app.add_route("/health/live", LivenessResource())
    app.add_route(
        "/health/ready",
        ReadinessResource(database, redis, version=_version()),
    )

    return app
