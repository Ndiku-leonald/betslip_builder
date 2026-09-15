from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.evaluation.backtest import walk_forward
from app.evaluation.baselines import evaluate_baselines
from app.calibration.calibrator import MarketCalibrator, SigmoidCalibrator
from app.features.common import FeatureRow
from app.features.football import FootballFeatureEngine
from app.features.basketball import BasketballFeatureEngine
from app.features.quality import quality_score
from app.historical.ingest import normalize_basketball_stats, normalize_football_stats
from app.models import Fixture, ModelVersion
from app.prediction.basketball import BasketballExpectedScoreModel
from app.prediction.football import FootballPoissonModel
from app.prediction.service import PredictionService, PredictionUnavailable
from app.providers.api_sports import normalize_football
from app.providers.api_sports import ApiSportsProvider, ProviderError
from app.cache import MemoryCache
from app.quota import QuotaManager
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


def test_basketball_elo_constructor_and_update_use_k_18_not_home_advantage():
    engine = BasketballFeatureEngine(); assert engine.elo_k == 18.0; assert engine.home_advantage == 65.0
    home, away = engine.update_ratings(1500, 1500, 110, 90)
    assert 10 < home - 1500 < 45 and away < 1500


def test_basketball_percentage_features_and_realistic_possessions():
    engine = BasketballFeatureEngine()
    percentage_stat = SimpleNamespace(field_goals_made=30, field_goals_attempted=60, three_pointers_made=9, three_pointers_attempted=30, free_throws_made=18, free_throws_attempted=20, offensive_rebounds=10, turnovers=12, points=87, total_rebounds=40, assists=20)
    history = [{"kickoff": datetime(2024, 1, 1, tzinfo=timezone.utc), "pf": 100, "pa": 95, "margin": 5, "stats": percentage_stat}]
    values = engine._values(history, history, 1500, 1500, datetime(2024, 1, 3, tzinfo=timezone.utc))
    assert values["home_fg_pct_avg_5"] == .5 and values["home_three_pct_avg_5"] == .3 and values["home_ft_pct_avg_5"] == .9
    assert values["home_field_goals_made_avg_5"] == 30
    pace_stat = SimpleNamespace(field_goals_made=39, field_goals_attempted=78, three_pointers_made=12, three_pointers_attempted=32, free_throws_made=18, free_throws_attempted=24, offensive_rebounds=10, turnovers=12, points=108, total_rebounds=40, assists=20)
    pace_history = [{**history[0], "stats": pace_stat}]
    pace_values = engine._values(pace_history, pace_history, 1500, 1500, datetime(2024, 1, 3, tzinfo=timezone.utc))
    assert 85 <= pace_values["home_estimated_pace_avg_5"] <= 110
    assert 85 <= pace_values["estimated_game_pace_avg_5"] <= 110


def test_competition_coverage_is_not_team_history_coverage():
    empty = quality_score(history_count=5, minimum_history=5, stats_fraction=1, competition_seen=False, competition_sample=0)
    covered = quality_score(history_count=5, minimum_history=5, stats_fraction=1, competition_seen=True, competition_sample=8)
    assert empty["competition_coverage"] < covered["competition_coverage"] and empty["competition_sample"] == 0


def test_same_kickoff_results_cannot_change_sibling_features():
    def payload(fixture_id, home_id, away_id, home_score):
        return normalize_football({"fixture": {"id": fixture_id, "date": "2024-01-05T12:00:00+00:00", "status": {"short": "FT"}}, "league": {"id": 39, "name": "Batch", "country": "X", "season": 2024}, "teams": {"home": {"id": home_id, "name": f"H{home_id}"}, "away": {"id": away_id, "name": f"A{away_id}"}}, "goals": {"home": home_score, "away": 0}})
    def build(a_score):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}); Base.metadata.create_all(engine)
        with Session(engine) as db:
            ingest_fixtures(db, [payload(1, 1, 2, a_score), payload(2, 3, 4, 0)])
            return FootballFeatureEngine().build(db)
    first, second = build(0), build(7)
    assert first[1].values == second[1].values


