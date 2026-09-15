from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class FixtureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    sport: str
    competition: str | None
    home: str
    away: str
    kickoff_at: datetime | None
    status: str
    status_detail: str | None
    home_score: int | None
    away_score: int | None
    period: str | None
    clock: str | None
    provider: str
    observed_at: datetime | None
    provider_updated_at: datetime | None
    ingested_at: datetime
    freshness: str
    data_age_seconds: int | None


class ProviderStatus(BaseModel):
    provider: str
    configured: bool
    healthy: bool
    last_success_at: datetime | None
    last_error: str | None
    latency_ms: float | None
    calls_today: int
    capabilities: dict[str, bool]


class ProviderUsageOut(BaseModel):
    provider: str
    calls_today: int
    mode: str


class ErrorOut(BaseModel):
    code: str
    message: str
    provider: str | None = None
    stale: bool = False


class DetailOut(BaseModel):
    fixture_id: str
    provider: str
    available: bool
    availability: Literal["available", "unsupported", "not_covered", "temporarily_unavailable", "provider_failure"] = "available"
    data: Any = None
    stale: bool = False
    message: str | None = None
