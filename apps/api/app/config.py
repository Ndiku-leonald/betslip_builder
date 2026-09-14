from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    api_football_key: str | None = None
    api_basketball_key: str | None = None
    database_url: str = "sqlite:///./slipiq.db"
    redis_url: str | None = None
    app_timezone: str = "Africa/Kampala"
    quota_mode: Literal["free", "standard", "realtime"] = "free"
    live_poll_seconds: int = 60
    prematch_refresh_minutes: int = 30
    odds_refresh_seconds: int = 60
    enable_scheduled_ingestion: bool = False
    api_cors_origins: str = "http://localhost:3000"

    @field_validator("live_poll_seconds", "prematch_refresh_minutes", "odds_refresh_seconds")
    @classmethod
    def positive_interval(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("intervals must be positive")
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

