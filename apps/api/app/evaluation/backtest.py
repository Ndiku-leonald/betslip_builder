from __future__ import annotations

from collections import defaultdict

from app.calibration.calibrator import MarketCalibrator
from app.evaluation.baselines import evaluate_fold_baselines
from app.evaluation.metrics import brier_score, categorical_log_loss, expected_calibration_error, log_loss, mae, multiclass_brier
from app.evaluation.splits import take_group_boundary, timestamp_groups


def _football_class(row):
    actual = row.actual or {}
    return "home" if actual.get("home_win") else "draw" if actual.get("draw") else "away"


def _outcome(row, key):
    actual = row.actual or {}
    if key in actual:
        return actual[key]
    if key == "home_moneyline": return actual.get("home_win")
    if key == "away_moneyline": return actual.get("away_win")
    if key == "btts_yes": return float(actual.get("home_goals", 0) > 0 and actual.get("away_goals", 0) > 0) if "home_goals" in actual else None
    if key.startswith(("over_", "under_")):
        try: line = float(key.removeprefix("over_").removeprefix("under_").replace("_", "."))
        except ValueError: return None
        total = actual.get("total", actual.get("home_goals", 0) + actual.get("away_goals", 0)); over = float(total > line)
        return 1 - over if key.startswith("under_") else over
    if key.startswith(("home_spread_", "home_handicap_")):
        try: return float(actual.get("margin", 0) + float(key.split("_")[-1]) > 0)
        except ValueError: return None
    return None


def _scalar_probability(value):
    """Extract the binary win probability from a market representation."""
    if isinstance(value, dict):
        value = value.get("win")
    return float(value) if isinstance(value, (int, float)) else None


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
    if sport == "basketball":
        return ("home_moneyline", "away_moneyline", "home_spread_-2.5", "home_spread_-5.5", "over_210.5", "over_220.5")
    return ("home_win", "draw", "away_win", "btts_yes", "over_1_5", "over_2_5", "over_3_5", "home_handicap_-0.5", "home_handicap_+0.5")


def _family_metrics(predictions: list[dict]) -> dict:
    grouped = defaultdict(list)
    for item in predictions: grouped[item["family"]].append(item)
    result = {}
    for family, items in grouped.items():
        raw = [x["raw_probability"] for x in items]; calibrated = [x["calibrated_probability"] for x in items]; actual = [x["actual"] for x in items]
        result[family] = {"sample_count": len(items), "actual_frequency": sum(actual) / len(actual), "mean_probability": sum(calibrated) / len(calibrated), "raw_brier": brier_score(raw, actual), "calibrated_brier": brier_score(calibrated, actual), "raw_log_loss": log_loss(raw, actual), "calibrated_log_loss": log_loss(calibrated, actual), "calibrated_ece": expected_calibration_error(calibrated, actual), "probability_mae": mae(calibrated, actual)}
    return result


def _market_metrics(predictions: list[dict]) -> dict:
    grouped = defaultdict(list)
    for item in predictions: grouped[item["market"]].append(item)
    result = {}
    for market, items in grouped.items():
        raw = [x["raw_probability"] for x in items]; calibrated = [x["calibrated_probability"] for x in items]; actual = [x["actual"] for x in items]
        result[market] = {"market_family": items[0]["family"], "sample_count": len(items), "actual_frequency": sum(actual) / len(actual), "mean_probability": sum(calibrated) / len(calibrated), "raw_brier": brier_score(raw, actual), "calibrated_brier": brier_score(calibrated, actual), "raw_log_loss": log_loss(raw, actual), "calibrated_log_loss": log_loss(calibrated, actual), "calibrated_ece": expected_calibration_error(calibrated, actual)}
    return result


def _fold_metadata(train, validation, test, index):
    return {"fold": index, "training_cutoff": max((row.data_cutoff_at for row in train), default=None), "validation_start": min((row.data_cutoff_at for row in validation), default=None), "validation_end": max((row.data_cutoff_at for row in validation), default=None), "test_start": min((row.data_cutoff_at for row in test), default=None), "test_end": max((row.data_cutoff_at for row in test), default=None), "training_fixture_count": len(train), "validation_fixture_count": len(validation), "test_fixture_count": len(test), "test_fixture_ids": [row.fixture_id for row in test]}


