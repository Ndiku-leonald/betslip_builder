import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.models import Fixture, FixtureFeatureSnapshot, ModelVersion, OddsSnapshot, Prediction
from app.schemas import SlipBuildRequest
from app.slips.backtest import evaluate_optimizer_backtest
from app.slips.config import PROFILE_CONFIG
from app.slips.correlation import CorrelationRisk, classify_correlation
from app.slips.optimizer import CandidateGate, PoolResult, SlipOptimizer
from app.slips.synthetic_pipeline import _seed
import app.main as main_module


def _db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


def _leg(fixture: str, *, family="1x2", selection="home", participant="none", line=None, odds=1.8, probability=.65, bookmaker="Book", provider="provider", sport="football", team_ids=None):
    return {"fixture_id": fixture, "market_family": family, "market_type": family, "selection": selection, "participant": participant, "line": line, "bookmaker_odds": odds, "model_probability": probability, "confidence": 80, "data_quality": 85, "market_reliability": 80, "source_reliability": 80, "expected_value": .1, "bookmaker": bookmaker, "provider": provider, "sport": sport, "team_ids": team_ids or [fixture + "-home", fixture + "-away"]}


def test_prematch_prediction_selection_ignores_live_and_unavailable_predictions():
    engine = _db(); now = datetime.now(timezone.utc).replace(microsecond=0)
    with Session(engine) as db:
        _seed(db, now)
        fixture = db.scalar(select(__import__("app.models", fromlist=["Fixture"]).Fixture).order_by(__import__("app.models", fromlist=["Fixture"]).Fixture.kickoff_at))
        prematch = db.scalar(select(Prediction).where(Prediction.fixture_id == fixture.id, Prediction.prediction_type == "pre_match"))
        db.add(Prediction(fixture_id=fixture.id, sport="football", prediction_type="live", generated_at=now + timedelta(minutes=5), payload={"available": True}))
        db.add(Prediction(fixture_id=fixture.id, sport="football", prediction_type="evaluation", generated_at=now + timedelta(minutes=6), payload={"available": True}))
        db.add(Prediction(fixture_id=fixture.id, sport="football", prediction_type="pre_match", generated_at=now + timedelta(minutes=7), payload={"available": False}))
        db.commit()
        selected = SlipOptimizer._latest_valid_prematch_prediction(db, fixture.id)
        assert selected.id == prematch.id and selected.prediction_type == "pre_match"


@pytest.mark.parametrize("left,right,expected", [
    (_leg("f", selection="home"), _leg("f", selection="away"), "CONFLICTING"),
    (_leg("f", selection="home"), _leg("f", family="draw_no_bet", selection="home"), "HIGH"),
    (_leg("f", selection="home"), _leg("f", family="handicap", selection="win", participant="home", line=-0.5), "HIGH"),
    (_leg("f", family="totals", selection="over", line=2.5), _leg("f", family="totals", selection="under", line=2.5), "CONFLICTING"),
    (_leg("f", family="totals", selection="over", line=2.5), _leg("f", family="btts", selection="yes"), "HIGH"),
    (_leg("f", family="totals", selection="under", line=2.5), _leg("f", family="btts", selection="no"), "HIGH"),
    (_leg("f", family="team_total", selection="over", participant="home", line=1.5), _leg("f", family="totals", selection="over", line=2.5), "HIGH"),
    (_leg("f", family="handicap", selection="win", participant="home", line=-3.5), _leg("f", family="handicap", selection="win", participant="away", line=-3.5), "CONFLICTING"),
    (_leg("b", family="moneyline", selection="home", sport="basketball"), _leg("b", family="moneyline", selection="away", sport="basketball"), "CONFLICTING"),
    (_leg("b", family="moneyline", selection="home", sport="basketball"), _leg("b", family="spread", selection="win", participant="home", line=-4.5, sport="basketball"), "HIGH"),
    (_leg("b", family="spread", selection="win", participant="home", line=-4.5, sport="basketball"), _leg("b", family="spread", selection="win", participant="away", line=-4.5, sport="basketball"), "CONFLICTING"),
])
def test_explicit_same_fixture_correlation_semantics(left, right, expected):
    assert classify_correlation(left, right)["risk"] == expected


