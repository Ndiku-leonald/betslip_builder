from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.cache import MemoryCache
from app.db import Base
from app.live.backtest import evaluate_live_backtest
from app.live.models import BasketballLivePosterior, FootballLivePosterior, _clock_context
from app.live.persistence import persist_live_match_snapshot
from app.live.quality import evaluate_live_data_quality
from app.live.ranking import rank_live_markets
from app.live.service import LiveIntelligenceService
from app.live.state import LiveMatchState, normalize_football_live_state
from app.live.throttle import claim_refresh
from app.markets.value import market_freshness
from app.models import Fixture, LiveMatchSnapshot, LivePredictionSnapshot, Prediction, Sport, Team
from app.odds.ontology import NormalizedMarket, normalize_external_market


def _state(**overrides):
    now = datetime.now(timezone.utc)
    values = dict(fixture_id="f", sport="football", source_provider="synthetic", source_event_id="1", status="live", kickoff_at=now - timedelta(minutes=30), source_timestamp=now, observed_at=now, provider_updated_at=now, period="0", clock="0'", minute=0, home_score=0, away_score=0, statistics={}, auxiliary={})
    values.update(overrides)
    return LiveMatchState(**values)


def _market(family="game_total", selection="over", line=200.0, status="open", provider_updated_at=None, participant="none"):
    now = datetime.now(timezone.utc)
    return NormalizedMarket(fixture_id="f", sport="basketball", bookmaker="Book", provider="feed", market_family=family, market_type=family, period="full_game", participant=participant, selection=selection, line=line, decimal_odds=2.0, status=status, observed_at=now, provider_updated_at=provider_updated_at or now, is_live=True)


def test_football_remaining_goals_scale_only_once_without_evidence():
    prior = {"expected_home_goals": 1.8, "expected_away_goals": 1.2}
    for minute, fraction in ((0, 1), (15, 5 / 6), (45, .5), (75, 1 / 6), (89, 1 / 90)):
        posterior = FootballLivePosterior.from_prior(_state(minute=minute, period=str(minute)), prior)
        assert posterior.home_remaining_mean == pytest.approx(1.8 * fraction, rel=.04)
        assert posterior.away_remaining_mean == pytest.approx(1.2 * fraction, rel=.04)
    kickoff = FootballLivePosterior.from_prior(_state(minute=0), prior)
    with_evidence = FootballLivePosterior.from_prior(_state(minute=45, statistics={"home": {"expected_goals": 2.0}, "away": {"expected_goals": .2}}), prior)
    assert kickoff.home_remaining_mean == pytest.approx(1.8)
    assert with_evidence.home_remaining_mean != pytest.approx(.9)


def test_football_current_score_is_translated_from_remaining_goal_matrix():
    prior = {"expected_home_goals": 1.4, "expected_away_goals": 1.1}
    leading = FootballLivePosterior.from_prior(_state(minute=70, period="70", home_score=1, away_score=0), prior)
    trailing = FootballLivePosterior.from_prior(_state(minute=70, period="70", home_score=0, away_score=2), prior)
    late_draw = FootballLivePosterior.from_prior(_state(minute=85, period="85", home_score=2, away_score=2), prior)
    early_nil = FootballLivePosterior.from_prior(_state(minute=5, period="5"), prior)
    assert leading.live_probability["home_win"] > leading.live_probability["away_win"]
    assert trailing.live_probability["away_win"] > trailing.live_probability["home_win"]
    assert late_draw.live_probability["draw"] > .5
    assert early_nil.live_probability["draw"] < .5


@pytest.mark.parametrize(("team_id", "expected"), [("h", "home"), ("a", "away")])
def test_red_cards_use_canonical_team_ids(team_id, expected):
    common = dict(home_provider_id="h", away_provider_id="a")
    state = _state(auxiliary=common, events=({"type": "Card", "detail": "Red Card", "team": {"id": team_id}},))
    result = FootballLivePosterior.from_prior(state, {"expected_home_goals": 1.5, "expected_away_goals": 1.0})
    no_card = FootballLivePosterior.from_prior(_state(auxiliary=common), {"expected_home_goals": 1.5, "expected_away_goals": 1.0})
    assert result.home_remaining_mean < no_card.home_remaining_mean if expected == "home" else result.away_remaining_mean < no_card.away_remaining_mean


