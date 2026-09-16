from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from app.markets.compatibility import model_probability
from app.markets.consensus import ProviderConsensusService
from app.markets.value import MarketValueService, market_freshness, odds_consensus
from app.markets.storage import latest_market_snapshots, market_snapshot_history, persist_market_snapshots
from app.odds.math import expected_value, fair_decimal_odds, fair_decimal_odds_with_push, implied_probability, no_vig, overround
from app.odds.ontology import NormalizedMarket, decimal_odds, normalize_external_market
from app.odds.providers import parse_api_sports_odds, parse_the_odds_api
from app.main import _family_for_market
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
    assert fair_decimal_odds_with_push(.4, .2) == pytest.approx(2.0)
    assert expected_value(.4, 2.0, push_probability=.2) == pytest.approx(0.0)


def test_market_names_normalize_but_settlement_does_not():
    total = normalize_external_market(fixture_id="f", sport="football", provider="x", bookmaker="A", market_name="Total Goals O/U 2.5", selection_name="Over 2.5", odds=1.9, line=2.5)
    assert total.market_family == "totals" and total.selection == "over" and total.line == 2.5
    ot = normalize_external_market(fixture_id="f", sport="basketball", provider="x", bookmaker="A", market_name="Moneyline incl OT", selection_name="Home", odds=1.8)
    regulation = normalize_external_market(fixture_id="f", sport="basketball", provider="x", bookmaker="A", market_name="Regulation Moneyline", selection_name="Home", odds=1.8)
    assert ot.settlement_semantics == "including_overtime" and regulation.settlement_semantics == "regulation"


def test_documented_provider_payloads_are_normalized():
    odds_event = {"id": "event-1", "home_team": "Manchester City", "away_team": "Liverpool", "bookmakers": [{"title": "Book B", "last_update": "2026-09-16T10:00:00+00:00", "markets": [{"key": "h2h", "last_update": "2026-09-16T10:01:00+00:00", "outcomes": [{"name": "Manchester City", "price": 1.5}, {"name": "Liverpool", "price": 4.5}, {"name": "Draw", "price": 4.0}]}, {"key": "spreads", "outcomes": [{"name": "Liverpool", "price": 2.1, "point": 0.5}]}, {"key": "totals", "outcomes": [{"name": "Over", "price": 1.9, "point": 2.5}, {"name": "Under", "price": 1.9, "point": 2.5}]}]}]}
    football = parse_the_odds_api([odds_event], "internal", "football")
    assert {item.selection for item in football if item.market_family == "1x2"} == {"home", "away", "draw"}
    assert next(item for item in football if item.market_family == "handicap").participant == "away"
    assert next(item for item in football if item.market_family == "totals").line == 2.5
    basketball = parse_the_odds_api([{**odds_event, "home_team": "Los Angeles Lakers", "away_team": "Boston Celtics", "bookmakers": [{"title": "Book B", "markets": [{"key": "h2h", "outcomes": [{"name": "Los Angeles Lakers", "price": 1.5}, {"name": "Boston Celtics", "price": 2.5}]}]}]}], "internal", "basketball")
    assert {item.selection for item in basketball} == {"home", "away"} and all(item.settlement_semantics == "including_overtime" for item in basketball)