def test_backtest_rejects_future_odds_prediction_and_post_kickoff_selection():
    now = datetime.now(timezone.utc)
    safe = {"selection_at": now, "odds_observed_at": now - timedelta(minutes=2), "prediction_generated_at": now - timedelta(minutes=3), "fixture_start_at": now + timedelta(hours=1), "actual_all_legs_hit": True}
    leaked = {**safe, "odds_observed_at": now + timedelta(minutes=1)}
    late = {**safe, "selection_at": now + timedelta(hours=2)}
    result = evaluate_optimizer_backtest([safe, leaked, late])
    assert result["evaluated_rows"] == 1
    assert result["rejected_leakage_rows"] == 2
    assert result["rejection_reasons"]["odds_observed_after_selection"] == 1
    assert result["rejection_reasons"]["selection_not_before_fixture_start"] == 1


def test_backtest_counts_missing_timestamps_separately():
    result = evaluate_optimizer_backtest([{"selection_at": datetime.now(timezone.utc), "actual_all_legs_hit": True}])
    assert result["missing_timestamp_rows"] == 1 and result["evaluated_rows"] == 0


def test_push_metrics_retain_win_push_loss_and_never_overstate_joint_probability():
    optimizer = SlipOptimizer()
    legs = [_leg("a", odds=1.9, probability=.55), _leg("b", odds=2.0, probability=.60)]
    legs[0]["push_probability"] = .10; legs[1]["push_probability"] = 0
    metrics = optimizer.recalculate_option(legs, 3.8, .1, PROFILE_CONFIG["balanced"])
    assert legs[0]["model_probability"] + legs[0]["push_probability"] + .35 == pytest.approx(1)
    assert metrics["all_legs_win_probability"] == pytest.approx(.33)
    assert metrics["no_loss_probability_with_push"] == pytest.approx(.39)
    assert metrics["push_affected_probability"] == pytest.approx(.06)
    assert metrics["no_loss_probability_with_push"] >= metrics["all_legs_win_probability"]
    assert any("push" in warning.lower() for warning in metrics["warnings"])


def test_half_point_line_has_zero_push_probability():
    optimizer = SlipOptimizer()
    leg = _leg("a", family="totals", selection="over", line=2.5, probability=.55)
    leg["push_probability"] = 0
    assert optimizer.recalculate_option([leg], 1.9, .1, PROFILE_CONFIG["balanced"])["push_affected_probability"] == 0


def test_target_tolerance_boundaries_and_exact_target():
    optimizer = SlipOptimizer(); base = [_leg("a", odds=1.0 + 0.01, probability=.9)]
    for odds in (4.95, 5.0, 5.05):
        legs = [_leg("a", odds=odds, probability=.7)]
        assert optimizer.recalculate_option(legs, 5, .01, PROFILE_CONFIG["balanced"])["target_reached"] is True
    assert optimizer.recalculate_option([_leg("a", odds=6.8)], 5, .1, PROFILE_CONFIG["balanced"])["target_reached"] is False
    assert optimizer.recalculate_option([_leg("a", odds=10)], 5, .1, PROFILE_CONFIG["balanced"])["target_reached"] is False
    assert base[0]["bookmaker_odds"] > 1


def test_profile_thresholds_are_central_and_aggressive_does_not_bypass_hard_gates():
    assert PROFILE_CONFIG["conservative"].minimum_probability > PROFILE_CONFIG["balanced"].minimum_probability > PROFILE_CONFIG["aggressive"].minimum_probability
    fixture = SimpleNamespace(status="scheduled")
    for profile in ("conservative", "balanced", "aggressive"):
        gate = CandidateGate({"min_confidence": 0, "min_data_quality": 0, "min_probability": 0, "max_individual_odds": 100, "require_positive_value": False}, PROFILE_CONFIG[profile])
        accepted, reasons = gate.check({"market_status": "suspended", "status": "CURRENT", "freshness": {"status": "STALE"}, "bookmaker_odds": 2, "model_probability": .9, "confidence": 90, "data_quality": 90, "market_reliability": 90, "source_reliability": 90, "calibration_status": "fitted", "compatibility": "SUPPORTED", "bookmaker": "Book"}, fixture=fixture, live=False)
        assert not accepted and "stale_or_aging_odds" in reasons and "market_status:suspended" in reasons


def test_snapshot_dedup_prefers_current_valid_duplicate_over_stale_duplicate():
    engine = _db(); now = datetime.now(timezone.utc).replace(microsecond=0)
    with Session(engine) as db:
        _seed(db, now)
        fixture = db.scalar(select(__import__("app.models", fromlist=["Fixture"]).Fixture).order_by(__import__("app.models", fromlist=["Fixture"]).Fixture.kickoff_at))
        current = db.scalar(select(OddsSnapshot).where(OddsSnapshot.fixture_id == fixture.id, OddsSnapshot.selection == "home"))
        stale = OddsSnapshot(fixture_id=fixture.id, provider=current.provider, bookmaker=current.bookmaker, market_family=current.market_family, market_type=current.market_type, period=current.period, participant=current.participant, selection=current.selection, line=current.line, decimal_odds=9, market_status="open", is_live=False, settlement_semantics=current.settlement_semantics, observed_at=now - timedelta(hours=3), provider_updated_at=now - timedelta(hours=3), payload={})
        db.add(stale); db.commit()
        selected = SlipOptimizer._prematch_snapshots(db, fixture.id)
        match = [row for row in selected if row.selection == "home" and row.bookmaker == current.bookmaker]
        assert len(match) == 1 and match[0].id == current.id


