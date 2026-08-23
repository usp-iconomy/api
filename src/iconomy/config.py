from functools import lru_cache
from typing import Literal

from pydantic import HttpUrl, PostgresDsn, RedisDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "ci", "staging", "production"]
PeaceCoinAdapter = Literal["fake", "http"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Environment = "local"
    debug: bool = False
    log_level: str = "INFO"

    database_url: PostgresDsn
    database_echo: bool = False

    redis_url: RedisDsn

    peacecoin_adapter: PeaceCoinAdapter = "fake"
    peacecoin_base_url: HttpUrl | None = None
    peacecoin_api_key: SecretStr | None = None

    oidc_issuer: HttpUrl
    oidc_audience: str = "iconomy-api"
    oidc_jwks_uri: HttpUrl | None = None
    oidc_algorithms: list[str] = ["RS256"]
    oidc_jwks_cache_seconds: int = 300
    oidc_leeway_seconds: int = 10

    institutional_email_domain: str = "usp.br"

    @field_validator("peacecoin_base_url", "peacecoin_api_key", "oidc_jwks_uri", mode="before")
    @classmethod
    def _empty_string_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def is_local(self) -> bool:
        return self.env in ("local", "ci")

    @property
    def jwks_uri(self) -> str:
        if self.oidc_jwks_uri is not None:
            return str(self.oidc_jwks_uri)
        return f"{str(self.oidc_issuer).rstrip('/')}/protocol/openid-connect/certs"

    @property
    def issuer(self) -> str:
        return str(self.oidc_issuer).rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