def test_multiple_and_missing_red_cards_are_safe():
    prior = {"expected_home_goals": 1.5, "expected_away_goals": 1.0}
    state = _state(auxiliary={"home_provider_id": "h", "away_provider_id": "a"}, events=({"type": "red card", "team": {"id": "h"}}, {"type": "red card", "team": {"id": "h"}}, {"type": "red card", "team": {"id": "a"}}))
    result = FootballLivePosterior.from_prior(state, prior)
    away_only = FootballLivePosterior.from_prior(_state(auxiliary={"home_provider_id": "h", "away_provider_id": "a"}, events=({"type": "red card", "team": {"id": "a"}}, {"type": "red card", "team": {"id": "a"}})), prior)
    assert result.home_remaining_mean < 1.5 and away_only.away_remaining_mean < 1.0
    assert FootballLivePosterior.from_prior(_state(), prior).home_remaining_mean == pytest.approx(1.5)


def test_basketball_regulation_and_overtime_clock_semantics():
    base = dict(sport="basketball", period="Q1", clock="10:00", minute=None, home_score=10, away_score=8, auxiliary={"rules_known": True})
    assert _clock_context(_state(**base))[0] == 120
    assert _clock_context(_state(**{**base, "period": "HT", "clock": None}))[0] == 1440
    assert _clock_context(_state(**{**base, "period": "Q4", "clock": "02:00"}))[0] == 2760
    assert _clock_context(_state(**{**base, "period": "OT1", "clock": "02:00"}))[0] == 3060
    elapsed, total, remaining, known = _clock_context(_state(**{**base, "period": "OT2", "clock": "02:00"}))
    assert elapsed == 3360 and total == 3480 and remaining == 120 and known


def test_basketball_discrete_pushes_are_exact_integer_events():
    posterior = BasketballLivePosterior.from_prior(_state(sport="basketball", period="Q4", clock="02:00", minute=None, home_score=101, away_score=94, auxiliary={"rules_known": True}), {"home_moneyline": .54, "away_moneyline": .46, "expected_home_score": 108, "expected_away_score": 104, "margin_sd": 12, "total_sd": 18})
    integer = posterior.probabilities_for_market(_market("game_total", "over", 200.0))
    half = posterior.probabilities_for_market(_market("game_total", "over", 200.5))
    spread = posterior.probabilities_for_market(_market("spread", "win", 0.0, participant="home"))
    half_spread = posterior.probabilities_for_market(_market("spread", "win", 0.5, participant="home"))
    assert integer["push_probability"] > 0 and half["push_probability"] == 0
    assert spread["push_probability"] > 0 and half_spread["push_probability"] == 0
    assert sum(integer[key] for key in ("win_probability", "push_probability", "loss_probability")) == pytest.approx(1)


def test_market_status_is_not_inferred_from_current_freshness():
    value = {"status": "CURRENT", "market_status": "suspended", "freshness": {"status": "CURRENT"}, "model_probability": .7, "model_resolved_win_probability": .7, "novig_probability_edge": .1, "confidence": 80, "data_quality": 90, "calibration_status": "PARTIALLY_CALIBRATED", "expected_value": .1, "source_reliability": 90, "market_reliability": 90, "provider_agreement": 1}
    ranked = rank_live_markets([value])
    assert ranked == [] and value["market_status"] == "suspended"


def test_stale_statistics_are_reported_and_not_used_as_current_evidence():
    old = datetime.now(timezone.utc) - timedelta(minutes=20)
    result = evaluate_live_data_quality(_state(statistics={"home": {"expected_goals": 2}}, auxiliary={"stats_observed_at": old}), now=datetime.now(timezone.utc), pre_match_available=True)
    assert result["statistics_fresh"] is False and result["statistics_used"] is False
    assert any("ignored" in warning for warning in result["warnings"])


def test_upstream_timestamps_control_freshness_not_ingestion_time():
    now = datetime.now(timezone.utc)
    quality = evaluate_live_data_quality(_state(source_timestamp=now - timedelta(minutes=10), provider_updated_at=now - timedelta(minutes=10), observed_at=now), now=now)
    odds = market_freshness(now, provider_updated_at=now - timedelta(minutes=5), now=now, ttl_seconds=30)
    assert quality["state_fresh"] is False and odds["status"] == "STALE"


