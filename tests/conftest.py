import pytest
from falcon import testing

from iconomy.app import create_app
from iconomy.config import Settings


@pytest.fixture
def settings() -> Settings:
    return Settings(
        env="ci",
        debug=True,
        log_level="WARNING",
        database_url="postgresql+asyncpg://iconomy:iconomy@localhost:5432/iconomy_test",
        redis_url="redis://localhost:6379/1",
    )


@pytest.fixture
def client(settings: Settings) -> testing.TestClient:
    return testing.TestClient(create_app(settings))
