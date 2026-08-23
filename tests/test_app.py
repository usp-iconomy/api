from iconomy.app import create_app
from iconomy.config import Settings


def test_app_boots_with_health_routes(settings: Settings) -> None:
    app = create_app(settings)

    assert app is not None


def test_explorer_adapter_defaults_to_fake(settings: Settings) -> None:
    assert settings.peacecoin_adapter == "fake"
