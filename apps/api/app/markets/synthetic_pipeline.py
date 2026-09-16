"""Deterministic Stage Three TEST DATA pipeline; never a production benchmark."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.markets.compatibility import model_probability
from app.markets.consensus import ProviderConsensusService
from app.markets.storage import latest_market_snapshots, market_snapshot_history, persist_market_snapshots, persist_provider_observation
from app.markets.value import MarketValueService, market_group_key
from app.models import Fixture, ModelVersion, Prediction
from app.odds.ontology import NormalizedMarket
from app.prediction.football import FootballPoissonModel
from app.providers.api_sports import normalize_football
from app.odds.providers import parse_api_sports_odds
from app.providers.livescore_football import LiveScoreFootballProvider
from app.providers.matching import match_fixture
from app.services.ingestion import ingest_fixtures
from app.features.common import FeatureRow


def _fixture(provider_id: int, when: datetime, status: str, home_score=None, away_score=None):
    return normalize_football({"fixture": {"id": provider_id, "date": when.isoformat(), "status": {"short": "FT" if status == "finished" else "NS"}}, "league": {"id": 39, "name": "Synthetic TEST DATA League", "country": "Test", "season": 2026}, "teams": {"home": {"id": 1, "name": "Manchester City"}, "away": {"id": 2, "name": "Liverpool"}}, "goals": {"home": home_score, "away": away_score}})


def _market(fixture_id: str, family: str, selection: str, odds: float, when: datetime, *, participant="none", line=None, bookmaker="Synthetic Book", provider="the-odds-api"):
    market_type = "1x2" if family == "1x2" else family
    return NormalizedMarket(fixture_id=fixture_id, sport="football", bookmaker=bookmaker, provider=provider, market_family=family, market_type=market_type, period="full_game", participant=participant, selection=selection, line=line, decimal_odds=odds, observed_at=when, provider_updated_at=when, raw={"test_data": True})


class _SyntheticResponse:
    status_code = 200
    headers = {}

    def __init__(self, payload): self.payload = payload
    def json(self): return self.payload


class _SyntheticLeagueClient:
    async def get(self, url, params=None, **kwargs):
        if url.endswith("/leagues"):
            return _SyntheticResponse({"leagues": [{"slug": "eng.1", "name": "Premier League", "country": "England"}]})
        return _SyntheticResponse({"fixtures": []})


def run() -> None:
    secondary_provider = LiveScoreFootballProvider("https://synthetic.provider", client=_SyntheticLeagueClient())
    secondary_league = asyncio.run(secondary_provider.resolve_league("Premier League"))
    api_sports_regression = parse_api_sports_odds({"response": [{"fixture": {"id": 1}, "teams": {"home": {"name": "Home FC"}, "away": {"name": "Away FC"}}, "bookmakers": [{"name": "Synthetic API Book", "bets": [{"name": "Asian Handicap", "values": [{"value": "Home", "handicap": "-0.5", "odd": "1.90"}, {"value": "Away", "handicap": "+0.5", "odd": "1.90"}]}]}]}]}, "synthetic", "football")
    print("SYNTHETIC TEST DATA — NOT REAL BETTING ADVICE")
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with Session(engine) as db:
        historical = [_fixture(index, now - timedelta(days=20 - index), "finished", index % 3, (index + 1) % 2) for index in range(12)]
        upcoming = _fixture(999, now + timedelta(days=1), "scheduled")
        ingest_fixtures(db, historical + [upcoming])
        fixture = db.query(Fixture).filter(Fixture.provider_fixture_id == "999").one()
        version = ModelVersion(name="synthetic-validated", version="test-20260916", sport="football", status="champion", parameters={"home_mean": 1.5, "away_mean": 1.0, "calibration": {"home_win": {"fitted": True}}}, metrics={"market_families": {"1X2": {"sample_count": 80, "calibrated_ece": .04, "calibrated_brier": .18, "calibrated_log_loss": .55}}, "markets": {}})
        db.add(version); db.flush()
        db.add(Prediction(fixture_id=fixture.id, model_version_id=version.id, sport="football", generated_at=now, payload={"available": True, "sport": "football", "calibrated_probability": {"home_win": .62, "draw": .2, "away_win": .18, "over_2_5": .58}, "raw_probability": {"home_win": .60, "draw": .21, "away_win": .19, "over_2_5": .56}, "calibration_status_by_market": {"home_win": "fitted", "draw": "fitted", "away_win": "fitted", "over_2_5": "fitted"}, "model_confidence_score": 78, "data_quality": {"overall": 82}}))
        db.commit()
        current = now
        prices = [_market(fixture.id, "1x2", "home", 1.8, current), _market(fixture.id, "1x2", "draw", 4.1, current), _market(fixture.id, "1x2", "away", 4.8, current)]
        old_home = _market(fixture.id, "1x2", "home", 9.0, current - timedelta(hours=4))
        incomplete = [_market(fixture.id, "1x2", "home", 1.8, current, bookmaker="Incomplete Book"), _market(fixture.id, "1x2", "away", 5.0, current, bookmaker="Incomplete Book")]
        whole_total = [_market(fixture.id, "totals", "over", 2.1, current, line=2.0), _market(fixture.id, "totals", "under", 1.8, current, line=2.0)]
        football_handicap = [_market(fixture.id, "handicap", "win", 1.85, current, participant="home", line=-.5), _market(fixture.id, "handicap", "win", 2.05, current, participant="away", line=.5)]
        basketball_spread = [_market(fixture.id, "spread", "win", 1.9, current, participant="home", line=-5.5, provider="api-sports-odds"), _market(fixture.id, "spread", "win", 2.1, current, participant="away", line=5.5, provider="api-sports-odds")]
        team_total = _market(fixture.id, "team_total", "over", 1.9, current, participant="home", line=1.5)
        persist_market_snapshots(db, prices + [old_home] + incomplete + whole_total + football_handicap + basketball_spread + [team_total])
        latest = latest_market_snapshots(db, fixture.id); history = market_snapshot_history(db, fixture.id)
        groups = {}
        for item in latest: groups.setdefault(market_group_key(item), []).append(item)
        service = MarketValueService(); values = []
        for item in latest:
            group = groups[market_group_key(item)]
            if item.market_family in {"handicap", "spread"}:
                win = .64 if item.participant == "home" else .36
                structure = {"win_probability": win, "push_probability": 0, "loss_probability": 1 - win, "calibration_status": "fitted"}
            elif item.market_family == "totals" and item.line == 2.0:
                structure = {"win_probability": .45, "push_probability": .2, "loss_probability": .35, "calibration_status": "fitted"}
            else:
                win = .62 if item.selection == "home" else .2 if item.selection == "draw" else .18
                structure = {"win_probability": win, "push_probability": 0, "loss_probability": 1 - win, "calibration_status": "fitted"}
            values.append(service.evaluate(item, model_probability_structure=structure, market_group=group, confidence=78, data_quality=82, market_reliability=80, source_reliability=75, provider_agreement=None))
        observations = [{"provider": "api-football", "home_name": "Manchester City", "away_name": "Liverpool", "home_score": 2, "away_score": 1, "status": "live", "clock": "67", "kickoff_at": current}, {"provider": "livescore-football", "home_name": "Manchester City", "away_name": "Liverpool", "home_score": 1, "away_score": 1, "status": "live", "clock": "67", "kickoff_at": current}]
        persist_provider_observation(db, fixture.id, observations[1], canonical_home_team="Manchester City", canonical_away_team="Liverpool")
        consensus = ProviderConsensusService().resolve(observations, primary_source="api-football", fixture_id=fixture.id, db=db)
        single_source = ProviderConsensusService().resolve([observations[0]], primary_source="api-football", fixture_id=fixture.id)
        row = FeatureRow("dynamic", "football", current, {"elo_diff": 0, "league_home_goals_avg": 1.4, "league_away_goals_avg": 1.0})
        model = FootballPoissonModel().fit([FeatureRow(str(index), "football", current - timedelta(days=index + 1), row.values, actual={"home_goals": 1, "away_goals": 0}) for index in range(20)])
        dynamic = model_probability(model, row, _market(fixture.id, "handicap", "win", 2.0, current, participant="away", line=.5))
        ranked = service.rank(values, "aggressive")
        print({"secondary_league": secondary_league, "api_sports_handicap": [(item.participant, item.line) for item in api_sports_regression], "football_handicap_no_vig": next(item for item in values if item["market_family"] == "handicap")["no_vig_status"], "basketball_spread_no_vig": next(item for item in values if item["market_family"] == "spread")["no_vig_status"], "single_source_agreement": single_source["agreement"], "single_source_agreement_status": single_source["agreement_status"], "ranked_handicap": any(item["market_family"] in {"handicap", "spread"} for item in ranked)})
        print({"fixtures": 13, "current_snapshots": len(latest), "history_snapshots": len(history), "old_quote_excluded": len(latest) < len(history), "incomplete_no_vig": next(item for item in values if item["bookmaker"] == "Incomplete Book")["no_vig_status"], "whole_line_push": next(item for item in values if item["market_family"] == "totals")["model_push_probability"], "away_handicap": dynamic, "provider_conflict": consensus["material_conflict"], "ranked_candidates": len(ranked), "matched_ids_are_not_compared": match_fixture({"home": "Manchester City", "away": "Liverpool", "kickoff_at": current}, [{"home": "Manchester City", "away": "Liverpool", "kickoff_at": current}])["status"] == "matched"})


if __name__ == "__main__": run()
