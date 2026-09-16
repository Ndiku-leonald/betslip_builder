from __future__ import annotations


SOURCE_ROLES = {
    "api-football": {"tier": "primary", "configured_priority": 100},
    "api-basketball": {"tier": "primary", "configured_priority": 100},
    "livescore-football": {"tier": "secondary", "configured_priority": 60},
    "easy-soccer-data": {"tier": "experimental_secondary", "configured_priority": 20},
    "the-odds-api": {"tier": "odds_context", "configured_priority": 50},
    "betpawa-import": {"tier": "target_import", "configured_priority": 40},
}


def source_reliability(provider: str, *, observed_agreement_rate: float | None = None, freshness_score: float = 50, coverage_score: float = 50) -> dict:
    role = SOURCE_ROLES.get(provider, {"tier": "unknown", "configured_priority": 0})
    evidence = 50 if observed_agreement_rate is None else max(0, min(100, observed_agreement_rate * 100))
    return {"provider": provider, **role, "observed_agreement_rate": observed_agreement_rate, "freshness_score": freshness_score, "coverage_score": coverage_score, "reliability_score": round(.4 * evidence + .3 * freshness_score + .3 * coverage_score, 2)}
