"""Deterministic end-to-end TEST DATA pipeline; never a production benchmark."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.evaluation.splits import chronological_split
from app.features.football import FootballFeatureEngine
from app.models import Fixture, ModelVersion, Prediction
from app.prediction.service import PredictionService
from app.providers.api_sports import normalize_football
from app.services.ingestion import ingest_fixtures
from app.training.train import train_candidate


def _fixture(provider_id, when, status, home_score=None, away_score=None):
    return normalize_football({
        "fixture": {"id": provider_id, "date": when.isoformat(), "status": {"short": "FT" if status == "finished" else "NS"}},
        "league": {"id": 39, "name": "Synthetic TEST DATA", "country": "Test", "season": 2024},
        "teams": {"home": {"id": 1, "name": "Synthetic Home"}, "away": {"id": 2, "name": "Synthetic Away"}},
        "goals": {"home": home_score, "away": away_score},
    })


def run() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    historical = []
    for index in range(28):
        # Four fixtures share one observation timestamp; the split helper must
        # keep this group in one partition.
        group = 12 if index in (12, 13, 14, 15) else index
        when = start + timedelta(days=group)
        historical.append(_fixture(index + 1, when, "finished", index % 3, (index + 1) % 2))
    upcoming = _fixture(999, start + timedelta(days=40), "scheduled")

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ingest_fixtures(db, historical + [upcoming])
        rows = FootballFeatureEngine(minimum_history=5).build_and_persist(db, include_unfinished=True)
        completed = [row for row in rows if row.actual]
        train_rows, validation_rows, test_rows, split = chronological_split(completed)
        assert train_rows and validation_rows and test_rows
        timestamp_sets = [set(row.data_cutoff_at for row in part) for part in (train_rows, validation_rows, test_rows)]
        assert not (timestamp_sets[0] & timestamp_sets[1] or timestamp_sets[1] & timestamp_sets[2] or timestamp_sets[0] & timestamp_sets[2])
        version, metrics = train_candidate(db, "football")
        version.status = "champion"  # controlled test-only activation
        db.commit()
        target_id = db.scalar(select(Fixture.id).where(Fixture.provider_fixture_id == "999"))
        payload = PredictionService(minimum_history=5).generate(db, target_id)
        persisted = db.scalar(select(Prediction).where(Prediction.fixture_id == target_id))
        assert persisted is not None and payload["model_version"] == version.version
        assert payload["calibration_status_by_market"]
        markets = payload["calibrated_probability"]
        assert abs(sum(markets[key] for key in ("home_win", "draw", "away_win")) - 1) < 1e-6
        assert "calibration" in (version.parameters or {})
        print("SYNTHETIC TEST DATA — NOT REAL MODEL PERFORMANCE")
        print({"historical_rows": len(completed), "train": len(train_rows), "validation": len(validation_rows), "test": len(test_rows), "model_version": version.version, "prediction_persisted": True, "calibration_status": payload["calibration_status"], "test_metric_families": list(metrics.get("market_families", {}))})


if __name__ == "__main__":
    run()
