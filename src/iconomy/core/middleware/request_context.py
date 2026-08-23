import time
import uuid
from typing import Any

import falcon.asgi
import structlog

from iconomy.core.logging import get_logger

logger = get_logger("http")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware:
    async def process_request(self, req: falcon.asgi.Request, resp: falcon.asgi.Response) -> None:
        request_id = req.get_header(REQUEST_ID_HEADER) or str(uuid.uuid4())
        req.context.request_id = request_id
        req.context.started_at = time.perf_counter()

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=req.method,
            path=req.path,
        )

    async def process_response(
        self,
        req: falcon.asgi.Request,
        resp: falcon.asgi.Response,
        resource: Any,
        req_succeeded: bool,
    ) -> None:
        request_id = getattr(req.context, "request_id", None)
        if request_id:
            resp.set_header(REQUEST_ID_HEADER, request_id)

        started_at = getattr(req.context, "started_at", None)
        duration_ms = round((time.perf_counter() - started_at) * 1000, 2) if started_at else None

        logger.info(
            "request",
            status=falcon.util.code_to_http_status(resp.status),
            duration_ms=duration_ms,
            succeeded=req_succeeded,
        )
        structlog.contextvars.clear_contextvars()
