from dataclasses import dataclass

import jwt

from iconomy.core.errors import UnauthorizedError
from iconomy.core.security.jwks import KeySource

REQUIRED_CLAIMS = ["exp", "iat", "iss", "aud", "sub"]


@dataclass(frozen=True, slots=True)
class Identity:
    """Carries no domain meaning: the platform role lives in our own
    database, not in the token.
    """

    subject: str
    email: str
    email_verified: bool
    name: str


class TokenVerifier:
    def __init__(
        self,
        *,
        keys: KeySource,
        issuer: str,
        audience: str,
        algorithms: list[str],
        leeway_seconds: int = 0,
    ) -> None:
        self._keys = keys
        self._issuer = issuer
        self._audience = audience
        self._algorithms = algorithms
        self._leeway = leeway_seconds

    async def verify(self, token: str) -> Identity:
        key = await self._signing_key(token)
        try:
            claims = jwt.decode(
                token,
                key.key,
                algorithms=self._algorithms,
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": REQUIRED_CLAIMS},
            )
        except jwt.PyJWTError as ex:
            raise UnauthorizedError("The access token is invalid or has expired.") from ex

        email = claims.get("email")
        if not email:
            raise UnauthorizedError("The access token carries no email claim.")

        return Identity(
            subject=str(claims["sub"]),
            email=str(email).strip().lower(),
            email_verified=bool(claims.get("email_verified", False)),
            name=str(claims.get("name") or claims.get("preferred_username") or email),
        )

    async def _signing_key(self, token: str) -> jwt.PyJWK:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.PyJWTError as ex:
            raise UnauthorizedError("The access token is malformed.") from ex

        if not kid:
            raise UnauthorizedError("The access token does not name a signing key.")

        key = await self._keys.get(str(kid))
        if key is None:
            # The realm may have rotated its keys since the last fetch.
            key = await self._keys.get(str(kid), force_refresh=True)
        if key is None:
            raise UnauthorizedError("The access token was signed by an unknown key.")
        return key
