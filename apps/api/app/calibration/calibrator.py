from __future__ import annotations

import math

import numpy as np
from scipy.optimize import minimize


class SigmoidCalibrator:
    """Platt-style calibration fitted only on a validation set."""
    def __init__(self, minimum_samples: int = 20) -> None:
        self.minimum_samples, self.a, self.b, self.fitted = minimum_samples, 1.0, 0.0, False

    def fit(self, probabilities, outcomes) -> "SigmoidCalibrator":
        p, y = np.clip(np.asarray(probabilities, dtype=float), 1e-6, 1 - 1e-6), np.asarray(outcomes, dtype=float)
        if len(p) < self.minimum_samples or len(np.unique(y)) < 2: return self
        z = np.log(p / (1 - p))
        def objective(params):
            q = 1 / (1 + np.exp(-np.clip(params[0] * z + params[1], -40, 40)))
            return -np.mean(y * np.log(q + 1e-12) + (1 - y) * np.log(1 - q + 1e-12))
        result = minimize(objective, [1.0, 0.0], method="BFGS")
        if result.success: self.a, self.b, self.fitted = float(result.x[0]), float(result.x[1]), True
        return self

    def transform(self, probability: float) -> float:
        p = min(1 - 1e-6, max(1e-6, float(probability)))
        return float(1 / (1 + math.exp(-max(-40, min(40, self.a * math.log(p / (1 - p)) + self.b)))))

    def metadata(self) -> dict: return {"method": "sigmoid", "a": self.a, "b": self.b, "fitted": self.fitted, "minimum_samples": self.minimum_samples}


class MarketCalibrator:
    def __init__(self, minimum_samples: int = 20) -> None: self.minimum_samples, self.calibrators = minimum_samples, {}
    def fit(self, predictions: dict[str, list[float]], outcomes: dict[str, list[float]]) -> "MarketCalibrator":
        self.calibrators = {key: SigmoidCalibrator(self.minimum_samples).fit(predictions[key], outcomes[key]) for key in predictions if key in outcomes}; return self
    def transform(self, markets: dict[str, float]) -> dict[str, float]: return {key: self.calibrators[key].transform(value) if key in self.calibrators else float(max(0, min(1, value))) for key, value in markets.items()}
    def metadata(self) -> dict: return {key: value.metadata() for key, value in self.calibrators.items()}