def test_date_status_and_mode_filters_exclude_live_completed_and_out_of_range_fixtures():
    engine = _db(); now = datetime.now(timezone.utc).replace(microsecond=0)
    with Session(engine) as db:
        _seed(db, now)
        fixtures = list(db.scalars(select(Fixture).order_by(Fixture.kickoff_at)))
        fixtures[0].status = "live"
        fixtures[1].status = "finished"
        db.commit()
        day = (now + timedelta(hours=3)).date()
        request = {"sports": ["football", "basketball"], "start_date": day, "end_date": day + timedelta(days=1), "profile": "balanced", "mode": "prematch", "include_live": False, "min_confidence": 0, "min_data_quality": 0, "min_probability": 0, "max_individual_odds": 3, "target_odds": 3, "target_tolerance": .1, "min_legs": 1, "max_legs": 6}
        pool = SlipOptimizer().candidate_pool(db, request)
        assert pool.candidates and all(item["status"] == "PRE_MATCH" for item in pool.candidates)
        assert fixtures[0].id not in {item["fixture_id"] for item in pool.candidates}
        assert fixtures[1].id not in {item["fixture_id"] for item in pool.candidates}
        live_request = {**request, "mode": "live", "include_live": True}
        assert SlipOptimizer().candidate_pool(db, live_request).candidates == []


def test_real_only_recommendations_require_complete_real_lineage():
    engine = _db(); now = datetime.now(timezone.utc).replace(microsecond=0)
    with Session(engine) as db:
        _seed(db, now)
        fixture = db.scalar(select(Fixture).where(Fixture.provider == "api-football", Fixture.status == "scheduled").order_by(Fixture.kickoff_at))
        prediction = db.scalar(select(Prediction).where(Prediction.fixture_id == fixture.id, Prediction.prediction_type == "pre_match"))
        request = {"sports": ["football"], "start_date": now.date(), "end_date": now.date() + timedelta(days=1), "profile": "balanced", "mode": "prematch", "include_live": False, "real_only": True, "min_confidence": 0, "min_data_quality": 0, "min_probability": 0, "max_individual_odds": 3, "target_odds": 3, "target_tolerance": .1, "min_legs": 1, "max_legs": 2}
        optimizer = SlipOptimizer()

        missing = optimizer.candidate_pool(db, request)
        assert not missing.candidates
        assert missing.diagnostics["rejection_reasons"]["missing_feature_snapshot"] >= 1
        assert missing.diagnostics["rejection_reasons"]["missing_real_odds_snapshot"] >= 1

        feature = FixtureFeatureSnapshot(fixture_id=fixture.id, sport="football", feature_version="lineage-test-v1", data_cutoff_at=now - timedelta(minutes=5), values={"home_elo": 1500}, data_quality={"overall": 90, "history_count": 5})
        db.add(feature)
        db.flush()
        real_odds = OddsSnapshot(fixture_id=fixture.id, provider="the-odds-api", source_event_id="event-lineage", bookmaker="Real Book", market_family="1x2", market_type="1x2", period="full_game", participant="none", selection="home", decimal_odds=1.8, market_status="open", is_live=False, settlement_semantics="full_game", observed_at=now, provider_updated_at=now, payload={})
        db.add(real_odds)
        db.commit()

        incomplete = optimizer.candidate_pool(db, request)
        assert not incomplete.candidates
        assert incomplete.diagnostics["rejection_reasons"]["feature_version_not_linked"] >= 1

        prediction.features_version = feature.feature_version
        db.commit()
        linked = optimizer.candidate_pool(db, request)
        assert linked.candidates

        model = db.get(ModelVersion, prediction.model_version_id)
        model.status = "candidate"
        db.commit()
        unapproved = optimizer.candidate_pool(db, request)
        assert not unapproved.candidates
        assert unapproved.diagnostics["rejection_reasons"]["model_not_approved"] >= 1


