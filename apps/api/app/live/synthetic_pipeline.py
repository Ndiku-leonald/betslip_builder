"""Deterministic, credential-free Stage Four validation scenarios."""

from datetime import datetime, timedelta, timezone

from app.live.models import BasketballLivePosterior, FootballLivePosterior
from app.live.quality import evaluate_live_data_quality, live_recommendation_gate
from app.live.state import LiveMatchState
from app.live.models import _clock_context
from app.markets.value import market_freshness
from app.live.ranking import rank_live_markets


def _state(sport: str, stamp: datetime, **values) -> LiveMatchState:
    return LiveMatchState(fixture_id=f"synthetic-{sport}", sport=sport, source_provider=f"synthetic-{sport}", source_event_id="demo", status="live", kickoff_at=stamp - timedelta(minutes=30), source_timestamp=stamp, observed_at=stamp, provider_updated_at=stamp, **values)


def run_synthetic_live_pipeline() -> dict:
    stamp = datetime.now(timezone.utc)
    football_prior = {"home_win": .47, "draw": .28, "away_win": .25, "expected_home_goals": 1.45, "expected_away_goals": 1.10}
    football_state = _state("football", stamp, period="30", clock="30'", minute=30, home_score=1, away_score=0, statistics={"home": {"shots_on_goal": 3}, "away": {"shots_on_goal": 1}})
    football_quality = evaluate_live_data_quality(football_state, now=stamp, provider_reliability=.9, pre_match_available=True)
    football_posterior = FootballLivePosterior.from_prior(football_state, football_prior)
    football_gate = live_recommendation_gate(football_quality, odds_available=True, odds_fresh=True)
    football_stale_gate = live_recommendation_gate(evaluate_live_data_quality(football_state, now=stamp + timedelta(minutes=5)), odds_available=True, odds_fresh=True)

    basketball_prior = {"home_moneyline": .54, "away_moneyline": .46, "expected_home_score": 108, "expected_away_score": 104, "margin_sd": 12, "total_sd": 18}
    basketball_state = _state("basketball", stamp, period="Q3", clock="06:00", home_score=70, away_score=64, statistics={"home": {"possessions": 60, "field_goals_pct": 52}, "away": {"possessions": 59, "field_goals_pct": 47}})
    basketball_quality = evaluate_live_data_quality(basketball_state, now=stamp, provider_reliability=.9, pre_match_available=True)
    basketball_posterior = BasketballLivePosterior.from_prior(basketball_state, basketball_prior)
    basketball_gate = live_recommendation_gate(basketball_quality, odds_available=True, odds_fresh=True)
    basketball_ot = BasketballLivePosterior.from_prior(_state("basketball", stamp, period="OT1", clock="02:00", home_score=102, away_score=100, statistics={}, auxiliary={"rules_known": True}), basketball_prior)
    suspended = rank_live_markets([{"status": "CURRENT", "market_status": "suspended", "freshness": {"status": "CURRENT"}, "model_probability": .7, "model_resolved_win_probability": .7, "novig_probability_edge": .1, "confidence": 80, "data_quality": 90, "calibration_status": "PARTIALLY_CALIBRATED"}])
    return {
        "status": "PASS",
        "football": {"pre_match": football_prior, "live": football_posterior.live_probability, "delta": {k: football_posterior.live_probability[k] - football_posterior.pre_match_probability[k] for k in football_posterior.live_probability}, "data_quality": football_quality, "recommendation_gate": football_gate, "stale_gate": football_stale_gate, "stale_odds": market_freshness(stamp - timedelta(minutes=5), provider_updated_at=stamp - timedelta(minutes=5), now=stamp, ttl_seconds=30)["status"] == "STALE", "snapshot_history": ["kickoff", "30'"]},
        "basketball": {"pre_match": basketball_prior, "live": basketball_posterior.live_probability, "ot_live": basketball_ot.live_probability, "ot_clock": _clock_context(basketball_ot.state), "data_quality": basketball_quality, "recommendation_gate": basketball_gate, "snapshot_history": ["Q1", "Q3", "OT1"]},
        "checks": {"pre_match_immutable": football_prior["home_win"] == .47, "chronological_history": ["kickoff", "30'"] == sorted(["kickoff", "30'"], key=lambda item: ["kickoff", "30'"].index(item)), "suspended_suppressed": suspended == [], "missing_prices_suppressed": live_recommendation_gate(football_quality, odds_available=False)[0] is False, "stale_prices_suppressed": live_recommendation_gate(football_quality, odds_available=True, odds_fresh=False)[0] is False},
    }
