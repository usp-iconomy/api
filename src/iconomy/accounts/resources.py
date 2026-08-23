import falcon
import falcon.asgi

from iconomy.accounts.schemas import ChooseRoleRequest, CurrentUserResponse, UserResponse
from iconomy.accounts.service import AccountService
from iconomy.core.middleware.authentication import require_identity
from iconomy.core.schemas import read_body


class CurrentUserResource:
    def __init__(self, service: AccountService) -> None:
        self._service = service

    async def on_get(self, req: falcon.asgi.Request, resp: falcon.asgi.Response) -> None:
        identity = require_identity(req)
        user = await self._service.resolve(identity)
        profile = UserResponse.model_validate(user)

        resp.media = CurrentUserResponse(
            user=profile,
            onboarding_required=profile.onboarding_required,
            email_verified=identity.email_verified,
        ).to_media()


class CurrentUserRoleResource:
    def __init__(self, service: AccountService) -> None:
        self._service = service

    async def on_post(self, req: falcon.asgi.Request, resp: falcon.asgi.Response) -> None:
        identity = require_identity(req)
        body = await read_body(req, ChooseRoleRequest)

        # Provisioning first, so this works even as the very first call a
        # freshly registered member makes.
        await self._service.resolve(identity)
        user = await self._service.choose_role(identity.subject, body.role)

        resp.media = UserResponse.model_validate(user).to_media()
