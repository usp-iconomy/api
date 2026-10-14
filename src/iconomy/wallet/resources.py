import falcon
import falcon.asgi

from iconomy.core.middleware.authentication import require_identity
from iconomy.wallet.service import WalletService


class CurrentWalletResource:
    def __init__(self, service: WalletService) -> None:
        self._service = service

    async def on_get(self, req: falcon.asgi.Request, resp: falcon.asgi.Response) -> None:
        identity = require_identity(req)
        summary = await self._service.summary_for(identity)
        resp.media = summary.to_media()