def test_realistic_api_sports_participant_market_payloads_are_normalized():
    payload = {"response": [{
        "fixture": {"id": 9001, "update": "2026-09-16T10:00:00+00:00"},
        "teams": {"home": {"name": "Manchester City"}, "away": {"name": "Liverpool"}},
        "bookmakers": [{"name": "API Book", "bets": [
            {"name": "Match Winner", "values": [
                {"value": "Manchester City", "odd": "1.50"}, {"value": "Draw", "odd": "4.00"}, {"value": "Liverpool", "odd": "5.50"}
            ]},
            {"name": "Asian Handicap", "values": [
                {"value": "Home", "handicap": "-0.5", "odd": "1.90"}, {"value": "Away", "handicap": "+0.5", "odd": "1.95"}
            ]},
            {"name": "Home Team Total Goals", "values": [{"value": "Over 1.5", "odd": "1.80"}]},
            {"name": "Away Team Total Goals", "values": [{"value": "Under 1.5", "odd": "1.85"}]},
            {"name": "Game Total Goals", "values": [{"value": "Over 2.5", "odd": "1.90"}, {"value": "Under 2.5", "odd": "1.90"}]},
        ]}],
    }]}
    markets = parse_api_sports_odds(payload, "fixture-9001", "football")
    assert {item.selection for item in markets if item.market_family == "1x2"} == {"home", "draw", "away"}
    handicaps = [item for item in markets if item.market_family == "handicap"]
    assert {(item.participant, item.selection, item.line) for item in handicaps} == {("home", "win", -.5), ("away", "win", .5)}
    assert {(item.participant, item.selection, item.line) for item in markets if item.market_family == "team_total"} == {("home", "over", 1.5), ("away", "under", 1.5)}
    assert {(item.market_family, item.selection, item.line) for item in markets if item.market_family in {"totals", "game_total"}} == {("totals", "over", 2.5), ("totals", "under", 2.5)}


def test_ambiguous_actual_team_name_is_rejected():
    with pytest.raises(ValueError, match="ambiguous team normalization"):
        parse_the_odds_api([{"id": "event-1", "home_team": "Manchester City", "away_team": "Liverpool", "bookmakers": [{"title": "Book", "markets": [{"key": "h2h", "outcomes": [{"name": "Arsenal", "price": 2.0}]}]}]}], "f", "football")


def test_latest_snapshots_dedupe_but_history_preserves_all():
    engine = __import__("sqlalchemy").create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=__import__("sqlalchemy.pool", fromlist=["StaticPool"]).StaticPool)
    from app.db import Base
    Base.metadata.create_all(engine)
    start = datetime(2026, 9, 16, 8, tzinfo=timezone.utc)
    markets = [market(observed_at=start + timedelta(minutes=index), decimal_odds=2.0 + index / 10) for index in range(3)]
    with __import__("sqlalchemy.orm", fromlist=["Session"]).Session(engine) as db:
        persist_market_snapshots(db, markets)
        current = latest_market_snapshots(db, "fixture-1")
        history = market_snapshot_history(db, "fixture-1")
    assert len(current) == 1 and current[0].decimal_odds == pytest.approx(2.2)
    assert len(history) == 3 and [item.decimal_odds for item in history] == [2.0, 2.1, 2.2]


def test_complete_market_only_uses_current_prices_for_no_vig():
    service = MarketValueService(); now = datetime.now(timezone.utc)
    old_home = market(observed_at=now - timedelta(hours=3), decimal_odds=50.0)
    current = [market(selection="home", decimal_odds=2.0, observed_at=now), market(selection="draw", decimal_odds=3.5, observed_at=now), market(selection="away", decimal_odds=4.0, observed_at=now)]
    value = service.evaluate(current[0], .6, market_group=current)
    assert value["no_vig_status"] == "complete_market" and value["overround"] == pytest.approx(overround([2.0, 3.5, 4.0]))
    assert old_home.decimal_odds not in [2.0, 3.5, 4.0]


def test_incomplete_market_never_de_vigs():
    current = [market(selection="home", decimal_odds=2.0), market(selection="away", decimal_odds=4.0)]
    value = MarketValueService().evaluate(current[0], .6, market_group=current)
    assert value["no_vig_status"] == "incomplete_market" and value["no_vig_probability"] is None and value["novig_probability_edge"] is None


