from __future__ import annotations

from collections import defaultdict

from app.calibration.calibrator import MarketCalibrator
from app.evaluation.metrics import brier_score, categorical_log_loss, expected_calibration_error, log_loss, mae, multiclass_brier


def _outcome(row, key):
    actual = row.actual or {}
    if key in actual: return actual[key]
    if key == "home_moneyline": return actual.get("home_win")
    if key == "away_moneyline": return actual.get("away_win")
    if key == "btts_yes": return float(actual.get("home_goals", 0) > 0 and actual.get("away_goals", 0) > 0) if "home_goals" in actual else None
    if key.startswith(("over_", "under_")):
        try: line = float(key.removeprefix("over_").removeprefix("under_"))
        except ValueError: return None
        total = actual.get("total", actual.get("home_goals", 0) + actual.get("away_goals", 0)); over = float(total > line)
        return 1 - over if key.startswith("under_") else over
    if key.startswith("home_spread_"):
        try: return float(actual.get("margin", 0) + float(key.removeprefix("home_spread_")) > 0)
        except ValueError: return None
    return None


def _family(key: str, sport: str) -> str:
    if sport == "basketball":
        if "moneyline" in key: return "moneyline"
        if "spread" in key: return "spread"
        if key.startswith(("over_", "under_")): return "totals"
    if key in {"home_win", "draw", "away_win"}: return "1X2"
    if key.startswith("btts"): return "btts"
    if key.startswith(("over_", "under_")): return "totals"
    return "handicap"


def _default_markets(sport: str) -> tuple[str, ...]:
    return ("home_moneyline", "away_moneyline", "home_spread_-2.5", "home_spread_-5.5", "over_210.5", "over_220.5") if sport == "basketball" else ("home_win", "draw", "away_win", "btts_yes", "over_1_5", "over_2_5", "over_3_5")


def _family_metrics(predictions: list[dict]) -> dict:
    grouped = defaultdict(list)
    for item in predictions: grouped[item["family"]].append(item)
    result = {}
    for family, items in grouped.items():
        raw, calibrated, actual = [x["raw_probability"] for x in items], [x["calibrated_probability"] for x in items], [x["actual"] for x in items]
        result[family] = {"sample_count": len(items), "actual_frequency": sum(actual) / len(actual), "mean_probability": sum(calibrated) / len(calibrated), "raw_brier": brier_score(raw, actual), "calibrated_brier": brier_score(calibrated, actual), "raw_log_loss": log_loss(raw, actual), "calibrated_log_loss": log_loss(calibrated, actual), "calibrated_ece": expected_calibration_error(calibrated, actual), "probability_mae": mae(calibrated, actual)}
    return result


def _market_metrics(predictions: list[dict]) -> dict:
    grouped = defaultdict(list)
    for item in predictions: grouped[item["market"]].append(item)
    result = {}
    for market, items in grouped.items():
        raw, calibrated, actual = [x["raw_probability"] for x in items], [x["calibrated_probability"] for x in items], [x["actual"] for x in items]
        result[market] = {"market_family": items[0]["family"], "sample_count": len(items), "actual_frequency": sum(actual) / len(actual), "mean_probability": sum(calibrated) / len(calibrated), "raw_brier": brier_score(raw, actual), "calibrated_brier": brier_score(calibrated, actual), "raw_log_loss": log_loss(raw, actual), "calibrated_log_loss": log_loss(calibrated, actual), "calibrated_ece": expected_calibration_error(calibrated, actual)}
    return result


def walk_forward(rows, model_factory, *, markets: tuple[str, ...] | None = None, minimum_train: int = 10, validation_size: int = 5, test_size: int = 5, sport: str | None = None) -> dict:
    ordered = sorted([row for row in rows if row.actual], key=lambda row: row.data_cutoff_at); sport = sport or (ordered[0].sport if ordered else "football"); markets = markets or _default_markets(sport); predictions = []; cursor = minimum_train
    while cursor < len(ordered):
        train, validation, test = ordered[:cursor], ordered[cursor:cursor + validation_size], ordered[cursor + validation_size:cursor + validation_size + test_size]
        if not test: break
        model = model_factory().fit(train); val_preds = {key: [] for key in markets}; val_actuals = {key: [] for key in markets}
        for row in validation:
            output = model.predict(row).get("markets", {})
            for key in markets:
                outcome = _outcome(row, key)
                if key in output and outcome is not None and isinstance(output[key], (int, float)): val_preds[key].append(output[key]); val_actuals[key].append(outcome)
        calibrator = MarketCalibrator().fit(val_preds, val_actuals)
        for row in test:
            output = model.predict(row).get("markets", {}); calibrated = calibrator.transform({key: output[key] for key in markets if key in output and isinstance(output[key], (int, float))})
            for key in markets:
                outcome = _outcome(row, key)
                if key in output and outcome is not None and isinstance(output[key], (int, float)): predictions.append({"fixture_id": row.fixture_id, "market": key, "family": _family(key, sport), "raw_probability": output[key], "calibrated_probability": calibrated.get(key, output[key]), "actual": outcome, "data_cutoff_at": row.data_cutoff_at, "calibrator": calibrator.metadata().get(key)})
        cursor += test_size
    # 1X2 is also reported as a proper three-class score, separate from OVR rows.
    multiclass_rows, multiclass_actual = [], []
    for row in ordered if sport == "football" else []:
        if row.fixture_id in {x["fixture_id"] for x in predictions}:
            actual = row.actual or {}; multiclass_rows.append({"home": next((x["calibrated_probability"] for x in predictions if x["fixture_id"] == row.fixture_id and x["market"] == "home_win"), 0), "draw": next((x["calibrated_probability"] for x in predictions if x["fixture_id"] == row.fixture_id and x["market"] == "draw"), 0), "away": next((x["calibrated_probability"] for x in predictions if x["fixture_id"] == row.fixture_id and x["market"] == "away_win"), 0)}); multiclass_actual.append("home" if actual.get("home_win") else "draw" if actual.get("draw") else "away")
    return {"predictions": predictions, "metrics": {"sample_count": len(predictions), "market_families": _family_metrics(predictions), "markets": _market_metrics(predictions), "multiclass_1x2_brier": multiclass_brier(multiclass_rows, multiclass_actual) if multiclass_rows else None, "multiclass_1x2_log_loss": categorical_log_loss(multiclass_rows, multiclass_actual) if multiclass_rows else None}}
