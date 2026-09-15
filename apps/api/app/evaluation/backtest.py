from __future__ import annotations

from app.calibration.calibrator import MarketCalibrator
from app.evaluation.metrics import brier_score, expected_calibration_error, log_loss, mae


def _outcome(row, key):
    actual = row.actual or {}
    if key in actual: return actual[key]
    if key == "home_moneyline": return actual.get("home_win")
    if key == "away_moneyline": return actual.get("away_win")
    if key == "over_2_5": return float(actual.get("home_goals", 0) + actual.get("away_goals", 0) > 2.5)
    return None


def walk_forward(rows, model_factory, *, markets: tuple[str, ...] = ("home_win", "draw", "away_win"), minimum_train: int = 10, validation_size: int = 5, test_size: int = 5) -> dict:
    ordered = sorted([row for row in rows if row.actual], key=lambda row: row.data_cutoff_at)
    predictions = []
    cursor = minimum_train
    while cursor < len(ordered):
        train = ordered[:cursor]; validation = ordered[cursor:cursor + validation_size]; test = ordered[cursor + validation_size:cursor + validation_size + test_size]
        if not test: break
        model = model_factory().fit(train)
        val_preds = {key: [] for key in markets}; val_actuals = {key: [] for key in markets}
        for row in validation:
            output = model.predict(row).get("markets", {})
            for key in markets:
                if key in output and _outcome(row, key) is not None: val_preds[key].append(output[key]); val_actuals[key].append(_outcome(row, key))
        calibrator = MarketCalibrator().fit(val_preds, val_actuals)
        for row in test:
            output = model.predict(row).get("markets", {}); calibrated = calibrator.transform({key: output[key] for key in markets if key in output})
            for key in markets:
                actual = _outcome(row, key)
                if key in output and actual is not None: predictions.append({"fixture_id": row.fixture_id, "market": key, "raw_probability": output[key], "calibrated_probability": calibrated.get(key, output[key]), "actual": actual, "data_cutoff_at": row.data_cutoff_at, "calibrator": calibrator.metadata().get(key)})
        cursor += test_size
    raw = [x["raw_probability"] for x in predictions]; calibrated = [x["calibrated_probability"] for x in predictions]; actual = [x["actual"] for x in predictions]
    return {"predictions": predictions, "metrics": {"sample_count": len(predictions), "raw_brier": brier_score(raw, actual), "calibrated_brier": brier_score(calibrated, actual), "raw_log_loss": log_loss(raw, actual), "calibrated_log_loss": log_loss(calibrated, actual), "calibrated_ece": expected_calibration_error(calibrated, actual), "probability_mae": mae([x["raw_probability"] for x in predictions], actual)}}
