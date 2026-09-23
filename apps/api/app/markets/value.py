from __future__ import annotations

from datetime import datetime, timezone
from statistics import median

from app.odds.math import expected_value, fair_decimal_odds_with_push, implied_probability, no_vig, overround


def odds_consensus(markets) -> list[dict]:
    """Summarize compatible current prices across bookmakers.

    The caller must provide latest observations. Context fields stay in the
    grouping key so lines, periods, settlement rules, and market families are
    never averaged together. Median pricing prevents one outlier book from
    defining the consensus.
    """
    groups = {}
    for market in markets:
        if market.status != "open" or market.decimal_odds is None or market.decimal_odds <= 1:
            continue
        key = (market.provider, market.fixture_id, market.market_family,
               market.market_type, market.period, market.participant,
               market.selection, market.line, market.settlement_semantics)
        groups.setdefault(key, []).append(market)
    result = []
    for key, items in groups.items():
        prices = [float(item.decimal_odds) for item in items]
        result.append({
            "provider": key[0], "fixture_id": key[1],
            "market_family": key[2], "market_type": key[3],
            "period": key[4], "participant": key[5], "selection": key[6],
            "line": key[7], "settlement_semantics": key[8],
            "bookmaker_count": len(items),
            "best_current_price": max(prices),
            "median_current_price": median(prices),
            "median_raw_implied_probability": median(1 / price for price in prices),
            "bookmakers": sorted({item.bookmaker for item in items}),
        })
    return result


def market_freshness(observed_at, *, provider_updated_at=None, now=None, ttl_seconds: int = 1800) -> dict:
    """Report fetch age separately from source-reported price age."""
    now = now or datetime.now(timezone.utc)

    def age(timestamp):
        if timestamp is None: return None
        timestamp = timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp.astimezone(timezone.utc)
        return max(0, int((now - timestamp).total_seconds()))

    fetch_age = age(observed_at)
    price_age = age(provider_updated_at) if provider_updated_at is not None else fetch_age
    if price_age is None: status = "STALE"
    elif price_age <= ttl_seconds: status = "CURRENT"
    elif price_age <= ttl_seconds * 2: status = "AGING"
    else: status = "STALE"
    return {"status": status, "age_seconds": price_age, "fetch_age_seconds": fetch_age, "price_age_seconds": price_age, "timestamp_source": "provider_updated_at" if provider_updated_at is not None else "observed_at"}


def _outcome_contract(market):
    if market.market_family == "1x2": return {"home", "draw", "away"}
    if market.market_family == "draw_no_bet": return {"home", "away"}
    if market.market_family == "double_chance": return {"home_draw", "draw_away", "home_away"}
    if market.market_family == "moneyline": return {"home", "away"}
    if market.market_family == "btts": return {"yes", "no"}
    if market.market_family in {"totals", "game_total", "team_total"}: return {"over", "under"}
    return None


def handicap_home_line(market) -> float | None:
    """Return a handicap/spread line from the home team's perspective."""
    if market.market_family not in {"handicap", "spread"} or market.line is None or market.participant not in {"home", "away"}:
        return None
    return float(market.line) if market.participant == "home" else -float(market.line)


def market_group_key(market):
    """Preserve market context while joining the two sides of a line market."""
    line = handicap_home_line(market) if market.market_family in {"handicap", "spread"} else market.line
    participant = None if market.market_family in {"handicap", "spread"} else market.participant
    return (market.provider, market.fixture_id, market.bookmaker, market.market_family, market.market_type, market.period, market.settlement_semantics, participant, line)


