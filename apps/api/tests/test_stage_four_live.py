from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.live.models import BasketballLivePosterior, FootballLivePosterior
from app.live.persistence import live_prediction_history, persist_live_match_snapshot
from app.live.quality import evaluate_live_data_quality, live_recommendation_gate
from app.live.state import LiveMatchState, normalize_basketball_live_state, normalize_football_live_state
from app.live.synthetic_pipeline import run_synthetic_live_pipeline
from app.live.service import LiveIntelligenceService
from app.models import Fixture, LiveMatchSnapshot, OddsSnapshot, Prediction, Sport, Team


def state(sport="football", **overrides):
    now = datetime.now(timezone.utc)
    values = {"fixture_id": "fixture-1", "sport": sport, "source_provider": "api-football" if sport == "football" else "api-basketball", "source_event_id": "1", "status": "live", "kickoff_at": now - timedelta(minutes=30), "source_timestamp": now, "observed_at": now, "provider_updated_at": now, "period": "30" if sport == "football" else "Q2", "clock": "30'" if sport == "football" else "04:00", "minute": 30 if sport == "football" else None, "home_score": 1 if sport == "football" else 44, "away_score": 0 if sport == "football" else 39, "statistics": {"home": {}, "away": {}}}
    values.update(overrides)
    return LiveMatchState(**values)


def test_normalizers_preserve_missing_fields_and_map_clock_and_periods():
    football = normalize_football_live_state({"fixture": {"id": 12, "date": "2026-09-23T16:00:00Z", "update": "2026-09-23T16:30:00Z", "status": {"short": "2H", "long": "Second Half", "elapsed": 67}}, "teams": {"home": {"id": 1, "name": "A"}, "away": {"id": 2, "name": "B"}}, "goals": {"home": 2, "away": 1}, "league": {"name": "Test"}})
    assert football.minute == 67 and football.home_score == 2 and football.statistics["home"] == {}
    basketball = normalize_basketball_live_state({"game": {"id": 13, "date": "2026-09-23T16:00:00Z", "status": {"short": "OT", "period": 5, "clock": "02:00"}, "teams": {"home": {"id": 1, "name": "A"}, "away": {"id": 2, "name": "B"}}, "scores": {"home": {"total": 99}, "away": {"total": 98}}, "league": {"name": "Test"}}})
    assert basketball.period == "5" and basketball.clock == "02:00" and basketball.home_score == 99


def test_quality_and_hard_gates_distinguish_state_and_price_freshness():
    now = datetime.now(timezone.utc)
    fresh = evaluate_live_data_quality(state(), now=now)
    assert fresh["status"] in {"MEDIUM", "HIGH"} and live_recommendation_gate(fresh, odds_available=False)[1].startswith("Live market prices unavailable")
    stale_state = state(source_timestamp=now - timedelta(minutes=10), observed_at=now - timedelta(minutes=10), provider_updated_at=now - timedelta(minutes=10))
    stale = evaluate_live_data_quality(stale_state, now=now)
    assert stale["status"] == "UNUSABLE" and live_recommendation_gate(stale, odds_available=True)[1] == "Live data too stale for a reliable market evaluation."


def test_football_posterior_updates_prior_without_overwriting_it_and_preserves_push():
    posterior = FootballLivePosterior.from_prior(state(home_score=1, away_score=0, minute=65, period="65", statistics={"home": {"expected_goals": 1.4}, "away": {"expected_goals": .3}}), {"home_win": .47, "draw": .28, "away_win": .25, "expected_home_goals": 1.4, "expected_away_goals": 1.0})
    assert posterior.live_probability["home_win"] > posterior.pre_match_probability["home_win"]
    from types import SimpleNamespace
    result = posterior.probabilities_for_market(SimpleNamespace(market_family="handicap", selection="win", line=0.0, participant="home"))
    assert result["push_probability"] > 0 and sum(result[key] for key in ("win_probability", "push_probability", "loss_probability")) == pytest.approx(1)


def test_basketball_posterior_uses_score_period_and_supports_integer_push():
    posterior = BasketballLivePosterior.from_prior(state("basketball", period="Q4", clock="02:00", home_score=101, away_score=94), {"home_moneyline": .54, "away_moneyline": .46, "expected_home_score": 108, "expected_away_score": 104, "margin_sd": 12, "total_sd": 18})
    assert posterior.live_probability["home_moneyline"] > .54
    from types import SimpleNamespace
    result = posterior.probabilities_for_market(SimpleNamespace(market_family="game_total", selection="over", line=200.0, participant="none"))
    assert result["push_probability"] > 0 and sum(result[key] for key in ("win_probability", "push_probability", "loss_probability")) == pytest.approx(1)


def test_immutable_snapshot_history_and_service_price_gate():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        sport = Sport(slug="football", name="Football"); db.add(sport); db.flush(); home = Team(sport_id=sport.id, name="Home"); away = Team(sport_id=sport.id, name="Away")
        db.add_all([home, away]); db.flush()
        fixture = Fixture(sport_id=sport.id, home_team_id=home.id, away_team_id=away.id, provider="synthetic-football", provider_fixture_id="1", status="live", home_score=1, away_score=0, period="30", clock="30'")
        db.add(fixture); db.flush()
        db.add(Prediction(fixture_id=fixture.id, sport="football", prediction_type="pre_match", generated_at=datetime.now(timezone.utc), payload={"available": True, "model_version": "synthetic-v1", "calibrated_probability": {"home_win": .47, "draw": .28, "away_win": .25}, "expected_home_goals": 1.4, "expected_away_goals": 1.0, "model_confidence_score": 65, "calibration_status": "fitted"}))
        db.flush()
        first = state(fixture_id=fixture.id, source_provider="synthetic-football")
        persist_live_match_snapshot(db, first); db.commit()
        prediction = LiveIntelligenceService().prediction(db, fixture.id)
        assert prediction["pre_match_prediction"]["home_win"] == pytest.approx(.47)
        assert prediction["probability_delta"]["home_win"] != 0
        market_result = LiveIntelligenceService().markets(db, fixture.id)
        assert market_result["opportunities"] == [] and any("Live market prices unavailable" in warning for warning in market_result["warnings"])
        assert len(live_prediction_history(db, fixture.id)) == 1


def test_synthetic_pipeline_is_deterministic_and_both_sports_pass():
    result = run_synthetic_live_pipeline()
    assert result["status"] == "PASS"
    assert result["football"]["recommendation_gate"][0] and result["basketball"]["recommendation_gate"][0]
    assert result["football"]["live"]["home_win"] != result["football"]["pre_match"]["home_win"]
