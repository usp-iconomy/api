from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version

import falcon
import falcon.asgi
import httpx
from redis.asyncio import Redis

from iconomy.accounts.resources import CurrentUserResource, CurrentUserRoleResource
from iconomy.accounts.service import AccountService
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
from iconomy.core.middleware.authentication import AuthenticationMiddleware
from iconomy.core.middleware.lifespan import LifespanMiddleware
from iconomy.core.middleware.request_context import RequestContextMiddleware
from iconomy.core.security.jwks import KeySource, RemoteKeySource
from iconomy.core.security.tokens import TokenVerifier

JWKS_TIMEOUT_SECONDS = 5.0


def _version() -> str:
    try:
        return pkg_version("usp-iconomy-api")
    except PackageNotFoundError:
        return "0.0.0-dev"


def create_app(
    settings: Settings | None = None,
    *,
    database: Database | None = None,
    redis: Redis | None = None,
    key_source: KeySource | None = None,
) -> falcon.asgi.App:
    settings = settings or get_settings()

    configure_logging(level=settings.log_level, pretty=settings.is_local)

    database = database or Database(str(settings.database_url), echo=settings.database_echo)
    redis = redis or create_redis(str(settings.redis_url))

    http_client: httpx.AsyncClient | None = None
    if key_source is None:
        http_client = httpx.AsyncClient(timeout=JWKS_TIMEOUT_SECONDS)
        key_source = RemoteKeySource(
            settings.jwks_uri,
            client=http_client,
            cache_seconds=settings.oidc_jwks_cache_seconds,
        )

    verifier = TokenVerifier(
        keys=key_source,
        issuer=settings.issuer,
        audience=settings.oidc_audience,
        algorithms=settings.oidc_algorithms,
        leeway_seconds=settings.oidc_leeway_seconds,
    )
    accounts = AccountService(database, institutional_domain=settings.institutional_email_domain)

    app = falcon.asgi.App(
        middleware=[
            RequestContextMiddleware(),
            AuthenticationMiddleware(verifier),
            LifespanMiddleware(database, redis, http_client=http_client),
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

    app.add_route("/auth/me", CurrentUserResource(accounts))
    app.add_route("/auth/me/role", CurrentUserRoleResource(accounts))

    return app
