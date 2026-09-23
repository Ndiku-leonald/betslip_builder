from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.live.models import BasketballLivePosterior, FootballLivePosterior
from app.live.persistence import latest_live_match_snapshot, live_prediction_history, state_for_fixture
from app.live.quality import evaluate_live_data_quality, live_recommendation_gate
from app.live.ranking import rank_live_markets
from app.live.state import LiveMatchState
from app.markets.storage import latest_market_snapshots
from app.markets.value import MarketValueService, market_group_key, odds_consensus
from app.models import Fixture, LiveMarketSnapshot, LivePredictionSnapshot, ModelVersion, Prediction, Sport
from app.odds.ontology import NormalizedMarket
from app.providers.reliability import source_reliability


STALE_WARNING = "Live data too stale for a reliable market evaluation."
NO_PRICE_WARNING = "Live market prices unavailable — no betting-market recommendation generated."


def _latest_prematch(db: Session, fixture_id: str) -> Prediction | None:
    return db.scalar(select(Prediction).where(Prediction.fixture_id == fixture_id, Prediction.prediction_type == "pre_match").order_by(Prediction.generated_at.desc()).limit(1))


def _prior_payload(prediction: Prediction | None) -> dict:
    if prediction is None:
        return {}
    payload = prediction.payload or {}
    prior = dict(payload.get("calibrated_probability", payload.get("markets", {})) or {})
    prior.update({key: payload[key] for key in ("expected_home_goals", "expected_away_goals", "expected_home_score", "expected_away_score", "expected_margin", "expected_total", "margin_sd", "total_sd") if key in payload})
    variance = payload.get("variance", {}) or {}
    prior.setdefault("margin_sd", variance.get("margin_sd", 12.0)); prior.setdefault("total_sd", variance.get("total_sd", 18.0))
    return prior


def _delta(pre: dict, live: dict) -> dict:
    return {key: round(float(live[key]) - float(pre[key]), 6) for key in live if isinstance(live.get(key), (int, float)) and isinstance(pre.get(key), (int, float))}


def _calibration(prediction: Prediction | None) -> str:
    if prediction is None:
        return "INSUFFICIENT_EVIDENCE"
    status = (prediction.payload or {}).get("calibration_status", "INSUFFICIENT_EVIDENCE")
    return "CALIBRATED" if status in {"fitted", "CALIBRATED"} else "PARTIALLY_CALIBRATED" if status in {"partial", "family_fitted", "PARTIALLY_CALIBRATED"} else "UNCALIBRATED"


