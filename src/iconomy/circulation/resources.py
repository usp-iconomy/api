import uuid

import falcon
import falcon.asgi

from iconomy.accounts.models import UserRole
from iconomy.accounts.service import AccountService
from iconomy.circulation.models import Sentiment
from iconomy.circulation.schemas import SendRequest
from iconomy.circulation.service import CirculationService
from iconomy.core.errors import ForbiddenError, ValidationError
from iconomy.core.middleware.authentication import require_identity
from iconomy.core.schemas import read_body

MAX_PAGE = 100
DEFAULT_PAGE = 50

# Members who can originate a transfer. Admin is left out — admin flows go
# through the backoffice, not /circulation/send.
SENDER_ROLES: frozenset[UserRole] = frozenset({UserRole.STUDENT, UserRole.TEACHER})


def _page(req: falcon.asgi.Request) -> tuple[int, int]:
    """Pull `limit` and `offset` from query string, bounded to sane values."""
    try:
        limit = int(req.get_param("limit") or DEFAULT_PAGE)
        offset = int(req.get_param("offset") or 0)
    except ValueError as exc:
        raise ValidationError("limit and offset must be integers.") from exc
    limit = max(1, min(limit, MAX_PAGE))
    offset = max(0, offset)
    return limit, offset


class CirculationFeedResource:
    """GET /circulation — public feed, filterable by sentiment/since."""

    def __init__(self, service: CirculationService) -> None:
        self._service = service

    async def on_get(self, req: falcon.asgi.Request, resp: falcon.asgi.Response) -> None:
        require_identity(req)
        limit, offset = _page(req)

        sentiment_param = req.get_param("sentiment")
        sentiment: Sentiment | None = None
        if sentiment_param is not None:
            try:
                sentiment = Sentiment(int(sentiment_param))
            except (ValueError, KeyError) as exc:
                raise ValidationError("sentiment must be 0, 1 or 2.") from exc

        since = req.get_param_as_datetime("since")
        entries = await self._service.list_feed(
            limit=limit, offset=offset, sentiment=sentiment, since=since
        )
        resp.media = [e.to_media() for e in entries]


class TransactionsResource:
    """GET /circulation/transactions — personal extract."""

    def __init__(self, service: CirculationService, accounts: AccountService) -> None:
        self._service = service
        self._accounts = accounts

    async def on_get(self, req: falcon.asgi.Request, resp: falcon.asgi.Response) -> None:
        identity = require_identity(req)
        user = await self._accounts.resolve(identity)
        limit, offset = _page(req)
        txs = await self._service.list_transactions(user, limit=limit, offset=offset)
        resp.media = [t.to_media() for t in txs]


class IntentStatusResource:
    """GET /circulation/intents/{intent_id} — the form polls this to show
    pending → submitted → confirmed."""

    def __init__(self, service: CirculationService, accounts: AccountService) -> None:
        self._service = service
        self._accounts = accounts

    async def on_get(
        self, req: falcon.asgi.Request, resp: falcon.asgi.Response, intent_id: str
    ) -> None:
        identity = require_identity(req)
        user = await self._accounts.resolve(identity)
        try:
            parsed = uuid.UUID(intent_id)
        except ValueError as exc:
            raise ValidationError("intent_id must be a UUID.") from exc
        resp.media = (await self._service.intent_status(user, parsed)).to_media()


class SendResource:
    """POST /circulation/send — enqueues an intent (202, not 200)."""

    def __init__(self, service: CirculationService, accounts: AccountService) -> None:
        self._service = service
        self._accounts = accounts

    async def on_post(self, req: falcon.asgi.Request, resp: falcon.asgi.Response) -> None:
        identity = require_identity(req)
        user = await self._accounts.resolve(identity)
        if user.role not in SENDER_ROLES:
            raise ForbiddenError("Only students and teachers can send tokens.")

        body = await read_body(req, SendRequest)
        response = await self._service.send(user, body)
        resp.status = falcon.HTTP_202
        resp.media = response.to_media()
