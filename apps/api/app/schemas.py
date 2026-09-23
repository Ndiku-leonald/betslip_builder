from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator


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


class LivePredictionOut(BaseModel):
    available: bool
    fixture_id: str
    sport: str | None = None
    state: dict = {}
    pre_match_prediction: dict = {}
    live_prediction: dict = {}
    probability_delta: dict = {}
    model_version: str | None = None
    model: str | None = None
    confidence: float | None = None
    data_quality: dict = {}
    calibration_status: str | None = None
    warnings: list[str] = []
    market_intelligence: dict | None = None
    reason: str | None = None


class LiveMarketResultOut(BaseModel):
    fixture_id: str
    values: list[dict] = []
    opportunities: list[dict] = []
    warnings: list[str] = []
    prediction: dict | None = None
    odds_consensus: list[dict] = []
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


class SlipBuildRequest(BaseModel):
    sports: list[Literal["football", "basketball"]] = ["football", "basketball"]
    start_date: date | None = None
    end_date: date | None = None
    mode: Literal["prematch", "live", "both"] = "prematch"
    target_odds: float
    profile: Literal["conservative", "balanced", "aggressive"] = "balanced"
    min_confidence: float = 0
    min_data_quality: float = 0
    max_legs: int = 6
    min_legs: int = 2
    min_probability: float = 0
    max_individual_odds: float = 100
    target_tolerance: float = .10
    include_live: bool = False
    competitions: list[str] = []
    bookmaker: str | None = None
    correlation_policy: Literal["avoid_same_fixture", "allow_with_penalty"] = "avoid_same_fixture"
    require_positive_value: bool = False
    alternatives: int = 3

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.target_odds <= 1 or self.target_odds > 1000: raise ValueError("target_odds must be greater than 1 and at most 1000")
        if self.min_legs < 1 or self.max_legs < self.min_legs or self.max_legs > 12: raise ValueError("leg limits must satisfy 1 <= min_legs <= max_legs <= 12")
        if not 0 <= self.min_confidence <= 100 or not 0 <= self.min_data_quality <= 100: raise ValueError("confidence and data-quality thresholds must be between 0 and 100")
        if not 0 <= self.target_tolerance <= .5: raise ValueError("target_tolerance must be between 0 and 0.5")
        if not 1 < self.max_individual_odds <= 100: raise ValueError("max_individual_odds must be greater than 1 and no more than 100")
        if not 0 <= self.min_probability < 1: raise ValueError("min_probability must be between 0 and 1")
        if self.start_date and self.end_date and self.end_date < self.start_date: raise ValueError("end_date cannot precede start_date")
        if self.start_date and self.end_date and (self.end_date - self.start_date).days > 31: raise ValueError("date window cannot exceed 31 days")
        if self.mode == "live" and not self.include_live: raise ValueError("include_live must be true in live mode")
        if not self.sports: raise ValueError("at least one sport is required")
        return self


class SlipLegOut(BaseModel):
    id: str | None = None
    fixture_id: str
    sport: str
    competition: str | None = None
    home: str
    away: str
    kickoff_at: datetime | None = None
    status: str
    market_family: str
    market_type: str
    participant: str
    selection: str
    line: float | None = None
    bookmaker_odds: float
    model_probability: float
    model_push_probability: float = 0
    fair_odds: float | None = None
    expected_value: float | None = None
    confidence: float = 0
    data_quality: float = 0
    explanation: str
    warnings: list[str] = []


class SlipOut(BaseModel):
    id: str | None = None
    target_odds: float
    combined_odds: float
    target_difference: float
    profile: str
    mode: str
    bookmaker: str | None = None
    provider: str | None = None
    legs: list[dict] = []
    naive_joint_probability: float
    risk_adjusted_probability: float
    correlation_risk: str
    target_reached: bool
    warnings: list[str] = []


class SlipBuildOut(BaseModel):
    status: str
    message: str
    target_odds: float
    profile: str
    mode: str
    target_reached: bool
    slips: list[dict] = []
    diagnostics: dict = {}
    exclusions: list[dict] = []
    warnings: list[str] = []