class LiveIntelligenceService:
    def __init__(self, value_service: MarketValueService | None = None) -> None:
        self.value_service = value_service or MarketValueService()

    def _state(self, db: Session, fixture: Fixture, sport: str) -> LiveMatchState:
        return state_for_fixture(db, fixture, sport)

    def prediction(self, db: Session, fixture_id: str, *, persist: bool = True) -> dict:
        fixture = db.get(Fixture, fixture_id)
        if fixture is None:
            raise LookupError("Fixture not found")
        sport = db.scalar(select(Sport.slug).where(Sport.id == fixture.sport_id)) or "unknown"
        state = self._state(db, fixture, sport)
        prediction = _latest_prematch(db, fixture_id)
        prior = _prior_payload(prediction)
        quality = evaluate_live_data_quality(state, provider_reliability=source_reliability(state.source_provider)["reliability_score"] / 100, pre_match_available=prediction is not None)
        if sport == "football":
            posterior = FootballLivePosterior.from_prior(state, prior)
            live_probability = posterior.live_probability
            pre_probability = posterior.pre_match_probability
            outputs = {"expected_home_goals": (state.home_score or 0) + posterior.home_remaining_mean, "expected_away_goals": (state.away_score or 0) + posterior.away_remaining_mean}
        elif sport == "basketball":
            posterior = BasketballLivePosterior.from_prior(state, prior)
            live_probability = posterior.live_probability
            pre_probability = posterior.pre_match_probability
            outputs = {"expected_home_score": posterior.expected_home_score, "expected_away_score": posterior.expected_away_score, "expected_margin": posterior.expected_home_score - posterior.expected_away_score, "expected_total": posterior.expected_home_score + posterior.expected_away_score, "variance": {"margin_sd": posterior.margin_sd, "total_sd": posterior.total_sd}}
        else:
            return {"available": False, "fixture_id": fixture_id, "reason": "Live model unavailable for this competition."}
        confidence = round(min(100.0, max(0.0, (prediction.payload or {}).get("model_confidence_score", 35.0) * .55 + quality["overall"] * 45.0 + posterior.confidence_evidence * 15.0)), 2)
        warnings = list(quality.get("warnings", []))
        if not warnings and state.status not in {"live", "halftime"}: warnings.append("Fixture is not currently live.")
        result = {"available": True, "fixture_id": fixture_id, "sport": sport, "state": state.as_dict(), "pre_match_prediction": pre_probability, "live_prediction": live_probability, "probability_delta": _delta(pre_probability, live_probability), "model_version": (prediction.payload or {}).get("model_version") if prediction else None, "model": posterior.method, "confidence": confidence, "data_quality": quality, "calibration_status": _calibration(prediction), "warnings": warnings, "market_intelligence": None, **outputs}
        if persist:
            live_row = latest_live_match_snapshot(db, fixture_id)
            if live_row is not None:
                exists = db.scalar(select(LivePredictionSnapshot).where(LivePredictionSnapshot.fixture_id == fixture_id, LivePredictionSnapshot.observed_at == live_row.observed_at))
                if exists is None:
                    db.add(LivePredictionSnapshot(fixture_id=fixture_id, live_match_snapshot_id=live_row.id, pre_match_prediction_id=prediction.id if prediction else None, model_version_id=prediction.model_version_id if prediction else None, sport=sport, model_version=(prediction.payload or {}).get("model_version") if prediction else None, observed_at=live_row.observed_at, generated_at=datetime.now(timezone.utc), pre_match_probability=pre_probability, live_probability=live_probability, probability_delta=result["probability_delta"], markets=live_probability, confidence=confidence, data_quality=quality, calibration_status=result["calibration_status"], warnings=warnings))
                    db.commit()
        return result

    def markets(self, db: Session, fixture_id: str, *, profile: str = "balanced", persist: bool = True) -> dict:
        fixture = db.get(Fixture, fixture_id)
        if fixture is None:
            raise LookupError("Fixture not found")
        prediction = self.prediction(db, fixture_id, persist=persist)
        if not prediction.get("available"):
            return {"fixture_id": fixture_id, "values": [], "opportunities": [], "warnings": prediction.get("warnings", []), "reason": prediction.get("reason")}
        sport = prediction["sport"]
        state = self._state(db, fixture, sport)
        prior = _prior_payload(_latest_prematch(db, fixture_id))
        posterior = FootballLivePosterior.from_prior(state, prior) if sport == "football" else BasketballLivePosterior.from_prior(state, prior)
        snapshots = latest_market_snapshots(db, fixture_id)
        if not snapshots:
            prediction["warnings"] = list(dict.fromkeys(prediction.get("warnings", []) + [NO_PRICE_WARNING]))
            return {"fixture_id": fixture_id, "values": [], "opportunities": [], "warnings": prediction["warnings"], "prediction": prediction, "odds_consensus": []}
        grouped = {}
        for item in snapshots: grouped.setdefault(market_group_key(item), []).append(item)
        values = []
        for snapshot in snapshots:
            normalized = NormalizedMarket(fixture_id=snapshot.fixture_id, sport=sport, bookmaker=snapshot.bookmaker or "", provider=snapshot.provider, market_family=snapshot.market_family or "unknown", market_type=snapshot.market_type or "unknown", period=snapshot.period or "full_game", participant=snapshot.participant or "none", selection=snapshot.selection or "unknown", line=snapshot.line, decimal_odds=snapshot.decimal_odds, status=snapshot.market_status, settlement_semantics=snapshot.settlement_semantics or "full_game", observed_at=snapshot.observed_at or snapshot.created_at, provider_updated_at=snapshot.provider_updated_at, source_event_id=snapshot.source_event_id, raw=snapshot.payload)
            model_info = posterior.probabilities_for_market(normalized)
            group = [NormalizedMarket(fixture_id=item.fixture_id, sport=sport, bookmaker=item.bookmaker or "", provider=item.provider, market_family=item.market_family or "unknown", market_type=item.market_type or "unknown", period=item.period or "full_game", participant=item.participant or "none", selection=item.selection or "unknown", line=item.line, decimal_odds=item.decimal_odds, status=item.market_status, settlement_semantics=item.settlement_semantics or "full_game", observed_at=item.observed_at or item.created_at, provider_updated_at=item.provider_updated_at, source_event_id=item.source_event_id, raw=item.payload) for item in grouped[market_group_key(snapshot)]]
            source = source_reliability(snapshot.provider)
            value = self.value_service.evaluate(normalized, model_probability_structure=model_info, confidence=prediction["confidence"], data_quality=prediction["data_quality"]["overall"] * 100, market_reliability=source["reliability_score"], market_reliability_components=source, source_reliability=source["reliability_score"], source_reliability_components=source, provider_agreement=prediction["data_quality"].get("source_agreement"), calibration_status=model_info.get("calibration_status", "UNCALIBRATED"), market_group=group, ttl_seconds=get_settings().live_odds_stale_seconds)
            value["compatibility"] = model_info.get("status", "UNSUPPORTED"); value["reason"] = model_info.get("reason"); values.append(value)
        opportunities = rank_live_markets(values, profile=profile)
        gate_ok, gate_reason = live_recommendation_gate(prediction["data_quality"], odds_available=bool(snapshots), odds_fresh=any(item["freshness"]["status"] == "CURRENT" for item in values))
        status_warnings = []
        if any(item.market_status == "suspended" for item in snapshots):
            status_warnings.append("Market currently suspended.")
        if any(item.market_status == "closed" for item in snapshots):
            status_warnings.append("Market currently closed.")
        if not any(item.market_status == "open" and item["freshness"]["status"] == "CURRENT" for item in values):
            status_warnings.append(NO_PRICE_WARNING)
        if not gate_ok:
            prediction["warnings"] = list(dict.fromkeys(prediction.get("warnings", []) + status_warnings + [gate_reason]))
            opportunities = []
        warnings = list(dict.fromkeys(prediction.get("warnings", []) + status_warnings))
        if persist:
            live_prediction_row = db.scalar(select(LivePredictionSnapshot).where(LivePredictionSnapshot.fixture_id == fixture_id).order_by(LivePredictionSnapshot.observed_at.desc()).limit(1))
            if live_prediction_row is not None:
                for snapshot, value in zip(snapshots, values):
                    existing = db.scalar(select(LiveMarketSnapshot).where(LiveMarketSnapshot.live_prediction_snapshot_id == live_prediction_row.id, LiveMarketSnapshot.odds_snapshot_id == snapshot.id).limit(1))
                    if existing is None:
                        db.add(LiveMarketSnapshot(fixture_id=fixture_id, live_prediction_snapshot_id=live_prediction_row.id, odds_snapshot_id=snapshot.id, provider=snapshot.provider, bookmaker=snapshot.bookmaker, market_family=snapshot.market_family or "unknown", market_type=snapshot.market_type, participant=snapshot.participant, selection=snapshot.selection or "unknown", line=snapshot.line, decimal_odds=snapshot.decimal_odds, market_status=snapshot.market_status, odds_observed_at=snapshot.observed_at, evaluated_at=datetime.now(timezone.utc), model_probability=value.get("model_probability"), push_probability=value.get("model_push_probability"), expected_value=value.get("expected_value"), suitability=value.get("suitability", "NOT_ELIGIBLE"), value_payload=value))
                db.commit()
        return {"fixture_id": fixture_id, "values": values, "opportunities": opportunities, "warnings": warnings, "prediction": prediction, "odds_consensus": odds_consensus([NormalizedMarket(fixture_id=item.fixture_id, sport=sport, bookmaker=item.bookmaker or "", provider=item.provider, market_family=item.market_family or "unknown", market_type=item.market_type or "unknown", period=item.period or "full_game", participant=item.participant or "none", selection=item.selection or "unknown", line=item.line, decimal_odds=item.decimal_odds, status=item.market_status, settlement_semantics=item.settlement_semantics or "full_game", observed_at=item.observed_at or item.created_at, provider_updated_at=item.provider_updated_at) for item in snapshots])}

    def history(self, db: Session, fixture_id: str, limit: int = 500) -> list[dict]:
        return [{"id": item.id, "fixture_id": item.fixture_id, "observed_at": item.observed_at, "generated_at": item.generated_at, "pre_match_probability": item.pre_match_probability, "live_probability": item.live_probability, "probability_delta": item.probability_delta, "confidence": item.confidence, "data_quality": item.data_quality, "calibration_status": item.calibration_status, "warnings": item.warnings} for item in live_prediction_history(db, fixture_id, limit)]
