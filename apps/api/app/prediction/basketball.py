from __future__ import annotations

import math

from scipy.stats import norm

from app.features.common import FeatureRow, mean


class BasketballExpectedScoreModel:
    sport = "basketball"

    def __init__(self) -> None:
        self.name = "basketball_expected_score_v1"
        self.home_mean, self.away_mean, self.margin_sd, self.total_sd = 105.0, 102.0, 12.0, 18.0

    def fit(self, rows: list[FeatureRow]) -> "BasketballExpectedScoreModel":
        actual = [x.actual for x in rows if x.actual]
        if actual:
            self.home_mean = mean([x["home_points"] for x in actual], 105)
            self.away_mean = mean([x["away_points"] for x in actual], 102)
            margins = [x["margin"] for x in actual]; totals = [x["total"] for x in actual]
            self.margin_sd = max(4.0, (sum((x - mean(margins)) ** 2 for x in margins) / max(1, len(margins))) ** .5)
            self.total_sd = max(6.0, (sum((x - mean(totals)) ** 2 for x in totals) / max(1, len(totals))) ** .5)
        return self

    def _scores(self, row: FeatureRow) -> tuple[float, float]:
        v = row.values
        h_for, h_against = v.get("home_points_for_avg_10", self.home_mean), v.get("home_points_against_avg_10", self.away_mean)
        a_for, a_against = v.get("away_points_for_avg_10", self.away_mean), v.get("away_points_against_avg_10", self.home_mean)
        elo = v.get("elo_diff", 65.0)
        home = max(40.0, min(180.0, .35 * self.home_mean + .325 * h_for + .325 * a_against + elo * .025))
        away = max(40.0, min(180.0, .35 * self.away_mean + .325 * a_for + .325 * h_against - elo * .0125))
        return home, away

    def predict(self, row: FeatureRow) -> dict:
        home, away = self._scores(row); margin, total = home - away, home + away
        markets = {"home_moneyline": float(norm.cdf(margin / self.margin_sd)), "away_moneyline": float(norm.cdf(-margin / self.margin_sd))}
        for line in (-5.5, -2.5, 2.5, 5.5): markets[f"home_spread_{line:+g}"] = float(norm.cdf((margin + line) / self.margin_sd))
        for line in (200.5, 210.5, 220.5, 230.5, 240.5):
            markets[f"over_{line:g}"] = float(norm.cdf((total - line) / self.total_sd)); markets[f"under_{line:g}"] = 1 - markets[f"over_{line:g}"]
        for line in (95.5, 100.5, 105.5, 110.5):
            markets[f"home_over_{line:g}"] = float(norm.cdf((home - line) / (self.total_sd / 2))); markets[f"away_over_{line:g}"] = float(norm.cdf((away - line) / (self.total_sd / 2)))
        return {"model": self.name, "expected_home_score": home, "expected_away_score": away, "expected_margin": margin, "expected_total": total, "variance": {"margin_sd": self.margin_sd, "total_sd": self.total_sd}, "markets": markets}

    def metadata(self) -> dict:
        return {"name": self.name, "sport": self.sport, "algorithm": "normal_expected_score", "home_mean": self.home_mean, "away_mean": self.away_mean, "margin_sd": self.margin_sd, "total_sd": self.total_sd}
