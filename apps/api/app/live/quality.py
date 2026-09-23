from __future__ import annotations

from datetime import datetime, timezone

from app.config import get_settings
from app.live.state import LiveMatchState


def _age(value: datetime | None, now: datetime) -> int | None:
    if value is None:
        return None
    stamp = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return max(0, int((now - stamp).total_seconds()))


def evaluate_live_data_quality(state: LiveMatchState, *, now: datetime | None = None, provider_reliability: float = 0.75, source_agreement: float | None = None, pre_match_available: bool = True) -> dict:
    settings = get_settings()
    current = now or datetime.now(timezone.utc)
    state_age = _age(state.source_timestamp or state.observed_at, current)
    stats_age = _age(state.stats_observed_at, current) if state.statistics else None
    missing_core = state.home_score is None or state.away_score is None or not state.status
    clock_valid = state.sport == "football" and state.status in {"live", "halftime"} and state.minute is not None or state.sport == "basketball" and state.status in {"live", "halftime"} and state.period is not None or state.status not in {"live", "halftime"}
    state_fresh = state_age is not None and state_age <= settings.live_data_stale_seconds
    stats_fresh = not state.statistics or (stats_age is not None and stats_age <= settings.live_stats_stale_seconds)
    if missing_core or not clock_valid or not state_fresh:
        quality_status = "UNUSABLE"
    else:
        components = [0.35, 0.2 if stats_fresh else 0.0, 0.2 * max(0.0, min(1.0, provider_reliability)), 0.15 if pre_match_available else 0.05, 0.1 if source_agreement is not None and source_agreement >= 0.8 else 0.05 if source_agreement is None else 0.0]
        score = max(0.0, min(1.0, sum(components)))
        quality_status = "HIGH" if score >= 0.8 else "MEDIUM" if score >= 0.6 else "LOW"
    score = 0.0 if quality_status == "UNUSABLE" else max(0.0, min(1.0, sum([0.35, 0.2 if stats_fresh else 0.0, 0.2 * max(0.0, min(1.0, provider_reliability)), 0.15 if pre_match_available else 0.05, 0.1 if source_agreement is None or source_agreement >= 0.8 else 0.0])))
    warnings = []
    if state_age is None: warnings.append("Match-state timestamp unavailable.")
    elif not state_fresh: warnings.append("Live data too stale for a reliable market evaluation.")
    if state.statistics and not stats_fresh: warnings.append("Live statistics are stale and will be ignored by the live model.")
    if not pre_match_available: warnings.append("No valid pre-match prediction; live model uses a lower-confidence baseline.")
    return {"overall": round(score, 4), "status": quality_status, "state_age_seconds": state_age, "statistics_age_seconds": stats_age, "state_fresh": state_fresh, "statistics_fresh": stats_fresh, "statistics_used": bool(state.statistics) and stats_fresh, "provider_reliability": provider_reliability, "source_agreement": source_agreement, "missing_core_fields": missing_core, "clock_valid": clock_valid, "warnings": warnings}


def live_recommendation_gate(quality: dict, *, odds_available: bool = True, odds_fresh: bool = True) -> tuple[bool, str | None]:
    settings = get_settings()
    if not quality.get("state_fresh") or quality.get("status") == "UNUSABLE" or quality.get("overall", 0) < settings.live_min_quality:
        return False, "Live data too stale for a reliable market evaluation."
    if not odds_available:
        return False, "Live market prices unavailable — no betting-market recommendation generated."
    if not odds_fresh:
        return False, "Live market prices unavailable — no betting-market recommendation generated."
    return True, None