@pytest.mark.parametrize("sport,family,home_line,away_line", [("football", "handicap", -.5, .5), ("basketball", "spread", -5.5, 5.5)])
def test_two_way_handicap_and_spread_markets_use_home_perspective_line(sport, family, home_line, away_line):
    now = datetime.now(timezone.utc)
    home = market(sport=sport, market_family=family, market_type=family, participant="home", selection="win", line=home_line, decimal_odds=1.9, observed_at=now)
    away = market(sport=sport, market_family=family, market_type=family, participant="away", selection="win", line=away_line, decimal_odds=2.1, observed_at=now)
    home_value = MarketValueService().evaluate(home, model_probability_structure={"win_probability": .68, "push_probability": 0, "loss_probability": .32, "calibration_status": "fitted"}, market_group=[home, away], confidence=80, data_quality=80, market_reliability=80, provider_agreement=None)
    assert home_value["no_vig_status"] == "complete_market"
    assert home_value["novig_probability_edge"] is not None


def test_mismatched_handicap_lines_do_not_form_a_market():
    home = market(market_family="handicap", market_type="handicap", participant="home", selection="win", line=-5.5)
    away = market(market_family="handicap", market_type="handicap", participant="away", selection="win", line=4.5)
    value = MarketValueService().evaluate(home, .6, market_group=[home, away])
    assert value["no_vig_status"] == "incomplete_market"


def test_whole_line_handicap_preserves_push_and_is_rankable_without_fake_agreement():
    now = datetime.now(timezone.utc)
    home = market(market_family="handicap", market_type="handicap", participant="home", selection="win", line=-1, decimal_odds=2.0, observed_at=now)
    away = market(market_family="handicap", market_type="handicap", participant="away", selection="win", line=1, decimal_odds=2.0, observed_at=now)
    service = MarketValueService()
    value = service.evaluate(home, model_probability_structure={"win_probability": .45, "push_probability": .20, "loss_probability": .35, "calibration_status": "fitted"}, market_group=[home, away], confidence=80, data_quality=80, market_reliability=80, provider_agreement=None)
    assert value["no_vig_status"] == "complete_market"
    assert value["model_resolved_win_probability"] == pytest.approx(.45 / (.45 + .35))
    assert value["model_push_probability"] == pytest.approx(.20)
    assert value["expected_value"] == pytest.approx(.45 * 1 - .35)
    assert service.rank([value], "balanced")


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


def test_football_handicap_supports_both_participants_and_pushes():
    row = FeatureRow("f", "football", datetime.now(timezone.utc), {"elo_diff": 0, "league_home_goals_avg": 1.3, "league_away_goals_avg": 1.0})
    model = FootballPoissonModel().fit([FeatureRow(str(i), "football", row.data_cutoff_at - timedelta(days=i + 1), row.values, actual={"home_goals": 1, "away_goals": 0}) for i in range(20)])
    home = model_probability(model, row, market(market_family="handicap", market_type="handicap", participant="home", selection="win", line=-0.5))
    away = model_probability(model, row, market(market_family="handicap", market_type="handicap", participant="away", selection="win", line=0.5))
    whole = model_probability(model, row, market(market_family="handicap", market_type="handicap", participant="home", selection="win", line=0.0))
    assert home["win_probability"] + away["win_probability"] == pytest.approx(1)
    assert whole["push_probability"] > 0 and whole["win_probability"] + whole["push_probability"] + whole["loss_probability"] == pytest.approx(1)


def test_team_totals_use_participant_and_selection():
    row = FeatureRow("f", "football", datetime.now(timezone.utc), {"elo_diff": 0, "league_home_goals_avg": 1.8, "league_away_goals_avg": .8})
    model = FootballPoissonModel()
    home_over = model_probability(model, row, market(market_family="team_total", market_type="team_total", participant="home", selection="over", line=1.5))
    home_higher = model_probability(model, row, market(market_family="team_total", market_type="team_total", participant="home", selection="over", line=2.5))
    away_under = model_probability(model, row, market(market_family="team_total", market_type="team_total", participant="away", selection="under", line=.5))
    assert home_over["win_probability"] > home_higher["win_probability"]
    assert 0 < away_under["win_probability"] < 1


