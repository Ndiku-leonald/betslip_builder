from __future__ import annotations

from datetime import datetime, timezone

from app.odds.math import expected_value, fair_decimal_odds, implied_probability, no_vig, overround


def market_freshness(observed_at, *, now=None, ttl_seconds: int = 1800) -> dict:
    if observed_at is None: return {"status": "STALE", "age_seconds": None}
    now = now or datetime.now(timezone.utc); observed = observed_at.replace(tzinfo=timezone.utc) if observed_at.tzinfo is None else observed_at.astimezone(timezone.utc)
    age = max(0, int((now - observed).total_seconds()))
    return {"status": "CURRENT" if age <= ttl_seconds else "AGING" if age <= ttl_seconds * 2 else "STALE", "age_seconds": age}


class MarketValueService:
    profiles = {"conservative": {"probability": .60, "confidence": 65, "data_quality": 70, "edge": .02}, "balanced": {"probability": .53, "confidence": 50, "data_quality": 50, "edge": .01}, "aggressive": {"probability": .45, "confidence": 35, "data_quality": 35, "edge": .03}}

    def evaluate(self, market, model_probability_value: float, *, model_version=None, confidence: float = 0, data_quality: float = 0, reliability: float | None = None, market_group=None, now=None, ttl_seconds: int = 1800) -> dict:
        freshness = market_freshness(market.observed_at, now=now, ttl_seconds=ttl_seconds)
        result = {"fixture_id": market.fixture_id, "sport": market.sport, "bookmaker": market.bookmaker, "provider": market.provider, "market_family": market.market_family, "market_type": market.market_type, "selection": market.selection, "line": market.line, "bookmaker_odds": market.decimal_odds, "model_probability": model_probability_value, "fair_odds": fair_decimal_odds(model_probability_value) if model_probability_value and 0 < model_probability_value <= 1 else None, "odds_observed_at": market.observed_at.isoformat(), "freshness": freshness, "model_version": model_version, "confidence": confidence, "data_quality": data_quality, "market_reliability": reliability, "status": "CURRENT" if freshness["status"] != "STALE" and market.status == "open" else "NO_QUALIFYING_MARKET"}
        if market.decimal_odds is None: result.update({"raw_implied_probability": None, "no_vig_probability": None, "overround": None, "raw_probability_edge": None, "novig_probability_edge": None, "expected_value": None}); return result
        raw = implied_probability(market.decimal_odds); result["raw_implied_probability"] = raw
        prices = [item.decimal_odds for item in (market_group or []) if item.decimal_odds and item.status == "open"]
        if len(prices) >= 2:
            result["overround"] = overround(prices); group_probs = no_vig(prices)
            matching_index = next((index for index, item in enumerate(market_group) if item is market or (getattr(item, "selection", None) == getattr(market, "selection", None) and getattr(item, "line", None) == getattr(market, "line", None) and getattr(item, "market_family", None) == getattr(market, "market_family", None) and getattr(item, "bookmaker", None) == getattr(market, "bookmaker", None))), None)
            result["no_vig_probability"] = group_probs[matching_index] if matching_index is not None and matching_index < len(group_probs) else raw / sum(1 / price for price in prices)
        else:
            result["no_vig_probability"] = raw; result["overround"] = None
        result["raw_probability_edge"] = model_probability_value - raw; result["novig_probability_edge"] = model_probability_value - result["no_vig_probability"]; result["expected_value"] = expected_value(model_probability_value, market.decimal_odds)
        return result

    def rank(self, values: list[dict], profile: str = "balanced") -> list[dict]:
        thresholds = self.profiles.get(profile, self.profiles["balanced"]); result = []
        for item in values:
            if item["status"] == "NO_QUALIFYING_MARKET" or item.get("model_probability", 0) < thresholds["probability"] or item.get("confidence", 0) < thresholds["confidence"] or item.get("data_quality", 0) < thresholds["data_quality"] or item.get("novig_probability_edge", 0) < thresholds["edge"]: continue
            item = dict(item); item["ranking_score"] = round(100 * (0.35 * item["model_probability"] + 0.25 * item["confidence"] / 100 + 0.2 * item["data_quality"] / 100 + 0.2 * max(0, item.get("novig_probability_edge", 0))), 2); item["ranking_components"] = {"probability": item["model_probability"], "confidence": item["confidence"], "data_quality": item["data_quality"], "edge": item.get("novig_probability_edge", 0), "freshness": item["freshness"]}; result.append(item)
        return sorted(result, key=lambda item: item["ranking_score"], reverse=True)