def test_pre_match_fallback_is_explicit_and_deltas_are_not_fabricated():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        sport = Sport(slug="football", name="Football"); db.add(sport); db.flush()
        home, away = Team(sport_id=sport.id, name="H"), Team(sport_id=sport.id, name="A"); db.add_all([home, away]); db.flush()
        fixture = Fixture(sport_id=sport.id, home_team_id=home.id, away_team_id=away.id, provider="synthetic", provider_fixture_id="fallback", status="live", home_score=0, away_score=0, period="10", clock="10'"); db.add(fixture); db.flush()
        output = LiveIntelligenceService().prediction(db, fixture.id)
        assert output["pre_match_prediction"] == {} and output["probability_delta"] == {}
        assert output["calibration_status"] == "INSUFFICIENT_EVIDENCE" and any("fallback baseline" in warning for warning in output["warnings"])


def test_prediction_references_the_exact_snapshot_used():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool); Base.metadata.create_all(engine)
    with Session(engine) as db:
        sport = Sport(slug="football", name="Football"); db.add(sport); db.flush(); home, away = Team(sport_id=sport.id, name="H"), Team(sport_id=sport.id, name="A"); db.add_all([home, away]); db.flush()
        fixture = Fixture(sport_id=sport.id, home_team_id=home.id, away_team_id=away.id, provider="synthetic", provider_fixture_id="exact", status="live", home_score=0, away_score=0, period="10", clock="10'"); db.add(fixture); db.flush()
        db.add(Prediction(fixture_id=fixture.id, sport="football", prediction_type="pre_match", generated_at=datetime.now(timezone.utc), payload={"available": True, "expected_home_goals": 1.4, "expected_away_goals": 1.0, "calibrated_probability": {"home_win": .45, "draw": .3, "away_win": .25}})); db.flush()
        output = LiveIntelligenceService().prediction(db, fixture.id); row = db.scalar(select(LiveMatchSnapshot).where(LiveMatchSnapshot.fixture_id == fixture.id)); prediction = db.scalar(select(LivePredictionSnapshot).where(LivePredictionSnapshot.fixture_id == fixture.id))
        assert output["available"] and prediction.live_match_snapshot_id == row.id


def test_refresh_cooldown_blocks_repeated_fixture_claims():
    cache = MemoryCache()
    assert claim_refresh(cache, "api-football", "f", 30)[0]
    assert claim_refresh(cache, "api-football", "f", 30)[0] is False
    assert claim_refresh(cache, "api-football", "other", 30)[0]


def test_backtest_is_snapshot_time_safe_and_reports_insufficient_calibration():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool); Base.metadata.create_all(engine)
    with Session(engine) as db:
        sport = Sport(slug="football", name="Football"); db.add(sport); db.flush(); home, away = Team(sport_id=sport.id, name="H"), Team(sport_id=sport.id, name="A"); db.add_all([home, away]); db.flush()
        fixture = Fixture(sport_id=sport.id, home_team_id=home.id, away_team_id=away.id, provider="synthetic", provider_fixture_id="bt", status="finished", home_score=2, away_score=0); db.add(fixture); db.flush()
        stamp = datetime.now(timezone.utc) - timedelta(minutes=50); state_row = persist_live_match_snapshot(db, _state(fixture_id=fixture.id, observed_at=stamp, source_timestamp=stamp, minute=15, period="15")); db.add(LivePredictionSnapshot(fixture_id=fixture.id, live_match_snapshot_id=state_row.id, sport="football", observed_at=stamp, pre_match_probability={"home_win": .45, "draw": .3, "away_win": .25}, live_probability={"home_win": .6, "draw": .2, "away_win": .2}, probability_delta={}, markets={}, confidence=50, data_quality={}, warnings=[])); db.commit()
        result = evaluate_live_backtest(db, fixture.id)
        assert result["status"] == "EVALUATED" and result["sample_count"] == 1 and result["calibration"]["status"] == "DESCRIPTIVE_ONLY" and "football:0-15" in result["buckets"]


def test_settlement_families_normalize_and_preserve_semantics():
    dnb = normalize_external_market(fixture_id="f", sport="football", provider="p", bookmaker="b", market_name="Draw No Bet", selection_name="Home", odds=1.8)
    double = normalize_external_market(fixture_id="f", sport="football", provider="p", bookmaker="b", market_name="Double Chance", selection_name="1X", odds=1.4)
    assert dnb.market_family == "draw_no_bet" and double.market_family == "double_chance" and double.selection == "home_draw"