def test_value_service_rejects_stale_and_ranks_fresh_positive_value():
    service = MarketValueService()
    stale = service.evaluate(market(observed_at=datetime.now(timezone.utc) - timedelta(hours=2)), .75, confidence=80, data_quality=90, now=datetime.now(timezone.utc), ttl_seconds=60)
    assert stale["status"] == "STALE_PRICE"
    fresh = service.evaluate(market(decimal_odds=1.5), .75, confidence=80, data_quality=90, market_group=[market(selection="home", decimal_odds=2.0), market(selection="draw", decimal_odds=3.5), market(selection="away", decimal_odds=4.0)])
    assert fresh["fair_odds"] == pytest.approx(4 / 3) and fresh["raw_probability_edge"] > 0
    assert service.rank([fresh], "balanced")[0]["ranking_score"] > 0


def test_freshness_states_are_explicit():
    now = datetime.now(timezone.utc)
    assert market_freshness(now, now=now, ttl_seconds=30)["status"] == "CURRENT"
    assert market_freshness(now - timedelta(seconds=50), now=now, ttl_seconds=30)["status"] == "AGING"
    assert market_freshness(now - timedelta(seconds=100), now=now, ttl_seconds=30)["status"] == "STALE"


def test_provider_price_timestamp_controls_freshness():
    now = datetime.now(timezone.utc)
    result = market_freshness(now - timedelta(seconds=10), provider_updated_at=now - timedelta(hours=2), now=now, ttl_seconds=60)
    assert result["fetch_age_seconds"] == 10 and result["price_age_seconds"] == 7200 and result["status"] == "STALE"


def test_odds_consensus_uses_median_compatible_current_prices():
    items = [market(bookmaker="Book A", decimal_odds=2.0), market(bookmaker="Book B", decimal_odds=2.1), market(bookmaker="Outlier", decimal_odds=8.0)]
    result = odds_consensus(items)
    assert len(result) == 1
    assert result[0]["best_current_price"] == 8.0 and result[0]["median_current_price"] == pytest.approx(2.1)
    assert result[0]["bookmaker_count"] == 3


def test_consensus_ignores_provider_specific_ids_when_canonical_teams_match():
    result = ProviderConsensusService().resolve([
        {"provider": "api-football", "home_name": "Manchester City", "away_name": "Liverpool", "home_provider_id": 42, "away_provider_id": 43},
        {"provider": "livescore-football", "home_name": "Manchester City", "away_name": "Liverpool", "home_provider_id": 9982, "away_provider_id": 9983},
    ])
    assert result["agreement"] == 1 and not result["conflicts"]


def test_single_source_consensus_is_unverified_not_perfect_agreement():
    result = ProviderConsensusService().resolve([{"provider": "api-football", "home_score": 2, "away_score": 1}])
    assert result["source_count"] == 1 and result["agreement"] is None and result["agreement_status"] == "unverified"


def test_team_total_does_not_inherit_game_total_reliability_family():
    assert _family_for_market(SimpleNamespace(market_family="team_total")) == "team_total"


def test_provider_agreement_is_a_hard_ranking_gate():
    service = MarketValueService()
    values = [service.evaluate(market(decimal_odds=1.5), .75, confidence=80, data_quality=90, market_group=[market(decimal_odds=1.5), market(selection="draw", decimal_odds=3.5), market(selection="away", decimal_odds=4.0)], provider_agreement=.7)]
    assert service.rank(values, "balanced", min_provider_agreement=.8) == []


def test_push_aware_value_exposes_resolved_probability_and_fair_price():
    current = [market(selection="over", line=2.0, decimal_odds=2.0), market(selection="under", line=2.0, decimal_odds=2.0)]
    value = MarketValueService().evaluate(current[0], model_probability_structure={"win_probability": .4, "push_probability": .2, "loss_probability": .4, "calibration_status": "fitted"}, market_group=current)
    assert value["model_win_probability"] == .4 and value["model_push_probability"] == .2 and value["model_loss_probability"] == .4
    assert value["model_resolved_win_probability"] == pytest.approx(.5) and value["fair_odds"] == pytest.approx(2.0)
