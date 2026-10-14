import json
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import falcon.util
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from falcon import testing
from sqlalchemy import text

from iconomy.accounts import models  # noqa: F401  (registers the tables on Base)
from iconomy.app import create_app
from iconomy.config import Settings
from iconomy.core.db import Base, Database
from iconomy.indexer import models as indexer_models  # noqa: F401  (same)

ISSUER = "https://identity.test/realms/iconomy"
AUDIENCE = "iconomy-api"
SIGNING_KID = "test-signing-key"
TEST_DATABASE = "iconomy_test"

TokenFactory = Callable[..., str]


class StaticKeySource:
    """Stands in for the realm's JWKS so tests need no Keycloak and no network."""

    def __init__(self, *keys: jwt.PyJWK) -> None:
        self._keys = {key.key_id: key for key in keys}

    async def get(self, kid: str, *, force_refresh: bool = False) -> jwt.PyJWK | None:
        return self._keys.get(kid)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        env="ci",
        debug=True,
        log_level="WARNING",
        database_url=f"postgresql+asyncpg://iconomy:iconomy@localhost:5432/{TEST_DATABASE}",
        redis_url="redis://localhost:6380/1",
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
    )


@pytest.fixture(scope="session")
def signing_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def key_source(signing_key: rsa.RSAPrivateKey) -> StaticKeySource:
    document: dict[str, Any] = json.loads(
        jwt.algorithms.RSAAlgorithm.to_jwk(signing_key.public_key())
    )
    document |= {"kid": SIGNING_KID, "alg": "RS256", "use": "sig"}
    return StaticKeySource(jwt.PyJWK(document, algorithm="RS256"))


@pytest.fixture
def issue_token(signing_key: rsa.RSAPrivateKey) -> TokenFactory:
    """Mint an access token shaped like the ones the realm issues."""

    def factory(
        *,
        subject: str | None = None,
        email: str = "membro@example.org",
        name: str = "Membro de Teste",
        expires_in: timedelta = timedelta(minutes=15),
        key: rsa.RSAPrivateKey | None = None,
        kid: str = SIGNING_KID,
        **overrides: Any,
    ) -> str:
        now = datetime.now(UTC)
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": subject or str(uuid.uuid4()),
            "iat": int(now.timestamp()),
            "exp": int((now + expires_in).timestamp()),
            "email": email,
            "email_verified": True,
            "name": name,
            "preferred_username": email,
        }
        claims.update(overrides)
        claims = {key_: value for key_, value in claims.items() if value is not None}
        return jwt.encode(claims, key or signing_key, algorithm="RS256", headers={"kid": kid})

    return factory


async def _create_database_if_missing(dsn: str) -> None:
    connection = await asyncpg.connect(dsn)
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DATABASE
        )
        if not exists:
            await connection.execute(f'CREATE DATABASE "{TEST_DATABASE}"')
    finally:
        await connection.close()


@pytest.fixture(scope="session")
def database(settings: Settings) -> Iterator[Database]:
    maintenance_dsn = "postgresql://iconomy:iconomy@localhost:5432/postgres"
    falcon.util.async_to_sync(_create_database_if_missing, maintenance_dsn)

    db = Database(str(settings.database_url))

    async def build_schema() -> None:
        async with db.engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)

    falcon.util.async_to_sync(build_schema)
    yield db
    falcon.util.async_to_sync(db.dispose)


@pytest.fixture(autouse=True)
def clean_tables(database: Database) -> None:
    tables = ", ".join(table.name for table in reversed(Base.metadata.sorted_tables))

    async def truncate() -> None:
        async with database.engine.begin() as connection:
            await connection.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))

    falcon.util.async_to_sync(truncate)


@pytest.fixture
def client(
    settings: Settings, database: Database, key_source: StaticKeySource
) -> testing.TestClient:
    return testing.TestClient(create_app(settings, database=database, key_source=key_source))


@pytest.fixture
def as_member(issue_token: TokenFactory) -> Callable[..., dict[str, str]]:
    """Authorization header for a member, minting a token on the fly."""

    def headers(**kwargs: Any) -> dict[str, str]:
        return {"Authorization": f"Bearer {issue_token(**kwargs)}"}

    return headers
