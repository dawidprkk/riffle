"""Settings, read from the environment and an optional .env file."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Defaults match docker-compose.yml and are for local development only.
    # Every deployment supplies its own via the environment.
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_user: str = "riffle"
    clickhouse_password: str = "riffle"
    clickhouse_database: str = "riffle"

    redpanda_proxy_url: str = "http://localhost:18082"
    riffle_topic: str = "subscription.events.v1"

    api_cors_origins: str = "http://localhost:5173"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
