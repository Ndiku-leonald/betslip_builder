from __future__ import annotations

import math
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Fixture, LivePredictionSnapshot, LiveMatchSnapshot


def _bucket(sport: str, snapshot: LiveMatchSnapshot) -> str:
    if sport == "football":
        minute = snapshot.minute or 0
        if minute <= 15: return "0-15"
        if minute <= 30: return "16-30"
        if minute < 46: return "31-HT"
        if minute <= 60: return "46-60"
        if minute <= 75: return "61-75"
        return "76+"
    period = str(snapshot.period or "").upper()
    return "OT" if period.startswith("OT") else period if period in {"Q1", "Q2", "Q3", "Q4"} else "UNKNOWN"


def _log_loss(probability: float, outcome: bool) -> float:
    p = min(1.0 - 1e-12, max(1e-12, probability))
    return -math.log(p if outcome else 1.0 - p)


def evaluate_live_backtest(db: Session, fixture_id: str | None = None, limit: int = 5000) -> dict:
    query = select(LivePredictionSnapshot, LiveMatchSnapshot, Fixture).join(LiveMatchSnapshot, LivePredictionSnapshot.live_match_snapshot_id == LiveMatchSnapshot.id).join(Fixture, Fixture.id == LivePredictionSnapshot.fixture_id).order_by(LivePredictionSnapshot.observed_at.asc()).limit(limit)
    if fixture_id is not None:
        query = query.where(LivePredictionSnapshot.fixture_id == fixture_id)
    rows = db.execute(query).all()
    buckets: dict[str, list[tuple[float, bool]]] = defaultdict(list)
    for prediction, snapshot, fixture in rows:
        if fixture.home_score is None or fixture.away_score is None:
            continue
        probabilities = prediction.live_probability or {}
        if fixture.sport_id is None:
            continue
        # The fixture outcome is used only after the immutable prediction was
        # generated; it is never read by the live model or snapshot writer.
        sport = "basketball" if "moneyline" in probabilities else "football"
        if sport == "football":
            keys = ("home_win", "draw", "away_win")
            outcome = "home_win" if fixture.home_score > fixture.away_score else "draw" if fixture.home_score == fixture.away_score else "away_win"
        else:
            keys = ("home_moneyline", "away_moneyline")
            outcome = "home_moneyline" if fixture.home_score > fixture.away_score else "away_moneyline"
        if not all(isinstance(probabilities.get(key), (int, float)) for key in keys):
            continue
        if sport == "football":
            brier = sum((float(probabilities[key]) - (1.0 if key == outcome else 0.0)) ** 2 for key in keys)
            logloss = _log_loss(float(probabilities[outcome]), True)
            bucket_key = f"football:{_bucket(sport, snapshot)}"
        else:
            brier = sum((float(probabilities[key]) - (1.0 if key == outcome else 0.0)) ** 2 for key in keys)
            logloss = _log_loss(float(probabilities[outcome]), True)
            bucket_key = f"basketball:{_bucket(sport, snapshot)}"
        buckets[bucket_key].append((brier, logloss))
    all_scores = [score for values in buckets.values() for score in values]
    result = {"status": "EVALUATED" if all_scores else "INSUFFICIENT_EVIDENCE", "sample_count": len(all_scores), "brier_score": round(sum(item[0] for item in all_scores) / len(all_scores), 6) if all_scores else None, "log_loss": round(sum(item[1] for item in all_scores) / len(all_scores), 6) if all_scores else None, "calibration": {"status": "DESCRIPTIVE_ONLY", "sample_count": len(all_scores)}, "buckets": {key: {"sample_count": len(values), "brier_score": round(sum(item[0] for item in values) / len(values), 6), "log_loss": round(sum(item[1] for item in values) / len(values), 6)} for key, values in sorted(buckets.items())}, "warnings": ["Live backtest uses only immutable prediction snapshots and final outcomes; small samples are descriptive, not production calibration evidence."]}
    return result
