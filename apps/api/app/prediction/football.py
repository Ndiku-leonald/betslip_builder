from __future__ import annotations

import math

import numpy as np
from scipy.stats import poisson

from app.features.common import FeatureRow, mean
from app.prediction.probabilities import football_markets


class FootballPoissonModel:
    sport = "football"

    def __init__(self, score_method: str = "poisson", goal_cap: int = 10, rho: float = -0.08) -> None:
        if score_method not in {"poisson", "dixon_coles"}: raise ValueError("score_method must be poisson or dixon_coles")
        self.name = f"football_{score_method}_v1"
        self.score_method, self.goal_cap, self.rho = score_method, goal_cap, rho
        self.home_mean, self.away_mean = 1.35, 1.05

    def fit(self, rows: list[FeatureRow]) -> "FootballPoissonModel":
        actual = [row.actual for row in rows if row.actual]
        if actual:
            self.home_mean = mean([x["home_goals"] for x in actual], 1.35)
            self.away_mean = mean([x["away_goals"] for x in actual], 1.05)
        return self

    def _lambdas(self, row: FeatureRow) -> tuple[float, float]:
        v = row.values
        league_h, league_a = max(.2, v.get("league_home_goals_avg", self.home_mean)), max(.2, v.get("league_away_goals_avg", self.away_mean))
        h_attack = v.get("home_goals_for_avg_10", self.home_mean) / league_h
        a_def = v.get("away_goals_against_avg_10", self.home_mean) / league_h
        a_attack = v.get("away_goals_for_avg_10", self.away_mean) / league_a
        h_def = v.get("home_goals_against_avg_10", self.away_mean) / league_a
        elo = v.get("elo_diff", 60.0)
        return max(.05, min(5.0, self.home_mean * math.sqrt(max(.1, h_attack * a_def)) * math.exp(elo / 10000))), max(.05, min(5.0, self.away_mean * math.sqrt(max(.1, a_attack * h_def)) * math.exp(-elo / 12000)))

    def predict_distribution(self, row: FeatureRow) -> np.ndarray:
        lh, la = self._lambdas(row)
        values = np.arange(self.goal_cap + 1)
        matrix = np.outer(poisson.pmf(values, lh), poisson.pmf(values, la))
        if self.score_method == "dixon_coles":
            matrix[0, 0] *= 1 - lh * la * self.rho
            matrix[0, 1] *= 1 + la * self.rho
            matrix[1, 0] *= 1 + lh * self.rho
            matrix[1, 1] *= 1 - self.rho
        return matrix / matrix.sum()

    def predict(self, row: FeatureRow) -> dict:
        matrix = self.predict_distribution(row)
        lh, la = self._lambdas(row)
        return {"model": self.name, "expected_home_goals": lh, "expected_away_goals": la, "markets": football_markets(matrix)}

    def metadata(self) -> dict:
        return {"name": self.name, "sport": self.sport, "algorithm": "poisson" if self.score_method == "poisson" else "dixon_coles", "score_method": self.score_method, "goal_cap": self.goal_cap, "rho": self.rho, "home_mean": self.home_mean, "away_mean": self.away_mean}
