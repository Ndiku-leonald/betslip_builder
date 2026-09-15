from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from app.db import SessionLocal
from app.models import BacktestPrediction, BacktestRun, ModelVersion, TrainingRun
from app.prediction.basketball import BasketballExpectedScoreModel
from app.prediction.football import FootballPoissonModel
from app.training.dataset import build_dataset
from app.evaluation.backtest import walk_forward


def train_candidate(db, sport: str, *, score_method: str = "poisson", seed: int = 0, feature_version: str | None = None):
    rows = build_dataset(db, sport); rows = [x for x in rows if x.actual]
    if len(rows) < 10: raise ValueError("at least 10 completed fixtures are required for a candidate model")
    model = (BasketballExpectedScoreModel() if sport == "basketball" else FootballPoissonModel(score_method)).fit(rows)
    backtest = walk_forward(rows, lambda: BasketballExpectedScoreModel() if sport == "basketball" else FootballPoissonModel(score_method), markets=("home_moneyline", "away_moneyline") if sport == "basketball" else ("home_win", "draw", "away_win"), minimum_train=max(5, len(rows) // 2), validation_size=max(2, len(rows) // 10), test_size=max(2, len(rows) // 10))
    metrics = backtest["metrics"]
    parameters = model.metadata(); now = datetime.now(timezone.utc)
    version = ModelVersion(name=model.name, version=f"{model.name}-{now:%Y%m%d%H%M%S}", sport=sport, algorithm=parameters.get("algorithm"), trained_at=now, training_start=rows[0].data_cutoff_at, training_end=rows[-1].data_cutoff_at, feature_version=feature_version or ("basketball_features_v1" if sport == "basketball" else "football_features_v1"), parameters=parameters, metrics=metrics, sample_count=len(rows), status="candidate")
    db.add(version); db.flush()
    artifact_dir = Path(__file__).resolve().parents[3] / "artifacts" / "models"; artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = artifact_dir / f"{version.version.replace('/', '_')}.json"; artifact_path.write_text(json.dumps(parameters, indent=2), encoding="utf-8"); version.artifact_path = str(artifact_path)
    db.add(TrainingRun(model_version_id=version.id, sport=sport, feature_version=version.feature_version, training_start=version.training_start, training_end=version.training_end, sample_count=len(rows), seed=seed, parameters=parameters, metrics=metrics))
    if backtest["predictions"]:
        run = BacktestRun(model_version_id=version.id, sport=sport, start_at=backtest["predictions"][0]["data_cutoff_at"], end_at=backtest["predictions"][-1]["data_cutoff_at"], sample_count=len(backtest["predictions"]), metrics=metrics); db.add(run); db.flush()
        for item in backtest["predictions"]: db.add(BacktestPrediction(backtest_run_id=run.id, fixture_id=item["fixture_id"], model_version_id=version.id, prediction_type=item["market"], raw_probability=item["raw_probability"], calibrated_probability=item["calibrated_probability"], actual_outcome=item["actual"], data_cutoff_at=item["data_cutoff_at"], generated_at=now))
    db.commit()
    return version, metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--sport", choices=("football", "basketball"), required=True); parser.add_argument("--model", default="football_poisson_v1"); parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    with SessionLocal() as db:
        version, metrics = train_candidate(db, args.sport, score_method="dixon_coles" if "dixon" in args.model else "poisson", seed=args.seed)
    print(json.dumps({"model_version": version.version, "status": version.status, "metrics": metrics}, default=str))
