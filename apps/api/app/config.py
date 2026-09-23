from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[3] / ".env", extra="ignore")
    api_football_key: str | None = None
    api_basketball_key: str | None = None
    api_football_daily_limit: int | None = None
    api_basketball_daily_limit: int | None = None
    database_url: str = "sqlite:///./slipiq.db"
    redis_url: str | None = None
    app_timezone: str = "Africa/Kampala"
    quota_mode: Literal["free", "standard", "realtime"] = "free"
    live_poll_seconds: int = 60
    prematch_refresh_minutes: int = 30
    odds_refresh_seconds: int = 60
    enable_scheduled_ingestion: bool = False
    api_cors_origins: str = "http://localhost:3000"
    livescore_football_base_url: str = "https://worldcup26.ir"
    enable_livescore_football: bool = True
    enable_easy_soccer_data: bool = False
    the_odds_api_key: str | None = None
    enable_odds_api: bool = False
    odds_prematch_ttl_seconds: int = 1800
    odds_live_ttl_seconds: int = 30
    live_data_stale_seconds: int = 120
    live_stats_stale_seconds: int = 180
    live_odds_stale_seconds: int = 30
    live_refresh_cooldown_seconds: int = 30
    enable_scheduled_live_odds: bool = True
    basketball_period_minutes: int = 12
    basketball_regulation_periods: int = 4
    basketball_overtime_minutes: int = 5
    live_min_quality: float = 0.45
    live_min_confidence: float = 45.0
    min_provider_agreement: float = 0.8
    betpawa_feed_url: str | None = None
    betpawa_api_key: str | None = None

    @field_validator("live_poll_seconds", "prematch_refresh_minutes", "odds_refresh_seconds", "live_data_stale_seconds", "live_stats_stale_seconds", "live_odds_stale_seconds", "live_refresh_cooldown_seconds", "basketball_period_minutes", "basketball_regulation_periods", "basketball_overtime_minutes", "api_football_daily_limit", "api_basketball_daily_limit")
    @classmethod
    def positive_interval(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("intervals must be positive")
        return value

    @field_validator("live_min_quality")
    @classmethod
    def quality_range(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("live_min_quality must be between 0 and 1")
        return value

    @field_validator("live_min_confidence")
    @classmethod
    def confidence_range(cls, value: float) -> float:
        if not 0 <= value <= 100:
            raise ValueError("live_min_confidence must be between 0 and 100")
        return value

    @property
    def provider_daily_limits(self) -> dict[str, int]:
        limits = {"api-football": 100, "api-basketball": 100} if self.quota_mode == "free" else {}
        for provider, value in (("api-football", self.api_football_daily_limit), ("api-basketball", self.api_basketball_daily_limit)):
            if value is not None:
                limits[provider] = value
        return limits

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
