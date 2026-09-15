from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.basketball import BasketballFeatureEngine
from app.features.football import FootballFeatureEngine
from app.models import Fixture, FixtureFeatureSnapshot, ModelVersion, Prediction, Sport
from app.prediction.basketball import BasketballExpectedScoreModel
from app.prediction.football import FootballPoissonModel


class PredictionUnavailable(RuntimeError):
    pass


class PredictionService:
    def __init__(self, minimum_history: int = 5) -> None: self.minimum_history = minimum_history

    def _model(self, version: ModelVersion):
        params = version.parameters or {}
        if version.sport == "basketball":
            model = BasketballExpectedScoreModel()
        else:
            model = FootballPoissonModel(params.get("score_method", "poisson"), params.get("goal_cap", 10), params.get("rho", -.08))
        for key in ("home_mean", "away_mean", "margin_sd", "total_sd"):
            if key in params: setattr(model, key, params[key])
        return model

    def generate(self, db: Session, fixture_id: str, model_version_id: str | None = None) -> dict:
        fixture = db.get(Fixture, fixture_id)
        if fixture is None: raise PredictionUnavailable("Fixture not found")
        sport = db.scalar(select(Sport.slug).where(Sport.id == fixture.sport_id)) or "unknown"
        version = db.get(ModelVersion, model_version_id) if model_version_id else db.scalar(select(ModelVersion).where(ModelVersion.sport == sport, ModelVersion.status == "champion").order_by(ModelVersion.trained_at.desc()))
        if version is None: raise PredictionUnavailable("No trained production model is available")
        engine = BasketballFeatureEngine(self.minimum_history) if sport == "basketball" else FootballFeatureEngine(self.minimum_history)
        rows = [row for row in engine.build(db, include_unfinished=True) if row.fixture_id == fixture_id]
        if not rows: raise PredictionUnavailable("Fixture has no kickoff time")
        row = rows[0]
        if row.data_quality.get("history_count", 0) < self.minimum_history: raise PredictionUnavailable(f"Insufficient pre-match history ({row.data_quality.get('history_count', 0)}/{self.minimum_history} team matches)")
        output = self._model(version).predict(row)
        quality = row.data_quality.get("overall", 0.0)
        confidence = round(max(0.0, min(100.0, quality * .8 + 20.0)), 2)
        generated = datetime.now(timezone.utc)
        payload = {"available": True, "fixture_id": fixture.id, "sport": sport, "generated_at": generated.isoformat(), "data_cutoff_at": row.data_cutoff_at.isoformat(), "model_version": version.version, "model": output.get("model"), **{key: value for key, value in output.items() if key != "model"}, "data_quality": row.data_quality, "model_confidence_score": confidence, "warnings": ["Model estimate, not bookmaker odds or certainty."]}
        db.add(Prediction(fixture_id=fixture.id, model_version_id=version.id, sport=sport, generated_at=generated, prediction_type="pre_match", data_cutoff_at=row.data_cutoff_at, features_version=engine.feature_version, payload=payload)); db.commit()
        return payload

    def list_models(self, db: Session, sport: str | None = None):
        query = select(ModelVersion).order_by(ModelVersion.trained_at.desc())
        if sport: query = query.where(ModelVersion.sport == sport)
        return list(db.scalars(query))
