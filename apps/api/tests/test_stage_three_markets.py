from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from app.markets.compatibility import model_probability
from app.markets.consensus import ProviderConsensusService
from app.markets.value import MarketValueService, market_freshness
from app.odds.math import expected_value, fair_decimal_odds, implied_probability, no_vig, overround
from app.odds.ontology import NormalizedMarket, decimal_odds, normalize_external_market
from app.odds.providers import parse_api_sports_odds, parse_the_odds_api
from app.prediction.football import FootballPoissonModel
from app.features.common import FeatureRow


def market(**overrides):
    values = {"fixture_id": "fixture-1", "sport": "football", "provider": "bookmaker-feed", "bookmaker": "Book A", "market_family": "1x2", "market_type": "1x2", "period": "full_game", "selection": "home", "line": None, "decimal_odds": 2.0, "observed_at": datetime.now(timezone.utc)}
    values.update(overrides)
    return NormalizedMarket(**values)


def test_odds_math_and_ev():
    prices = [2.0, 3.5, 4.0]
    assert implied_probability(1.5) == pytest.approx(2 / 3)
    assert overround(prices) == pytest.approx(.035714, rel=1e-4)
    assert sum(no_vig(prices)) == pytest.approx(1)
    assert fair_decimal_odds(.75) == pytest.approx(4 / 3)
    assert expected_value(.75, 1.5) == pytest.approx(.125)
    assert decimal_odds(150, "american") == pytest.approx(2.5)
    with pytest.raises(ValueError): decimal_odds(1.0)


def test_market_names_normalize_but_settlement_does_not():
    total = normalize_external_market(fixture_id="f", sport="football", provider="x", bookmaker="A", market_name="Total Goals O/U 2.5", selection_name="Over 2.5", odds=1.9, line=2.5)
    assert total.market_family == "totals" and total.selection == "over" and total.line == 2.5
    ot = normalize_external_market(fixture_id="f", sport="basketball", provider="x", bookmaker="A", market_name="Moneyline incl OT", selection_name="Home", odds=1.8)
    regulation = normalize_external_market(fixture_id="f", sport="basketball", provider="x", bookmaker="A", market_name="Regulation Moneyline", selection_name="Home", odds=1.8)
    assert ot.settlement_semantics == "including_overtime" and regulation.settlement_semantics == "regulation"


def test_documented_provider_payloads_are_normalized():
    football = parse_api_sports_odds({"response": [{"fixture": {"id": 44}, "bookmakers": [{"name": "Book A", "bets": [{"name": "Match Winner", "values": [{"value": "Home", "odd": "2.0"}, {"value": "Draw", "odd": "3.5"}]}]}]}]}, "internal", "football")
    basketball = parse_the_odds_api([{"id": "event-1", "bookmakers": [{"title": "Book B", "markets": [{"key": "h2h", "outcomes": [{"name": "Home", "price": 1.5}]}]}]}], "internal", "basketball")
    assert football[0].market_family == "1x2" and football[0].decimal_odds == 2
    assert basketball[0].market_family == "moneyline" and basketball[0].settlement_semantics == "including_overtime"


def test_consensus_distinguishes_matching_minor_and_material_conflicts():
    service = ProviderConsensusService()
    same = service.resolve([{"provider": "api-football", "home_score": 2, "away_score": 1, "clock": "67"}, {"provider": "livescore-football", "home_score": 2, "away_score": 1, "clock": "67"}])
    minor = service.resolve([{"provider": "api-football", "home_score": 2, "away_score": 1, "clock": "67"}, {"provider": "livescore-football", "home_score": 2, "away_score": 1, "clock": "66"}])
    material = service.resolve([{"provider": "api-football", "home_score": 2, "away_score": 1}, {"provider": "livescore-football", "home_score": 1, "away_score": 1}])
    assert same["agreement"] == 1 and not same["conflicts"]
    assert minor["conflicts"][0]["severity"] == "minor"
    assert any(item["severity"] == "material" for item in material["conflicts"])


def test_dynamic_model_line_probability_is_supported():
    row = FeatureRow("f", "football", datetime.now(timezone.utc), {"elo_diff": 60, "league_home_goals_avg": 1.3, "league_away_goals_avg": 1.0})
    model = FootballPoissonModel().fit([FeatureRow(str(i), "football", row.data_cutoff_at - timedelta(days=i + 1), row.values, actual={"home_goals": 1, "away_goals": 0}) for i in range(20)])
    total = market(market_family="totals", market_type="total_goals", selection="over", line=2.5, decimal_odds=1.9)
    result = model_probability(model, row, total)
    assert result["status"] == "SUPPORTED" and 0 < result["probability"] < 1


def test_value_service_rejects_stale_and_ranks_fresh_positive_value():
    service = MarketValueService()
    stale = service.evaluate(market(observed_at=datetime.now(timezone.utc) - timedelta(hours=2)), .75, confidence=80, data_quality=90, now=datetime.now(timezone.utc), ttl_seconds=60)
    assert stale["status"] == "NO_QUALIFYING_MARKET"
    fresh = service.evaluate(market(decimal_odds=1.5), .75, confidence=80, data_quality=90, market_group=[market(selection="home", decimal_odds=2.0), market(selection="draw", decimal_odds=3.5), market(selection="away", decimal_odds=4.0)])
    assert fresh["fair_odds"] == pytest.approx(4 / 3) and fresh["raw_probability_edge"] > 0
    assert service.rank([fresh], "balanced")[0]["ranking_score"] > 0


def test_freshness_states_are_explicit():
    now = datetime.now(timezone.utc)
    assert market_freshness(now, now=now, ttl_seconds=30)["status"] == "CURRENT"
    assert market_freshness(now - timedelta(seconds=50), now=now, ttl_seconds=30)["status"] == "AGING"
    assert market_freshness(now - timedelta(seconds=100), now=now, ttl_seconds=30)["status"] == "STALE"
