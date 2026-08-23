from typing import Any

import falcon
import falcon.asgi

from iconomy.core.logging import get_logger

logger = get_logger(__name__)


class AppError(Exception):
    status: str = falcon.HTTP_500
    code: str = "internal_error"
    title: str = "Internal error"

    def __init__(self, detail: str | None = None, **context: Any) -> None:
        self.detail = detail or self.title
        self.context = context
        super().__init__(self.detail)


class NotFoundError(AppError):
    status = falcon.HTTP_404
    code = "not_found"
    title = "Resource not found"


class ValidationError(AppError):
    status = falcon.HTTP_422
    code = "validation_error"
    title = "Invalid data"


class ConflictError(AppError):
    status = falcon.HTTP_409
    code = "conflict"
    title = "State conflict"


class UnauthorizedError(AppError):
    status = falcon.HTTP_401
    code = "unauthorized"
    title = "Not authenticated"


class ForbiddenError(AppError):
    status = falcon.HTTP_403
    code = "forbidden"
    title = "Access denied"


class UpstreamError(AppError):
    status = falcon.HTTP_502
    code = "upstream_error"
    title = "Upstream service unavailable"


async def handle_app_error(
    req: falcon.asgi.Request,
    resp: falcon.asgi.Response,
    ex: AppError,
    params: dict[str, Any],
) -> None:
    resp.status = ex.status
    resp.content_type = falcon.MEDIA_JSON
    resp.media = {
        "type": f"https://uspiconomy.usp.br/errors/{ex.code}",
        "title": ex.title,
        "status": int(ex.status[:3]),
        "detail": ex.detail,
        "code": ex.code,
        **({"context": ex.context} if ex.context else {}),
    }


async def handle_http_error(
    req: falcon.asgi.Request,
    resp: falcon.asgi.Response,
    ex: falcon.HTTPError,
    params: dict[str, Any],
) -> None:
    resp.status = ex.status
    resp.content_type = falcon.MEDIA_JSON
    resp.media = {
        "type": f"https://uspiconomy.usp.br/errors/http_{ex.status_code}",
        "title": ex.title or ex.status,
        "status": ex.status_code,
        "detail": ex.description or "",
        "code": f"http_{ex.status_code}",
    }


async def handle_unexpected_error(
    req: falcon.asgi.Request,
    resp: falcon.asgi.Response,
    ex: Exception,
    params: dict[str, Any],
) -> None:
    logger.exception("unhandled_error", path=req.path, method=req.method)
    resp.status = falcon.HTTP_500
    resp.content_type = falcon.MEDIA_JSON
    resp.media = {
        "type": "https://uspiconomy.usp.br/errors/internal_error",
        "title": "Internal error",
        "status": 500,
        "detail": "Unexpected error. The incident has been logged.",
        "code": "internal_error",
    }
