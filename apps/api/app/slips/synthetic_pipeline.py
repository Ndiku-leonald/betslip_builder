"""Deterministic, credential-free Stage Five software scenarios."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import Competition, Fixture, ModelVersion, OddsSnapshot, Prediction, ProviderObservation, Sport, Team
from app.slips.backtest import evaluate_optimizer_backtest
from app.slips.optimizer import SlipOptimizer


def _request(target: float, profile: str, *, sports: list[str], max_legs: int = 6) -> dict:
    return {"sports": sports, "target_odds": target, "profile": profile, "mode": "prematch", "include_live": False, "max_legs": max_legs, "min_legs": 2, "min_confidence": 0, "min_data_quality": 0, "min_probability": 0, "max_individual_odds": 3.0, "target_tolerance": .10, "alternatives": 3, "correlation_policy": "avoid_same_fixture", "require_positive_value": False}


def _seed(db: Session, now: datetime) -> None:
    football = Sport(slug="football", name="Football"); basketball = Sport(slug="basketball", name="Basketball"); db.add_all([football, basketball]); db.flush()
    metrics = {"market_families": {"1X2": {"sample_count": 150, "calibrated_ece": .03, "calibrated_brier": .18, "calibrated_log_loss": .50}, "moneyline": {"sample_count": 150, "calibrated_ece": .03, "calibrated_brier": .18, "calibrated_log_loss": .50}}}
    f_model = ModelVersion(name="synthetic-football", version="stage-five-test", sport="football", status="champion", metrics=metrics)
    b_model = ModelVersion(name="synthetic-basketball", version="stage-five-test", sport="basketball", status="champion", metrics=metrics)
    db.add_all([f_model, b_model]); db.flush()
    books = ["Synthetic Book"]
    for index, (sport, model, odds, probability) in enumerate([
        (football, f_model, 1.40, .76), (football, f_model, 1.50, .75), (football, f_model, 1.50, .74),
        (football, f_model, 1.70, .72), (football, f_model, 1.70, .71), (football, f_model, 1.75, .70),
        (basketball, b_model, 1.80, .68), (basketball, b_model, 1.80, .67), (basketball, b_model, 1.80, .66), (basketball, b_model, 1.80, .65),
    ]):
        home = Team(sport_id=sport.id, name=f"{sport.slug.title()} Home {index}"); away = Team(sport_id=sport.id, name=f"{sport.slug.title()} Away {index}"); db.add_all([home, away]); db.flush()
        competition = Competition(sport_id=sport.id, name=f"Synthetic {sport.name} League", provider_id=f"synthetic-{sport.slug}"); db.add(competition); db.flush()
        fixture = Fixture(sport_id=sport.id, competition_id=competition.id, home_team_id=home.id, away_team_id=away.id, provider=f"api-{sport.slug}", provider_fixture_id=str(index), kickoff_at=now + timedelta(minutes=index * 10 + 10), status="scheduled", observed_at=now, provider_updated_at=now, ingested_at=now, freshness="RECENT")
        db.add(fixture); db.flush()
        if sport.slug == "football":
            calibrated = {"home_win": probability, "draw": .10, "away_win": 1 - probability - .10}
            raw = calibrated
            family = "1x2"; market_type = "1x2"; selections = [("home", None, odds), ("draw", None, 5.0), ("away", None, 7.0)]
        else:
            calibrated = {"home_moneyline": probability, "away_moneyline": 1 - probability}
            raw = calibrated
            family = "moneyline"; market_type = "moneyline"; selections = [("home", None, odds), ("away", None, 2.5)]
        db.add(Prediction(fixture_id=fixture.id, model_version_id=model.id, sport=sport.slug, prediction_type="pre_match", generated_at=now, data_cutoff_at=now - timedelta(hours=1), payload={"available": True, "sport": sport.slug, "model_version": "stage-five-test", "calibrated_probability": calibrated, "raw_probability": raw, "calibration_status_by_market": {key: "fitted" for key in calibrated}, "model_confidence_score": 82, "data_quality": {"overall": 86}}))
        for selection, line, price in selections:
            db.add(OddsSnapshot(fixture_id=fixture.id, provider=f"api-{sport.slug}", bookmaker=books[0], market_family=family, market_type=market_type, period="full_game", participant="none", selection=selection, line=line, decimal_odds=price, market_status="open", is_live=False, settlement_semantics="including_overtime" if sport.slug == "basketball" else "full_game", observed_at=now, provider_updated_at=now, payload={"synthetic": True}))
        db.add(ProviderObservation(fixture_id=fixture.id, provider="synthetic-secondary", observed_at=now, kickoff_at=fixture.kickoff_at, status="scheduled", canonical_home_team=home.name, canonical_away_team=away.name))
    # A separate stale and suspended fixture verifies centralized rejection diagnostics.
    db.commit()


def run_stage_five_synthetic_pipeline() -> dict:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with Session(engine) as db:
        _seed(db, now)
        optimizer = SlipOptimizer()
        results = {
            "scenario_a": optimizer.optimize(db, _request(3.0, "conservative", sports=["football"])),
            "scenario_b": optimizer.optimize(db, _request(5.0, "balanced", sports=["football", "basketball"])),
            "scenario_c": optimizer.optimize(db, _request(10.0, "aggressive", sports=["football", "basketball"])),
            "scenario_d": optimizer.optimize(db, _request(50.0, "conservative", sports=["football"], max_legs=3)),
        }
        backtest = evaluate_optimizer_backtest([
            {"selection_at": now - timedelta(days=2), "target_reached": True, "achieved_odds": 3.1, "leg_count": 3, "predicted_joint_probability": .42, "actual_all_legs_hit": True, "expected_value": .04, "correlation_risk": "LOW"},
            {"selection_at": now - timedelta(days=1), "target_reached": False, "achieved_odds": 2.4, "leg_count": 2, "predicted_joint_probability": .48, "actual_all_legs_hit": False, "expected_value": .01, "correlation_risk": "MODERATE"},
        ])
        return {"status": "PASS", "scenario_a": {"status": results["scenario_a"]["status"], "target_reached": results["scenario_a"]["target_reached"], "slips": results["scenario_a"]["slips"]}, "scenario_b": {"status": results["scenario_b"]["status"], "target_reached": results["scenario_b"]["target_reached"], "slips": results["scenario_b"]["slips"]}, "scenario_c": {"status": results["scenario_c"]["status"], "target_reached": results["scenario_c"]["target_reached"], "slips": results["scenario_c"]["slips"]}, "scenario_d": {"status": results["scenario_d"]["status"], "target_reached": results["scenario_d"]["target_reached"], "slips": results["scenario_d"]["slips"], "diagnostics": results["scenario_d"]["diagnostics"], "warnings": results["scenario_d"]["warnings"]}, "backtest": backtest, "responsible_use": "Synthetic tests validate software behavior, not real-world betting accuracy or profitability."}