def test_buildable_search_never_mixes_bookmakers_when_cross_book_prices_are_better():
    optimizer = SlipOptimizer()
    items = [_leg("a", odds=2.2, bookmaker="Book A"), _leg("b", odds=2.2, bookmaker="Book B"), _leg("a2", odds=1.5, bookmaker="Book A"), _leg("b2", odds=1.5, bookmaker="Book B")]
    optimizer.candidate_pool = lambda db, request: PoolResult(items, {"candidates_discovered": 4, "candidates_rejected": 0, "candidates_entering_optimizer": 4}, [])
    result = optimizer.optimize(None, {"target_odds": 4.84, "target_tolerance": .1, "profile": "balanced", "min_legs": 2, "max_legs": 2, "alternatives": 3})
    assert result["slips"]
    assert all({(leg["provider"], leg["bookmaker"]) for leg in slip["legs"]} == {(slip["provider"], slip["bookmaker"])} for slip in result["slips"])


def test_same_fixture_is_one_leg_by_default_and_alternatives_have_fixture_diversity():
    result = __import__("app.slips.synthetic_pipeline", fromlist=["run_stage_five_synthetic_pipeline"]).run_stage_five_synthetic_pipeline()
    slips = result["scenario_b"]["slips"]
    assert all(len({leg["fixture_id"] for leg in slip["legs"]}) == len(slip["legs"]) for slip in slips)
    for index, left in enumerate(slips):
        for right in slips[index + 1:]:
            assert len({leg["fixture_id"] for leg in left["legs"]}.symmetric_difference({leg["fixture_id"] for leg in right["legs"]})) >= 2


def test_optimizer_search_diagnostics_expose_bounds_and_pruning():
    result = __import__("app.slips.synthetic_pipeline", fromlist=["run_stage_five_synthetic_pipeline"]).run_stage_five_synthetic_pipeline()
    # Scenario D exposes the diagnostic contract on the safe-failure path.
    diagnostics = result["scenario_d"]["diagnostics"]
    assert diagnostics["pruning_count"] >= 0 and diagnostics["combinations_explored"] >= 0
    assert diagnostics["search_limit"]["beam_width"] > 0 and diagnostics["search_limit"]["max_legs"] == 3


def test_api_build_retrieval_explain_history_and_leg_removal_use_persisted_snapshots():
    engine = _db(); now = datetime.now(timezone.utc).replace(microsecond=0)
    with Session(engine) as db: _seed(db, now)
    def override_db():
        with Session(engine) as db: yield db
    main_module.app.dependency_overrides[get_db] = override_db
    try:
        # Seeded fixtures begin ten minutes after now; use their local
        # calendar day so the test remains stable near midnight in Africa/Kampala.
        day = (now + timedelta(hours=2)).astimezone(ZoneInfo("Africa/Kampala")).date().isoformat()
        client = TestClient(main_module.app)
        response = client.post("/api/slips/build", json={"sports": ["football"], "start_date": day, "end_date": day, "target_odds": 3, "profile": "balanced", "max_legs": 3, "min_legs": 2})
        assert response.status_code == 200 and response.json()["slips"]
        slip = response.json()["slips"][0]; slip_id = slip["id"]; leg_id = slip["legs"][0]["id"]
        assert client.get(f"/api/slips/{slip_id}").status_code == 200
        assert "explanation" in client.get(f"/api/slips/{slip_id}/explain").json()
        assert client.get("/api/slips/history").status_code == 200
        removed = client.delete(f"/api/slips/{slip_id}/legs/{leg_id}")
        assert removed.status_code == 200 and len(removed.json()["legs"]) == len(slip["legs"]) - 1
        assert removed.json()["combined_odds"] == pytest.approx(math.prod(leg["bookmaker_odds"] for leg in removed.json()["legs"]))
        for remaining_leg in list(removed.json()["legs"]):
            final = client.delete(f"/api/slips/{slip_id}/legs/{remaining_leg['id']}")
        assert final.status_code == 200 and final.json()["legs"] == [] and final.json()["combined_odds"] == 1.0
        assert client.get("/api/slips/not-found").status_code == 404
        assert client.get("/api/slips/not-found/explain").status_code == 404
        assert client.delete(f"/api/slips/{slip_id}/legs/not-found").status_code == 404
        impossible = client.post("/api/slips/build", json={"sports": ["football"], "start_date": day, "end_date": day, "target_odds": 999, "profile": "balanced", "max_legs": 2, "min_legs": 2, "bookmaker": "Missing Book"})
        assert impossible.status_code == 200 and impossible.json()["status"] == "NO_SAFE_TARGET"
        assert client.post("/api/slips/build", json={"target_odds": 1}).status_code == 422
    finally:
        main_module.app.dependency_overrides.clear()
