from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.features.basketball import BasketballFeatureEngine
from app.features.football import FootballFeatureEngine
from app.models import Fixture, FixtureFeatureSnapshot, ModelVersion, Prediction, Sport
from app.prediction.basketball import BasketballExpectedScoreModel
from app.prediction.football import FootballPoissonModel
from app.calibration.calibrator import MarketCalibrator


class PredictionUnavailable(RuntimeError):
    pass


def distribution_certainty(markets: dict, sport: str) -> float:
    """Return a higher-is-better separation score, independent of probability."""
    keys = ("home_win", "draw", "away_win") if sport == "football" else ("home_moneyline", "away_moneyline")
    values = [float(markets[key]) for key in keys if key in markets and isinstance(markets[key], (int, float))]
    if len(values) != len(keys):
        return 0.0
    total = sum(values) or 1.0
    values = [max(1e-12, value / total) for value in values]
    import math
    entropy = -sum(value * math.log(value) for value in values)
    return round(max(0.0, min(100.0, (1.0 - entropy / math.log(len(values))) * 100.0)), 2)


class PredictionService:
    def __init__(self, minimum_history: int = 5) -> None: self.minimum_history = minimum_history

    def _model(self, version: ModelVersion):
        params = version.parameters or {}
        if version.sport == "basketball":
            model = BasketballExpectedScoreModel()
        else:
            model = FootballPoissonModel(params.get("score_method", "poisson"), params.get("goal_cap", 10), params.get("rho", -.08))
        for key in ("home_mean", "away_mean", "margin_sd", "total_sd", "home_score_sd", "away_score_sd"):
            if key in params: setattr(model, key, params[key])
        return model

    def generate(self, db: Session, fixture_id: str, model_version_id: str | None = None) -> dict:
        fixture = db.get(Fixture, fixture_id)
        if fixture is None: raise PredictionUnavailable("Fixture not found")
        sport = db.scalar(select(Sport.slug).where(Sport.id == fixture.sport_id)) or "unknown"
        if fixture.status in {"live", "halftime"}: raise PredictionUnavailable("Live analysis is not available in Stage Two; use the future live model")
        if fixture.status == "finished": raise PredictionUnavailable("Finished fixtures require explicit historical/research mode")
        if fixture.status != "scheduled": raise PredictionUnavailable("Predictions are only available for scheduled upcoming fixtures")
        version = db.get(ModelVersion, model_version_id) if model_version_id else db.scalar(select(ModelVersion).where(ModelVersion.sport == sport, ModelVersion.status == "champion").order_by(ModelVersion.trained_at.desc()))
        if version is None: raise PredictionUnavailable("No trained production model is available")
        engine = BasketballFeatureEngine(self.minimum_history) if sport == "basketball" else FootballFeatureEngine(self.minimum_history)
        rows = [row for row in engine.build(db, include_unfinished=True) if row.fixture_id == fixture_id]
        if not rows: raise PredictionUnavailable("Fixture has no kickoff time")
        row = rows[0]
        if row.data_quality.get("history_count", 0) < self.minimum_history: raise PredictionUnavailable(f"Insufficient pre-match history ({row.data_quality.get('history_count', 0)}/{self.minimum_history} team matches)")
        output = self._model(version).predict(row); raw_markets = output.get("markets", {})
        calibration_meta = (version.parameters or {}).get("calibration", {})
        calibrator = MarketCalibrator.from_metadata(calibration_meta)
        calibrated_markets = calibrator.transform(raw_markets)
        market_status = calibrator.status_by_market(raw_markets.keys())
        # Overall status describes the persisted calibration set.  The
        # market-specific map still explicitly marks output markets without a
        # fitted calibrator as insufficient.
        calibration_status = calibrator.overall_status(calibration_meta.keys()) if calibration_meta else "insufficient_samples"
        quality = row.data_quality.get("overall", 0.0)
        sample = min(100.0, 100.0 * row.data_quality.get("history_count", 0) / max(1, self.minimum_history * 2))
        calibration_quality = 100.0 * sum(value == "fitted" for value in market_status.values()) / max(1, len(market_status))
        family = "1X2" if sport == "football" else "moneyline"
        family_metrics = (version.metrics or {}).get("market_families", {}).get(family, {})
        model_stability = max(0.0, min(100.0, 100.0 * (1.0 - float(family_metrics.get("calibrated_ece", 0.65))))) if family_metrics else 30.0
        competition = row.data_quality.get("competition_coverage", 25.0)
        confidence_components = {"data_quality": quality, "sample_quality": sample, "calibration_quality": calibration_quality, "competition_coverage": competition, "distribution_certainty": distribution_certainty(calibrated_markets, sport), "model_stability": model_stability}
        # Calibration and data coverage are safety floors; a separated outcome is
        # not allowed to hide weak evidence.
        confidence = round(sum(confidence_components.values()) / len(confidence_components), 2)
        confidence = round(min(confidence, quality, sample, max(calibration_quality, 35.0), competition), 2)
        generated = datetime.now(timezone.utc)
        payload = {"available": True, "fixture_id": fixture.id, "sport": sport, "generated_at": generated.isoformat(), "data_cutoff_at": row.data_cutoff_at.isoformat(), "model_version": version.version, "model": output.get("model"), **{key: value for key, value in output.items() if key != "model" and key != "markets"}, "markets": calibrated_markets, "raw_probability": raw_markets, "calibrated_probability": calibrated_markets, "calibration_status": calibration_status, "calibration_status_by_market": market_status, "data_quality": row.data_quality, "confidence_components": confidence_components, "model_confidence_score": confidence, "warnings": ["Model estimate, not bookmaker odds or certainty."]}
        db.add(Prediction(fixture_id=fixture.id, model_version_id=version.id, sport=sport, generated_at=generated, prediction_type="pre_match", data_cutoff_at=row.data_cutoff_at, features_version=engine.feature_version, payload=payload)); db.commit()
        return payload

    def list_models(self, db: Session, sport: str | None = None):
        query = select(ModelVersion).order_by(ModelVersion.trained_at.desc())
        if sport: query = query.where(ModelVersion.sport == sport)
        return list(db.scalars(query))
