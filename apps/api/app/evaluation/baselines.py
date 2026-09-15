"""Leakage-safe, fold-local baselines used for model comparisons."""
from __future__ import annotations

from collections import Counter

import numpy as np
from scipy.stats import poisson

from app.evaluation.metrics import brier_score, categorical_log_loss, log_loss, mae, multiclass_brier, rmse
from app.prediction.probabilities import football_markets


def _football_class(row):
    actual = row.actual or {}
    return "home" if actual.get("home_win") else "draw" if actual.get("draw") else "away"


def _poisson_markets(home_mean: float, away_mean: float, goal_cap: int = 10) -> dict:
    goals = np.arange(goal_cap + 1)
    matrix = np.outer(poisson.pmf(goals, max(0.05, home_mean)), poisson.pmf(goals, max(0.05, away_mean)))
    return football_markets(matrix / matrix.sum())


def _metric_for_class(probabilities, rows):
    actual = [_football_class(row) for row in rows]
    return {
        "sample_count": len(rows),
        "test_fixture_ids": [row.fixture_id for row in rows],
        "multiclass_brier": multiclass_brier(probabilities, actual),
        "categorical_log_loss": categorical_log_loss(probabilities, actual),
    }


def evaluate_fold_baselines(train_rows, test_rows, sport: str) -> dict:
    """Fit baselines on ``train_rows`` and score them only on ``test_rows``."""
    train = [row for row in train_rows if row.actual]
    test = [row for row in test_rows if row.actual]
    if not train or not test:
        return {}
    if sport == "football":
        counts = Counter(_football_class(row) for row in train)
        total = len(train)
        frequency = {key: counts[key] / total for key in ("home", "draw", "away")}
        frequency_rows = [frequency.copy() for _ in test]
        elo_rows = []
        for row in test:
            home = 1 / (1 + 10 ** (-float(row.values.get("elo_diff", 0)) / 400))
            draw = 0.20
            away = 1 - home
            denominator = home + draw + away
            elo_rows.append({"home": home / denominator, "draw": draw / denominator, "away": away / denominator})
        home_mean = sum(row.actual["home_goals"] for row in train) / len(train)
        away_mean = sum(row.actual["away_goals"] for row in train) / len(train)
        poisson_rows = [{"home": _poisson_markets(home_mean, away_mean)["home_win"], "draw": _poisson_markets(home_mean, away_mean)["draw"], "away": _poisson_markets(home_mean, away_mean)["away_win"]} for _ in test]
        poisson_template = poisson_rows[0]
        result = {
            "league_frequency_1x2": {**_metric_for_class(frequency_rows, test), "probabilities": frequency, "fit_fixture_ids": [row.fixture_id for row in train]},
            "simple_elo_1x2": {**_metric_for_class(elo_rows, test), "fit_fixture_ids": [row.fixture_id for row in train]},
            "league_average_poisson": {**_metric_for_class(poisson_rows, test), "fit_fixture_ids": [row.fixture_id for row in train], "home_mean": home_mean, "away_mean": away_mean, "probabilities": poisson_template},
        }
        for name, market_rows in (("league_frequency_1x2", frequency_rows), ("simple_elo_1x2", elo_rows), ("league_average_poisson", poisson_rows)):
            result[name]["evaluation_start"] = min(row.data_cutoff_at for row in test)
            result[name]["evaluation_end"] = max(row.data_cutoff_at for row in test)
        return result

    outcomes = [float(row.actual.get("home_win", 0)) for row in test]
    home_rate = sum(float(row.actual.get("home_win", 0)) for row in train) / len(train)
    home_rate_rows = [{"home": home_rate, "away": 1 - home_rate} for _ in test]
    elo_rows = []
    for row in test:
        home = 1 / (1 + 10 ** (-float(row.values.get("elo_diff", 0)) / 400))
        elo_rows.append({"home": home, "away": 1 - home})
    home_mean = sum(row.actual["home_points"] for row in train) / len(train)
    away_mean = sum(row.actual["away_points"] for row in train) / len(train)
    result = {
        "home_win_frequency": {"sample_count": len(test), "test_fixture_ids": [row.fixture_id for row in test], "fit_fixture_ids": [row.fixture_id for row in train], "brier": brier_score([home_rate] * len(test), outcomes), "log_loss": log_loss([home_rate] * len(test), outcomes), "mean_probability": home_rate},
        "simple_elo_moneyline": {"sample_count": len(test), "test_fixture_ids": [row.fixture_id for row in test], "fit_fixture_ids": [row.fixture_id for row in train], "brier": brier_score([item["home"] for item in elo_rows], outcomes), "log_loss": log_loss([item["home"] for item in elo_rows], outcomes), "mean_probability": sum(item["home"] for item in elo_rows) / len(elo_rows)},
        "league_average_score": {"sample_count": len(test), "test_fixture_ids": [row.fixture_id for row in test], "fit_fixture_ids": [row.fixture_id for row in train], "home_score": home_mean, "away_score": away_mean, "home_mae": mae([home_mean] * len(test), [row.actual["home_points"] for row in test]), "away_mae": mae([away_mean] * len(test), [row.actual["away_points"] for row in test]), "home_rmse": rmse([home_mean] * len(test), [row.actual["home_points"] for row in test]), "away_rmse": rmse([away_mean] * len(test), [row.actual["away_points"] for row in test])},
    }
    for item in result.values():
        item["evaluation_start"] = min(row.data_cutoff_at for row in test)
        item["evaluation_end"] = max(row.data_cutoff_at for row in test)
    return result


def evaluate_baselines(rows, sport: str) -> dict:
    """Backward-compatible convenience wrapper; uses a chronological holdout."""
    ordered = sorted([row for row in rows if row.actual], key=lambda row: row.data_cutoff_at)
    midpoint = max(1, int(len(ordered) * 0.6))
    return evaluate_fold_baselines(ordered[:midpoint], ordered[midpoint:], sport)
