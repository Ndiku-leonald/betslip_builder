"""Small deterministic, explicitly synthetic Stage Two pipeline smoke test."""
from datetime import datetime, timedelta, timezone
from app.features.common import FeatureRow
from app.prediction.football import FootballPoissonModel
from app.prediction.basketball import BasketballExpectedScoreModel
from app.evaluation.backtest import walk_forward


def run() -> None:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    football, basketball = [], []
    for index in range(30):
        when = start + timedelta(days=index)
        football.append(FeatureRow(str(index), "football", when, {"home_elo": 1500 + index, "away_elo": 1500, "elo_diff": 60 + index, "league_home_goals_avg": 1.3, "league_away_goals_avg": 1.0, "home_goals_for_avg_10": 1.4, "home_goals_against_avg_10": 1.0, "away_goals_for_avg_10": 1.0, "away_goals_against_avg_10": 1.2}, actual={"home_goals": float(index % 3), "away_goals": float((index + 1) % 2), "home_win": float(index % 3 > (index + 1) % 2), "draw": float(index % 3 == (index + 1) % 2), "away_win": float(index % 3 < (index + 1) % 2)}))
        basketball.append(FeatureRow(str(index), "basketball", when, {"elo_diff": 65, "home_points_for_avg_10": 108, "home_points_against_avg_10": 101, "away_points_for_avg_10": 103, "away_points_against_avg_10": 106}, actual={"home_points": float(100 + index % 12), "away_points": float(96 + index % 10), "home_win": float(index % 4 != 0), "away_win": float(index % 4 == 0), "margin": float(4 + index % 5), "total": float(196 + index % 14)}))
    football_model = FootballPoissonModel().fit(football); basketball_model = BasketballExpectedScoreModel().fit(basketball)
    football_result = walk_forward(football, FootballPoissonModel, minimum_train=10, validation_size=5, test_size=5)
    basketball_result = walk_forward(basketball, BasketballExpectedScoreModel, markets=("home_moneyline", "away_moneyline"), minimum_train=10, validation_size=5, test_size=5)
    assert football_result["metrics"]["sample_count"] > 0 and basketball_result["metrics"]["sample_count"] > 0
    assert sum(football_model.predict_distribution(football[0]).flat) > .999 and basketball_model.predict(basketball[0])["expected_total"] > 0
    print("SYNTHETIC PIPELINE PASS", football_result["metrics"]["sample_count"], basketball_result["metrics"]["sample_count"])


if __name__ == "__main__": run()
