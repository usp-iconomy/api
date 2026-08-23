import falcon.asgi
import structlog

from iconomy.core.errors import UnauthorizedError
from iconomy.core.security.tokens import Identity, TokenVerifier

BEARER = "bearer"


class AuthenticationMiddleware:
    """Never demands authentication — resources do that by calling
    `require_identity`, so public routes stay public.
    """

    def __init__(self, verifier: TokenVerifier) -> None:
        self._verifier = verifier

    async def process_request(self, req: falcon.asgi.Request, resp: falcon.asgi.Response) -> None:
        req.context.identity = None

        header = req.get_header("Authorization")
        if not header:
            return

        scheme, _, token = header.partition(" ")
        if scheme.lower() != BEARER or not token.strip():
            raise UnauthorizedError("Authorization must use the Bearer scheme.")

        identity = await self._verifier.verify(token.strip())
        req.context.identity = identity
        structlog.contextvars.bind_contextvars(subject=identity.subject)


def require_identity(req: falcon.asgi.Request) -> Identity:
    identity: Identity | None = getattr(req.context, "identity", None)
    if identity is None:
        raise UnauthorizedError("This endpoint requires an access token.")
    return identity