def _compatible_market_group(market, group) -> tuple[bool, str]:
    contract = _outcome_contract(market)
    if contract is None and market.market_family not in {"handicap", "spread"}: return False, "not_applicable"
    if not group: return False, "incomplete_market"
    comparable = [item for item in group if getattr(item, "status", getattr(item, "market_status", "open")) == "open" and item.decimal_odds is not None]
    if market.market_family in {"handicap", "spread"}:
        context = (market.provider, market.fixture_id, market.bookmaker, market.market_family, market.market_type, market.period, market.settlement_semantics)
        if not all((item.provider, item.fixture_id, item.bookmaker, item.market_family, item.market_type, item.period, item.settlement_semantics) == context for item in comparable): return False, "incomplete_market"
        participants = {item.participant for item in comparable}
        lines = {round(handicap_home_line(item), 8) for item in comparable}
        complete = participants == {"home", "away"} and lines == {round(handicap_home_line(market), 8)} and all(item.selection == "win" for item in comparable)
        return complete, "complete_market" if complete else "incomplete_market"
    context = (market.provider, market.fixture_id, market.bookmaker, market.market_family, market.market_type, market.period, market.participant, market.line, market.settlement_semantics)
    if not all((item.provider, item.fixture_id, item.bookmaker, item.market_family, item.market_type, item.period, item.participant, item.line, item.settlement_semantics) == context for item in comparable): return False, "incomplete_market"
    return ({item.selection for item in comparable} == contract), "complete_market" if {item.selection for item in comparable} == contract else "incomplete_market"


