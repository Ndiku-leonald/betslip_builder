from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProfileConfig:
    minimum_probability: float
    minimum_confidence: float
    minimum_data_quality: float
    minimum_market_reliability: float
    minimum_source_reliability: float
    minimum_calibration: frozenset[str]
    weights: dict[str, float]
    correlation_penalty: float
    uncertainty_penalty: float


# One configuration surface keeps safety gates and optimizer weights auditable.
PROFILE_CONFIG: dict[str, ProfileConfig] = {
    "conservative": ProfileConfig(
        minimum_probability=.60, minimum_confidence=65, minimum_data_quality=70,
        minimum_market_reliability=65, minimum_source_reliability=70,
        minimum_calibration=frozenset({"fitted", "CALIBRATED", "PARTIALLY_CALIBRATED", "family_fitted"}),
        weights={"joint": .34, "target": .18, "confidence": .16, "quality": .12, "reliability": .10, "value": .06, "legs": .04},
        correlation_penalty=.30, uncertainty_penalty=.20,
    ),
    "balanced": ProfileConfig(
        minimum_probability=.53, minimum_confidence=50, minimum_data_quality=50,
        minimum_market_reliability=45, minimum_source_reliability=55,
        minimum_calibration=frozenset({"fitted", "CALIBRATED", "PARTIALLY_CALIBRATED", "family_fitted", "raw_dynamic_line"}),
        weights={"joint": .29, "target": .22, "confidence": .12, "quality": .11, "reliability": .10, "value": .10, "legs": .06},
        correlation_penalty=.22, uncertainty_penalty=.14,
    ),
    "aggressive": ProfileConfig(
        minimum_probability=.45, minimum_confidence=35, minimum_data_quality=35,
        minimum_market_reliability=25, minimum_source_reliability=45,
        minimum_calibration=frozenset({"fitted", "CALIBRATED", "PARTIALLY_CALIBRATED", "family_fitted", "raw_dynamic_line"}),
        weights={"joint": .22, "target": .28, "confidence": .09, "quality": .09, "reliability": .09, "value": .17, "legs": .06},
        correlation_penalty=.16, uncertainty_penalty=.10,
    ),
}

MAX_TARGET_ODDS = 1000.0
MAX_DATE_WINDOW_DAYS = 31
MAX_BEAM_WIDTH = 160
MAX_CANDIDATES_PER_GROUP = 120
MAX_CANDIDATES_PER_FIXTURE = 8