def test_calibrated_mutually_exclusive_and_complementary_markets_remain_coherent():
    calibrator = MarketCalibrator(); calibrator.calibrators = {key: SigmoidCalibrator() for key in ("home_win", "draw", "away_win", "btts_yes", "btts_no", "over_2_5", "under_2_5", "home_moneyline", "away_moneyline")}
    output = calibrator.transform({"home_win": .6, "draw": .2, "away_win": .2, "btts_yes": .4, "btts_no": .6, "over_2_5": .55, "under_2_5": .45, "home_moneyline": .7, "away_moneyline": .3})
    assert np.isclose(output["home_win"] + output["draw"] + output["away_win"], 1)
    assert np.isclose(output["home_moneyline"] + output["away_moneyline"], 1)
    assert np.isclose(output["btts_yes"] + output["btts_no"], 1)
    assert np.isclose(output["over_2_5"] + output["under_2_5"], 1)


def test_prediction_service_rejects_live_stage_two_fixture():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}); Base.metadata.create_all(engine)
    live = normalize_football({"fixture": {"id": 700, "date": "2024-01-05T12:00:00+00:00", "status": {"short": "2H"}}, "league": {"id": 39, "name": "Live", "country": "X", "season": 2024}, "teams": {"home": {"id": 1, "name": "A"}, "away": {"id": 2, "name": "B"}}, "goals": {"home": 1, "away": 0}})
    with Session(engine) as db:
        ingest_fixtures(db, [live]); fixture_id = db.scalar(select(Fixture.id))
        try: PredictionService().generate(db, fixture_id)
        except PredictionUnavailable as exc: assert "Live analysis" in str(exc)
        else: raise AssertionError("live fixtures must not receive a Stage Two pre-match prediction")


def test_production_prediction_service_exposes_persisted_calibration():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}); Base.metadata.create_all(engine)
    def payload(fixture_id, day, status, home_score, away_score):
        return normalize_football({"fixture": {"id": fixture_id, "date": f"2024-01-{day:02d}T12:00:00+00:00", "status": {"short": status}}, "league": {"id": 39, "name": "Calibrated", "country": "X", "season": 2024}, "teams": {"home": {"id": 1, "name": "A"}, "away": {"id": 2, "name": "B"}}, "goals": {"home": home_score, "away": away_score}})
    with Session(engine) as db:
        ingest_fixtures(db, [payload(index, index, "FT", 1 if index % 2 else 0, 0 if index % 2 else 1) for index in range(1, 6)] + [payload(99, 20, "NS", None, None)])
        calibration = MarketCalibrator().fit({"home_win": [.6] * 20, "draw": [.2] * 20, "away_win": [.2] * 20}, {"home_win": [i % 2 for i in range(20)], "draw": [i % 2 for i in range(20)], "away_win": [1 - i % 2 for i in range(20)]})
        model = FootballPoissonModel().fit([football_row(i, i % 3, (i + 1) % 2) for i in range(20)])
        db.add(ModelVersion(name=model.name, version="calibrated-test", sport="football", status="champion", parameters={**model.metadata(), "calibration": calibration.metadata()})); db.commit()
        target_id = db.scalar(select(Fixture.id).where(Fixture.provider_fixture_id == "99")); result = PredictionService().generate(db, target_id)
    assert result["calibration_status"] == "fitted" and "raw_probability" in result and "calibrated_probability" in result
    assert np.isclose(result["markets"]["home_win"] + result["markets"]["draw"] + result["markets"]["away_win"], 1)


def test_baseline_comparison_is_persistable_and_explicit():
    result = evaluate_baselines([football_row(i, 1 if i % 2 else 0, 0 if i % 2 else 1) for i in range(12)], "football")
    assert "league_frequency_1x2" in result and "simple_elo_1x2" in result and "league_average_poisson" in result


def test_historical_request_budget_caps_actual_retry_attempts(monkeypatch):
    import app.providers.api_sports as module
    class Response:
        status_code = 500; headers = {}
        def json(self): return {"response": []}
    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def get(self, *args, **kwargs): return Response()
    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    provider = ApiSportsProvider(name="api-football", key="test-key", base_url="https://example.test", cache=MemoryCache(), quota=QuotaManager(mode="standard")); provider.request_budget = 2
    try: __import__("asyncio").run(provider._request("fixtures"))
    except ProviderError: pass
    assert sum(event["external_request"] for event in provider.last_request_events) == 2


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