class MarketValueService:
    profiles = {
        "conservative": {"probability": .60, "confidence": 65, "data_quality": 70, "edge": .02, "market_reliability": 65, "calibration": {"fitted"}},
        "balanced": {"probability": .53, "confidence": 50, "data_quality": 50, "edge": .01, "market_reliability": 45, "calibration": {"fitted", "family_fitted"}},
        "aggressive": {"probability": .45, "confidence": 35, "data_quality": 35, "edge": .03, "market_reliability": 25, "calibration": {"fitted", "family_fitted", "raw_dynamic_line"}},
    }

    def evaluate(self, market, model_probability_value: float | None = None, *, model_probability_structure: dict | None = None, model_version=None, confidence: float = 0, data_quality: float = 0, market_reliability: float | None = 50, market_reliability_components: dict | None = None, source_reliability: float | None = 50, source_reliability_components: dict | None = None, provider_agreement: float | None = 1.0, material_conflict: bool = False, calibration_status: str = "fitted", market_group=None, now=None, ttl_seconds: int = 1800) -> dict:
        market_status = getattr(market, "status", getattr(market, "market_status", "open"))
        structure = model_probability_structure or {"win_probability": model_probability_value, "push_probability": 0.0, "loss_probability": (1 - model_probability_value) if model_probability_value is not None else None, "calibration_status": calibration_status}
        win = structure.get("win_probability"); push = structure.get("push_probability", 0.0) or 0.0; loss = structure.get("loss_probability")
        resolved = win / (win + loss) if win is not None and loss is not None and win + loss > 0 else None
        freshness = market_freshness(market.observed_at, provider_updated_at=market.provider_updated_at, now=now, ttl_seconds=ttl_seconds)
        status = "CURRENT" if freshness["status"] != "STALE" and market_status == "open" else "STALE_PRICE" if freshness["status"] == "STALE" else "UNSUPPORTED"
        if structure.get("status") and structure["status"] != "SUPPORTED": status = structure["status"]
        complete, no_vig_status = _compatible_market_group(market, market_group)
        if status == "CURRENT" and not complete and no_vig_status == "incomplete_market": status = "INCOMPLETE_MARKET"
        if status == "CURRENT" and structure.get("calibration_status", calibration_status) in {"insufficient_calibration", "insufficient_model"}: status = "INSUFFICIENT_CALIBRATION"
        result = {
            "fixture_id": market.fixture_id, "sport": getattr(market, "sport", "football"), "bookmaker": market.bookmaker, "provider": market.provider,
            "market_family": market.market_family, "market_type": market.market_type, "period": getattr(market, "period", "full_game"), "participant": market.participant, "selection": market.selection, "line": market.line,
            "settlement_semantics": getattr(market, "settlement_semantics", "full_game"), "is_live": bool(getattr(market, "is_live", False)),
            "bookmaker_odds": market.decimal_odds, "model_probability": win, "model_win_probability": win, "model_push_probability": push, "model_loss_probability": loss,
            "model_resolved_win_probability": resolved, "fair_odds": None, "raw_implied_probability": None, "no_vig_probability": None,
            "no_vig_status": no_vig_status, "overround": None, "raw_probability_edge": None, "novig_probability_edge": None, "expected_value": None, "market_status": market_status,
            "confidence": confidence, "data_quality": data_quality, "market_reliability": market_reliability, "market_reliability_components": market_reliability_components or {},
            "source_reliability": source_reliability, "source_reliability_components": source_reliability_components or {}, "provider_agreement": provider_agreement,
            "material_provider_conflict": material_conflict, "calibration_status": structure.get("calibration_status", calibration_status), "freshness": freshness, "status": status,
        }
        if market.decimal_odds is None or win is None or loss is None: return result
        result["fair_odds"] = fair_decimal_odds_with_push(win, push, loss) if win > 0 else None
        raw = implied_probability(market.decimal_odds); result["raw_implied_probability"] = raw
        if complete:
            current = [item for item in market_group if getattr(item, "status", getattr(item, "market_status", "open")) == "open" and item.decimal_odds is not None]
            prices = [item.decimal_odds for item in current]; result["overround"] = overround(prices); probs = no_vig(prices)
            selected_index = next((index for index, item in enumerate(current) if item is market or (item.selection == market.selection and item.participant == market.participant)), None)
            if selected_index is not None: result["no_vig_probability"] = probs[selected_index]
        result["raw_probability_edge"] = (resolved if resolved is not None else win) - raw
        if result["no_vig_probability"] is not None: result["novig_probability_edge"] = (resolved if resolved is not None else win) - result["no_vig_probability"]
        result["expected_value"] = expected_value(win, market.decimal_odds, push_probability=push, loss_probability=loss)
        return result

    def rank(self, values: list[dict], profile: str = "balanced", *, min_provider_agreement: float = 0.8) -> list[dict]:
        thresholds = self.profiles.get(profile, self.profiles["balanced"]); result = []
        for item in values:
            if item.get("status") != "CURRENT" or item.get("compatibility") not in {None, "SUPPORTED"}: continue
            if item.get("freshness", {}).get("status") == "STALE" or item.get("no_vig_status") == "incomplete_market": continue
            if item.get("material_provider_conflict") or (item.get("provider_agreement") is not None and item["provider_agreement"] < min_provider_agreement): continue
            if item.get("calibration_status", "insufficient_calibration") not in thresholds["calibration"]: continue
            if item.get("market_reliability") is None or item.get("market_reliability", 0) < thresholds["market_reliability"]: continue
            ranking_probability = item.get("model_resolved_win_probability") if item.get("model_resolved_win_probability") is not None else item.get("model_win_probability", item.get("model_probability", 0))
            if ranking_probability < thresholds["probability"] or item.get("confidence", 0) < thresholds["confidence"] or item.get("data_quality", 0) < thresholds["data_quality"]: continue
            edge = item.get("novig_probability_edge")
            if edge is None or edge < thresholds["edge"]: continue
            item = dict(item); freshness = item.get("freshness", {}); source = item.get("source_reliability") or 0; reliability = item.get("market_reliability") or 0; agreement = item.get("provider_agreement") or 0
            item["ranking_score"] = round(100 * (0.22 * ranking_probability + 0.14 * item["confidence"] / 100 + 0.12 * item["data_quality"] / 100 + 0.16 * reliability / 100 + 0.12 * min(1, max(0, edge)) + 0.08 * min(1, max(0, item.get("expected_value", 0) or 0)) + 0.08 * min(1, source / 100) + 0.04 * agreement + 0.04 * (1 if freshness.get("status") == "CURRENT" else 0)), 2)
            item["ranking_components"] = {"model_probability": ranking_probability, "confidence": item["confidence"], "data_quality": item["data_quality"], "market_reliability": reliability, "calibration_status": item.get("calibration_status"), "no_vig_edge": edge, "expected_value": item.get("expected_value"), "price_freshness": freshness, "source_reliability": source, "provider_agreement": agreement}
            result.append(item)
        return sorted(result, key=lambda item: item["ranking_score"], reverse=True)
