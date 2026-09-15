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


class PredictionOut(BaseModel):
    available: bool
    fixture_id: str
    sport: str | None = None
    generated_at: datetime | None = None
    data_cutoff_at: datetime | str | None = None
    model_version: str | None = None
    model: str | None = None
    expected_home_goals: float | None = None
    expected_away_goals: float | None = None
    expected_home_score: float | None = None
    expected_away_score: float | None = None
    expected_margin: float | None = None
    expected_total: float | None = None
    markets: dict = {}
    raw_probability: dict = {}
    calibrated_probability: dict = {}
    calibration_status: str | None = None
    calibration_status_by_market: dict = {}
    data_quality: dict = {}
    confidence_components: dict = {}
    model_confidence_score: float | None = None
    warnings: list[str] = []
    reason: str | None = None


class ModelVersionOut(BaseModel):
    id: str
    name: str
    version: str
    sport: str | None = None
    algorithm: str | None = None
    trained_at: datetime | None = None
    feature_version: str | None = None
    metrics: dict = {}
    sample_count: int | None = None
    status: str
