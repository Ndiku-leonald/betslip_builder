from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.evaluation.backtest import walk_forward
from app.features.common import FeatureRow
from app.features.football import FootballFeatureEngine
from app.historical.ingest import normalize_basketball_stats, normalize_football_stats
from app.prediction.basketball import BasketballExpectedScoreModel
from app.prediction.football import FootballPoissonModel
from app.providers.api_sports import normalize_football
from app.services.ingestion import ingest_fixtures


def football_row(index=0, home_goals=1, away_goals=0):
    return FeatureRow(str(index), "football", datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=index), {"elo_diff": 60, "league_home_goals_avg": 1.35, "league_away_goals_avg": 1.05, "home_goals_for_avg_10": 1.4, "home_goals_against_avg_10": 1.0, "away_goals_for_avg_10": 1.0, "away_goals_against_avg_10": 1.2}, {"overall": 80}, {"home_goals": home_goals, "away_goals": away_goals, "home_win": float(home_goals > away_goals), "draw": float(home_goals == away_goals), "away_win": float(home_goals < away_goals)})


def test_football_score_matrix_and_markets_are_probabilities():
    model = FootballPoissonModel().fit([football_row(i, i % 3, (i + 1) % 2) for i in range(20)])
    matrix = model.predict_distribution(football_row())
    result = model.predict(football_row())
    assert np.isclose(matrix.sum(), 1.0)
    assert np.isclose(result["markets"]["home_win"] + result["markets"]["draw"] + result["markets"]["away_win"], 1.0)
    assert np.isclose(result["markets"]["btts_yes"] + result["markets"]["btts_no"], 1.0)
    assert np.isclose(result["markets"]["over_2_5"] + result["markets"]["under_2_5"], 1.0)
    stronger = football_row(); stronger.values["elo_diff"] = 400
    assert model.predict(stronger)["expected_home_goals"] > result["expected_home_goals"]


def test_basketball_probabilities_are_monotonic_and_sum():
    rows = [FeatureRow(str(i), "basketball", datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i), {"elo_diff": 65, "home_points_for_avg_10": 108, "home_points_against_avg_10": 101, "away_points_for_avg_10": 103, "away_points_against_avg_10": 106}, actual={"home_points": 105 + i % 5, "away_points": 100 + i % 4, "home_win": float(i % 3 != 0), "away_win": float(i % 3 == 0), "margin": 5, "total": 205}) for i in range(20)]
    model = BasketballExpectedScoreModel().fit(rows); output = model.predict(rows[0]); markets = output["markets"]
    assert np.isclose(markets["home_moneyline"] + markets["away_moneyline"], 1.0)
    assert markets["home_spread_-2.5"] > markets["home_spread_-5.5"]
    assert markets["over_210.5"] > markets["over_220.5"]
    assert output["expected_total"] == output["expected_home_score"] + output["expected_away_score"]


def test_walk_forward_calibrates_after_training_cutoff_only():
    result = walk_forward([football_row(i, i % 3, (i + 1) % 2) for i in range(30)], FootballPoissonModel, minimum_train=10, validation_size=5, test_size=5)
    assert result["metrics"]["sample_count"] > 0
    assert all(item["data_cutoff_at"] < datetime(2024, 1, 31, tzinfo=timezone.utc) for item in result["predictions"])


def test_historical_statistics_are_provider_specific_and_normalized():
    football = normalize_football_stats({"response": [{"team": {"id": 1}, "statistics": [{"type": "Total Shots", "value": 12}, {"type": "expected_goals", "value": "1.4"}]}]})
    basketball = normalize_basketball_stats({"response": [{"game": {"id": 1}, "team": {"id": 1}, "field_goals": {"made": 30, "attempted": 70}, "rebounds": {"total": 40}, "turnovers": 9}]})
    assert football[0]["shots"] == 12 and football[0]["expected_goals"] == 1.4
    assert basketball[0]["field_goals_made"] == 30 and basketball[0]["total_rebounds"] == 40
    assert "statistics" not in basketball[0]


def test_feature_engine_is_strictly_pre_match_and_chronological():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}); Base.metadata.create_all(engine)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    payloads = []
    for index in range(8):
        day = (start + timedelta(days=index)).date().isoformat()
        payloads.append(normalize_football({"fixture": {"id": index + 1, "date": f"{day}T12:00:00+00:00", "status": {"short": "FT"}}, "league": {"id": 39, "name": "Synthetic", "country": "X", "season": 2024}, "teams": {"home": {"id": 1, "name": "A"}, "away": {"id": 2, "name": "B"}}, "goals": {"home": index % 3, "away": (index + 1) % 2}}))
    payloads.append(normalize_football({"fixture": {"id": 99, "date": "2024-01-12T12:00:00+00:00", "status": {"short": "NS"}}, "league": {"id": 39, "name": "Synthetic", "country": "X", "season": 2024}, "teams": {"home": {"id": 1, "name": "A"}, "away": {"id": 2, "name": "B"}}, "goals": {"home": None, "away": None}}))
    with Session(engine) as db:
        ingest_fixtures(db, payloads); rows = FootballFeatureEngine(minimum_history=2).build(db, include_unfinished=True)
    target = rows[-1]
    assert "target_home_goals" not in target.values and target.actual is None
    assert target.data_quality["history_count"] >= 2
    assert target.data_cutoff_at == datetime(2024, 1, 12, 12, tzinfo=timezone.utc)
