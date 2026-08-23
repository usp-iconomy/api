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

    @field_validator("peacecoin_base_url", "peacecoin_api_key", mode="before")
    @classmethod
    def _empty_string_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def is_local(self) -> bool:
        return self.env in ("local", "ci")


@lru_cache
def get_settings() -> Settings:
    return Settings()