def _compare_baselines(candidate_predictions, baseline_metrics, test_rows):
    ids = [row.fixture_id for row in test_rows]
    candidate_ids = sorted({item["fixture_id"] for item in candidate_predictions})
    if candidate_ids and candidate_ids != sorted(ids):
        raise ValueError("candidate and baseline evaluation fixture IDs differ")
    comparable = {}
    for name, metric in baseline_metrics.items():
        if "test_fixture_ids" not in metric or not candidate_ids:
            continue
        comparable[name] = {"candidate_test_fixture_ids": ids, "baseline_test_fixture_ids": metric["test_fixture_ids"], "same_test_sample_count": len(ids) == metric["sample_count"], "evaluation_start": metric.get("evaluation_start"), "evaluation_end": metric.get("evaluation_end")}
    return comparable


def walk_forward(rows, model_factory, *, markets: tuple[str, ...] | None = None, minimum_train: int = 10, validation_size: int = 5, test_size: int = 5, sport: str | None = None) -> dict:
    ordered = sorted([row for row in rows if row.actual], key=lambda row: (row.data_cutoff_at, str(row.fixture_id)))
    sport = sport or (ordered[0].sport if ordered else "football"); markets = markets or _default_markets(sport)
    groups = timestamp_groups(ordered); cursor = 0; trained = 0
    while cursor < len(groups) and trained < minimum_train:
        trained += len(groups[cursor][1]); cursor += 1
    predictions, folds, baseline_folds = [], [], []
    while cursor < len(groups):
        validation_end = take_group_boundary(groups, cursor, validation_size)
        test_end = take_group_boundary(groups, validation_end, test_size)
        if validation_end <= cursor or test_end <= validation_end: break
        flatten = lambda selected: [row for _, items in selected for row in items]
        train, validation, test = flatten(groups[:cursor]), flatten(groups[cursor:validation_end]), flatten(groups[validation_end:test_end])
        model = model_factory().fit(train); val_predictions = {key: [] for key in markets}; val_actuals = {key: [] for key in markets}
        for row in validation:
            output = model.predict(row).get("markets", {})
            for key in markets:
                outcome = _outcome(row, key); value = _scalar_probability(output.get(key))
                if value is not None and outcome is not None: val_predictions[key].append(value); val_actuals[key].append(outcome)
        calibrator = MarketCalibrator().fit(val_predictions, val_actuals)
        fold_predictions = []
        for row in test:
            output = model.predict(row).get("markets", {})
            scalar_output = {market: _scalar_probability(output.get(market)) for market in markets if _scalar_probability(output.get(market)) is not None}
            calibrated_output = calibrator.transform(scalar_output)
            for key in markets:
                outcome = _outcome(row, key); value = _scalar_probability(output.get(key))
                if value is None or outcome is None: continue
                calibrated = calibrated_output.get(key, value)
                item = {"fixture_id": row.fixture_id, "market": key, "family": _family(key, sport), "raw_probability": value, "calibrated_probability": calibrated, "actual": outcome, "data_cutoff_at": row.data_cutoff_at, "calibrator": calibrator.metadata().get(key)}
                predictions.append(item); fold_predictions.append(item)
        metadata = _fold_metadata(train, validation, test, len(folds)); folds.append({**metadata, "prediction_count": len(fold_predictions), "prediction_fixture_ids": sorted({item["fixture_id"] for item in fold_predictions})})
        baselines = evaluate_fold_baselines(train, test, sport); baseline_folds.append({"fold": len(folds) - 1, "metrics": baselines, "comparability": _compare_baselines(fold_predictions, baselines, test)})
        cursor = test_end; trained = sum(len(items) for _, items in groups[:cursor])
    multiclass_rows, multiclass_actual = [], []
    by_fixture = defaultdict(dict)
    for item in predictions:
        if item["family"] == "1X2": by_fixture[item["fixture_id"]][item["market"]] = item["calibrated_probability"]
    for row in ordered:
        values = by_fixture.get(row.fixture_id, {}); actual = _football_class(row)
        if all(key in values for key in ("home_win", "draw", "away_win")):
            multiclass_rows.append({"home": values["home_win"], "draw": values["draw"], "away": values["away_win"]}); multiclass_actual.append(actual)
    baseline_summary = {}
    for item in baseline_folds:
        for name, metric in item["metrics"].items():
            baseline_summary.setdefault(name, []).append(metric)
    return {"predictions": predictions, "folds": folds, "baseline_folds": baseline_folds, "metrics": {"sample_count": len(predictions), "market_families": _family_metrics(predictions), "markets": _market_metrics(predictions), "multiclass_1x2_brier": multiclass_brier(multiclass_rows, multiclass_actual) if multiclass_rows else None, "multiclass_1x2_log_loss": categorical_log_loss(multiclass_rows, multiclass_actual) if multiclass_rows else None, "baselines": baseline_summary}}
