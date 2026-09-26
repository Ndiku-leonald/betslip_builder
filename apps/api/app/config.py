from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[3] / ".env", extra="ignore")
    app_env: Literal["development", "test", "production"] = "development"
    app_process_role: Literal["web", "worker"] = "web"
    log_level: str = "INFO"
    app_version: str = "0.1.0"
    release: str | None = None
    api_football_key: str | None = None
    api_basketball_key: str | None = None
    api_sports_key: str | None = None
    api_football_base_url: str = "https://v3.football.api-sports.io"
    api_basketball_base_url: str = "https://v1.basketball.api-sports.io"
    api_football_daily_limit: int | None = None
    api_basketball_daily_limit: int | None = None
    football_data_api_key: str | None = None
    football_data_base_url: str = "https://api.football-data.org/v4"
    football_data_daily_limit: int | None = None
    additional_provider_1_name: str | None = None
    additional_provider_1_sports: str | None = None
    additional_provider_1_base_url: str | None = None
    additional_provider_1_api_key: str | None = None
    additional_provider_1_auth_header: str = "Authorization"
    additional_provider_1_adapter: str = "pending"
    additional_provider_2_name: str | None = None
    additional_provider_2_sports: str | None = None
    additional_provider_2_base_url: str | None = None
    additional_provider_2_api_key: str | None = None
    additional_provider_2_auth_header: str = "Authorization"
    additional_provider_2_adapter: str = "pending"
    additional_provider_3_name: str | None = None
    additional_provider_3_sports: str | None = None
    additional_provider_3_base_url: str | None = None
    additional_provider_3_api_key: str | None = None
    additional_provider_3_auth_header: str = "Authorization"
    additional_provider_3_adapter: str = "pending"
    additional_provider_4_name: str | None = None
    additional_provider_4_sports: str | None = None
    additional_provider_4_base_url: str | None = None
    additional_provider_4_api_key: str | None = None
    additional_provider_4_auth_header: str = "Authorization"
    additional_provider_4_adapter: str = "pending"
    additional_provider_5_name: str | None = None
    additional_provider_5_sports: str | None = None
    additional_provider_5_base_url: str | None = None
    additional_provider_5_api_key: str | None = None
    additional_provider_5_auth_header: str = "Authorization"
    additional_provider_5_adapter: str = "pending"
    additional_provider_6_name: str | None = None
    additional_provider_6_sports: str | None = None
    additional_provider_6_base_url: str | None = None
    additional_provider_6_api_key: str | None = None
    additional_provider_6_auth_header: str = "Authorization"
    additional_provider_6_adapter: str = "pending"
    database_url: str = "sqlite:///./slipiq.db"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800
    redis_url: str | None = None
    redis_required_in_production: bool = True
    redis_key_prefix: str = "slipiq"
    app_timezone: str = "Africa/Kampala"
    quota_mode: Literal["free", "standard", "realtime"] = "free"
    live_poll_seconds: int = 60
    prematch_refresh_minutes: int = 30
    odds_refresh_seconds: int = 60
    enable_scheduled_ingestion: bool = False
    api_cors_origins: str = "http://localhost:3000"
    allowed_origins: str | None = None
    trusted_hosts: str = "localhost,127.0.0.1"
    api_rate_limit_enabled: bool = True
    api_rate_limit_requests: int = 60
    api_rate_limit_window_seconds: int = 60
    expensive_rate_limit_requests: int = 10
    expensive_rate_limit_window_seconds: int = 60
    admin_token: str | None = None
    enable_admin_endpoints: bool = True
    enable_api_docs: bool = True
    max_request_body_bytes: int = 1_000_000
    request_id_max_length: int = 96
    strict_security_headers: bool = True
    metrics_enabled: bool = True
    provider_connect_timeout: float = 5.0
    provider_read_timeout: float = 15.0
    provider_retry_attempts: int = 3
    provider_retry_base_seconds: float = 0.5
    provider_circuit_failure_threshold: int = 5
    provider_circuit_cooldown_seconds: int = 30
    livescore_football_base_url: str = "https://worldcup26.ir"
    enable_livescore_football: bool = True
    enable_easy_soccer_data: bool = False
    the_odds_api_key: str | None = None
    the_odds_api_base_url: str = "https://api.the-odds-api.com/v4"
    the_odds_api_daily_limit: int | None = None
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

    @field_validator("live_poll_seconds", "prematch_refresh_minutes", "odds_refresh_seconds", "live_data_stale_seconds", "live_stats_stale_seconds", "live_odds_stale_seconds", "live_refresh_cooldown_seconds", "basketball_period_minutes", "basketball_regulation_periods", "basketball_overtime_minutes", "api_football_daily_limit", "api_basketball_daily_limit", "football_data_daily_limit")
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

    @field_validator("db_pool_size", "db_max_overflow", "db_pool_timeout", "db_pool_recycle", "api_rate_limit_requests", "api_rate_limit_window_seconds", "expensive_rate_limit_requests", "expensive_rate_limit_window_seconds", "max_request_body_bytes", "request_id_max_length", "provider_retry_attempts", "provider_circuit_failure_threshold", "provider_circuit_cooldown_seconds")
    @classmethod
    def positive_operational_limits(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("operational limits must be positive")
        return value

    @field_validator("provider_connect_timeout", "provider_read_timeout", "provider_retry_base_seconds")
    @classmethod
    def positive_provider_limits(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("provider timeout/retry values must be positive")
        return value

    @property
    def provider_daily_limits(self) -> dict[str, int]:
        limits = {"api-football": 100, "api-basketball": 100, "football-data.org": 10} if self.quota_mode == "free" else {}
        for provider, value in (("api-football", self.api_football_daily_limit), ("api-basketball", self.api_basketball_daily_limit), ("football-data.org", self.football_data_daily_limit), ("the-odds-api", self.the_odds_api_daily_limit)):
            if value is not None:
                limits[provider] = value
        return limits

    @property
    def additional_provider_slots(self) -> list[dict[str, Any]]:
        slots: list[dict[str, Any]] = []
        for index in range(1, 7):
            values = {key: getattr(self, f"additional_provider_{index}_{key}") for key in ("name", "sports", "base_url", "api_key", "auth_header", "adapter")}
            if any(values[key] for key in ("name", "base_url", "api_key")):
                values["slot"] = index
                values["configured"] = bool(values["base_url"] and values["api_key"])
                values["enabled"] = bool(values["base_url"])
                values["sports"] = [item.strip() for item in str(values["sports"] or "").split(",") if item.strip()]
                slots.append(values)
        return slots

    @property
    def cors_origins(self) -> list[str]:
        raw = self.allowed_origins if self.allowed_origins is not None else self.api_cors_origins
        return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]

    @property
    def trusted_host_list(self) -> list[str]:
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]

    @property
    def effective_release(self) -> str:
        return self.release or self.app_version


def validate_production_settings(settings: Settings | None = None) -> None:
    """Fail closed for deployment-critical production configuration."""
    current = settings or get_settings()
    if current.app_env != "production":
        return
    database = current.database_url.lower()
    if not (database.startswith("postgresql://") or database.startswith("postgresql+")):
        raise ValueError("production DATABASE_URL must use PostgreSQL")
    if current.redis_required_in_production and not current.redis_url:
        raise ValueError("production REDIS_URL is required")
    if not current.cors_origins or "*" in current.cors_origins:
        raise ValueError("production allowed origins must be explicit")
    if not current.trusted_host_list or "*" in current.trusted_host_list:
        raise ValueError("production TRUSTED_HOSTS must be explicit")
    if current.app_process_role not in {"web", "worker"}:
        raise ValueError("production APP_PROCESS_ROLE must be web or worker")
    if current.enable_admin_endpoints and not current.admin_token:
        raise ValueError("production admin endpoints require ADMIN_TOKEN")


@lru_cache
def get_settings() -> Settings:
    return Settings()
