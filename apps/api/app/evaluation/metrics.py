from __future__ import annotations

import math


def brier_score(predictions, outcomes) -> float: return sum((float(p) - float(y)) ** 2 for p, y in zip(predictions, outcomes)) / max(1, len(predictions))
def log_loss(predictions, outcomes) -> float: return -sum(float(y) * math.log(max(1e-12, min(1 - 1e-12, float(p)))) + (1 - float(y)) * math.log(max(1e-12, min(1 - 1e-12, 1 - float(p)))) for p, y in zip(predictions, outcomes)) / max(1, len(predictions))
def mae(predictions, outcomes) -> float: return sum(abs(float(p) - float(y)) for p, y in zip(predictions, outcomes)) / max(1, len(predictions))
def rmse(predictions, outcomes) -> float: return (sum((float(p) - float(y)) ** 2 for p, y in zip(predictions, outcomes)) / max(1, len(predictions))) ** .5
def accuracy(predictions, outcomes) -> float: return sum(int(p == y) for p, y in zip(predictions, outcomes)) / max(1, len(predictions))


def multiclass_brier(probability_rows, actual_classes) -> float:
    """Proper multiclass Brier: mean sum((p_k - 1[y=k])^2) per fixture."""
    return sum(sum((float(probability.get(label, 0.0)) - float(label == actual)) ** 2 for label in ("home", "draw", "away")) for probability, actual in zip(probability_rows, actual_classes)) / max(1, len(actual_classes))


def categorical_log_loss(probability_rows, actual_classes) -> float:
    return -sum(math.log(max(1e-12, float(probability.get(actual, 0.0)))) for probability, actual in zip(probability_rows, actual_classes)) / max(1, len(actual_classes))


def expected_calibration_error(predictions, outcomes, bins: int = 10) -> float:
    total = len(predictions); error = 0.0
    if not total: return 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        values = [(float(p), float(y)) for p, y in zip(predictions, outcomes) if low <= p < high or index == bins - 1 and p == high]
        if values: error += len(values) / total * abs(sum(x[0] for x in values) / len(values) - sum(x[1] for x in values) / len(values))
    return error


def reliability_buckets(predictions, outcomes) -> list[dict]:
    result = []
    for low, high in ((.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, 1.00001)):
        values = [(float(p), float(y)) for p, y in zip(predictions, outcomes) if low <= p < high]
        result.append({"lower": low, "upper": high, "count": len(values), "mean_predicted": sum(x[0] for x in values) / len(values) if values else None, "hit_rate": sum(x[1] for x in values) / len(values) if values else None, "difference": (sum(x[1] for x in values) / len(values) - sum(x[0] for x in values) / len(values)) if values else None})
    return result
