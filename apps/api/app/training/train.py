from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from app.calibration.calibrator import MarketCalibrator
from app.db import SessionLocal
from app.evaluation.backtest import _outcome, walk_forward
from app.evaluation.splits import chronological_split
from app.models import BacktestPrediction, BacktestRun, ModelVersion, TrainingRun
from app.prediction.basketball import BasketballExpectedScoreModel
from app.prediction.football import FootballPoissonModel
from app.training.dataset import build_dataset


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def train_candidate(db, sport: str, *, score_method: str = "poisson", seed: int = 0, feature_version: str | None = None):
    rows = sorted([row for row in build_dataset(db, sport) if row.actual], key=lambda row: row.data_cutoff_at)
    if len(rows) < 10: raise ValueError("at least 10 completed fixtures are required for a candidate model")
    train_rows, validation_rows, test_rows, split_metadata = chronological_split(rows)
    if not train_rows or not validation_rows or not test_rows:
        raise ValueError("chronological timestamp groups must provide train, validation, and test partitions")
    model = (BasketballExpectedScoreModel() if sport == "basketball" else FootballPoissonModel(score_method)).fit(train_rows)
    markets = ("home_moneyline", "away_moneyline", "home_spread_-2.5", "home_spread_-5.5", "over_210.5", "over_220.5") if sport == "basketball" else ("home_win", "draw", "away_win", "btts_yes", "over_1_5", "over_2_5", "over_3_5", "home_handicap_-0.5", "home_handicap_+0.5")
    val_predictions = {key: [] for key in markets}; val_outcomes = {key: [] for key in markets}
    for row in validation_rows:
        output = model.predict(row).get("markets", {})
        for key in markets:
            outcome = _outcome(row, key)
            value = output.get(key, {}).get("win") if isinstance(output.get(key), dict) else output.get(key)
            if value is not None and outcome is not None: val_predictions[key].append(value); val_outcomes[key].append(outcome)
    calibrator = MarketCalibrator().fit(val_predictions, val_outcomes)
    parameters = model.metadata(); parameters["calibration"] = calibrator.metadata(); parameters["calibration_policy"] = "train model on first 60%; fit calibrator on next 20%; test remains untouched"
    now = datetime.now(timezone.utc); version_name = f"{model.name}-{now:%Y%m%d%H%M%S}"
    backtest = walk_forward(rows, lambda: BasketballExpectedScoreModel() if sport == "basketball" else FootballPoissonModel(score_method), markets=markets, minimum_train=max(5, len(rows) // 2), validation_size=max(2, len(rows) // 10), test_size=max(2, len(rows) // 10), sport=sport)
    metrics = _jsonable({"market_families": backtest["metrics"].get("market_families", {}), "markets": backtest["metrics"].get("markets", {}), "multiclass_1x2_brier": backtest["metrics"].get("multiclass_1x2_brier"), "multiclass_1x2_log_loss": backtest["metrics"].get("multiclass_1x2_log_loss"), "baselines": backtest["metrics"].get("baselines", {}), "baseline_comparability": [fold["comparability"] for fold in backtest.get("baseline_folds", [])], "folds": backtest.get("folds", []), "split": split_metadata})
    version = ModelVersion(name=model.name, version=version_name, sport=sport, algorithm=parameters.get("algorithm"), trained_at=now, training_start=train_rows[0].data_cutoff_at, training_end=train_rows[-1].data_cutoff_at, validation_start=validation_rows[0].data_cutoff_at if validation_rows else None, validation_end=validation_rows[-1].data_cutoff_at if validation_rows else None, feature_version=feature_version or ("basketball_features_v1" if sport == "basketball" else "football_features_v1"), parameters=parameters, metrics=metrics, sample_count=len(rows), status="candidate")
    db.add(version); db.flush()
    artifact_root = Path(__file__).resolve().parents[4] / "artifacts"
    artifact_dir = artifact_root / "models"; artifact_dir.mkdir(parents=True, exist_ok=True); artifact_path = artifact_dir / f"{version_name.replace('/', '_')}.json"; artifact_path.write_text(json.dumps(parameters, indent=2), encoding="utf-8"); version.artifact_path = f"models/{artifact_path.name}"
    db.add(TrainingRun(model_version_id=version.id, sport=sport, feature_version=version.feature_version, training_start=version.training_start, training_end=version.training_end, validation_start=version.validation_start, validation_end=version.validation_end, sample_count=len(train_rows), rows_excluded=len(rows) - len(train_rows), seed=seed, parameters=parameters, metrics=metrics))
    if backtest["predictions"]:
        run = BacktestRun(model_version_id=version.id, sport=sport, start_at=backtest["predictions"][0]["data_cutoff_at"], end_at=backtest["predictions"][-1]["data_cutoff_at"], sample_count=len(backtest["predictions"]), metrics=metrics); db.add(run); db.flush()
        for item in backtest["predictions"]: db.add(BacktestPrediction(backtest_run_id=run.id, fixture_id=item["fixture_id"], model_version_id=version.id, prediction_type=item["market"], raw_probability=item["raw_probability"], calibrated_probability=item["calibrated_probability"], actual_outcome=item["actual"], data_cutoff_at=item["data_cutoff_at"], generated_at=now))
    db.commit(); return version, metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--sport", choices=("football", "basketball"), required=True); parser.add_argument("--model", default="football_poisson_v1"); parser.add_argument("--seed", type=int, default=0); args = parser.parse_args()
    with SessionLocal() as db: version, metrics = train_candidate(db, args.sport, score_method="dixon_coles" if "dixon" in args.model else "poisson", seed=args.seed)
    print(json.dumps({"model_version": version.version, "status": version.status, "metrics": metrics}, default=str))
