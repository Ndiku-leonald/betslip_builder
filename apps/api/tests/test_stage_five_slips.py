from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Slip, SlipLeg
from app.schemas import SlipBuildRequest
from app.slips.backtest import evaluate_optimizer_backtest
from app.slips.config import PROFILE_CONFIG
from app.slips.correlation import CorrelationRisk, classify_correlation
from app.slips.optimizer import CandidateGate, SlipOptimizer
from app.slips.synthetic_pipeline import run_stage_five_synthetic_pipeline


def _value(**overrides):
    value = {"market_status": "open", "status": "CURRENT", "freshness": {"status": "CURRENT"}, "bookmaker_odds": 1.8, "model_probability": .65, "model_win_probability": .65, "confidence": 80, "data_quality": 85, "market_reliability": 80, "source_reliability": 80, "provider_agreement": 1.0, "material_provider_conflict": False, "calibration_status": "fitted", "compatibility": "SUPPORTED", "bookmaker": "Book", "expected_value": .1}
    value.update(overrides)
    return value


def test_request_validation_is_bounded_and_supports_profiles():
    request = SlipBuildRequest(target_odds=5, profile="aggressive", max_legs=8, min_legs=2, sports=["football"])
    assert request.profile == "aggressive"
    with pytest.raises(ValueError): SlipBuildRequest(target_odds=1, max_legs=6, min_legs=2)
    with pytest.raises(ValueError): SlipBuildRequest(target_odds=5, max_legs=13, min_legs=2)
    with pytest.raises(ValueError): SlipBuildRequest(target_odds=5, max_legs=6, min_legs=2, end_date="2026-10-20", start_date="2026-09-01")


def test_central_candidate_gate_rejects_stale_status_quality_and_model_failures():
    fixture = SimpleNamespace(status="scheduled")
    gate = CandidateGate({"min_confidence": 0, "min_data_quality": 0, "min_probability": 0, "max_individual_odds": 3, "require_positive_value": False}, PROFILE_CONFIG["balanced"])
    accepted, reasons = gate.check(_value(freshness={"status": "STALE"}, market_status="suspended"), fixture=fixture, live=False)
    assert not accepted and "stale_or_aging_odds" in reasons and "market_status:suspended" in reasons


def test_correlation_classification_rejects_same_fixture_and_flags_shared_team():
    left = {"fixture_id": "one", "team_ids": ["a", "b"], "market_family": "totals", "selection": "over", "sport": "football"}
    right = {"fixture_id": "one", "team_ids": ["a", "b"], "market_family": "btts", "selection": "yes", "sport": "football"}
    assert classify_correlation(left, right)["risk"] == CorrelationRisk.HIGH
    assert classify_correlation({**left, "fixture_id": "two"}, {**right, "fixture_id": "three", "team_ids": ["b", "c"]})["risk"] == CorrelationRisk.HIGH


def test_joint_probability_and_exact_combined_odds_are_deterministic():
    optimizer = SlipOptimizer()
    legs = [{"fixture_id": "a", "bookmaker": "Book", "provider": "p", "bookmaker_odds": 1.5, "model_probability": .8, "confidence": 80, "data_quality": 80, "market_reliability": 80, "source_reliability": 80, "sport": "football", "team_ids": ["a1", "a2"]}, {"fixture_id": "b", "bookmaker": "Book", "provider": "p", "bookmaker_odds": 2.0, "model_probability": .7, "confidence": 80, "data_quality": 80, "market_reliability": 80, "source_reliability": 80, "sport": "football", "team_ids": ["b1", "b2"]}]
    metrics = optimizer.recalculate_option(legs, 3, .1, PROFILE_CONFIG["balanced"])
    assert metrics["combined_odds"] == pytest.approx(3.0)
    assert metrics["naive_joint_probability"] == pytest.approx(.56)


def test_synthetic_scenarios_a_to_d_and_backtest_pass():
    result = run_stage_five_synthetic_pipeline()
    assert result["status"] == "PASS"
    assert result["scenario_a"]["target_reached"]
    assert result["scenario_b"]["target_reached"]
    assert result["scenario_c"]["target_reached"]
    assert result["scenario_d"]["status"] == "NO_SAFE_TARGET"
    assert result["backtest"]["status"] == "PASS"


def test_backtest_is_timestamp_ordered_and_reports_small_sample_limitation():
    now = datetime.now(timezone.utc)
    result = evaluate_optimizer_backtest([{"selection_at": now, "predicted_joint_probability": .6, "actual_all_legs_hit": True, "target_reached": True, "achieved_odds": 2, "leg_count": 2}])
    assert result["status"] == "PASS" and "Synthetic or small samples" in result["limitation"]


def test_persistence_schema_can_store_auditable_slip_snapshots():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        slip = Slip(risk="balanced", profile="balanced", mode="prematch", target_odds=3, achieved_odds=3.1, optimization_version="stage-five-v1", joint_probability=.4, adjusted_score=.36, correlation_risk="LOW", target_reached=True, configuration_snapshot={"target_tolerance": .1}, warnings=[], diagnostics={"combinations_explored": 4})
        db.add(slip); db.flush(); db.add(SlipLeg(slip_id=slip.id, fixture_id="fixture", odds_snapshot_id="snapshot", leg_order=0, snapshot={"bookmaker_odds": 1.55, "model_probability": .7})); db.commit()
        assert db.query(SlipLeg).one().snapshot["bookmaker_odds"] == 1.55


def test_optimizer_persistence_converts_datetime_snapshots_to_json():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        payload = {"status": "TARGET_REACHED", "target_odds": 2, "profile": "balanced", "mode": "prematch", "slips": [{"target_odds": 2, "combined_odds": 2, "profile": "balanced", "mode": "prematch", "bookmaker": "Book", "provider": "provider", "naive_joint_probability": .5, "risk_adjusted_probability": .5, "correlation_risk": "LOW", "target_reached": True, "legs": [{"fixture_id": "fixture", "snapshot_id": "snapshot", "kickoff_at": datetime.now(timezone.utc), "bookmaker_odds": 2, "model_probability": .5}], "warnings": []}], "diagnostics": {}}
        saved = SlipOptimizer().persist(db, payload, configuration={"start_date": datetime.now(timezone.utc).date()})
        assert saved["slips"][0]["id"] and isinstance(db.query(SlipLeg).one().snapshot["kickoff_at"], str)
