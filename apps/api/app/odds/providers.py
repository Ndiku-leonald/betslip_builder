from __future__ import annotations

from typing import Any, Protocol

import httpx

from app.odds.ontology import NormalizedMarket, normalize_external_market


class OddsProvider(Protocol):
    name: str
    configured: bool

    async def list_events(self, sport: str, **kwargs) -> list[dict]: ...
    async def markets_for_fixture(self, fixture_id: str, sport: str, **kwargs) -> list[NormalizedMarket]: ...


class ApiSportsOddsProvider:
    name = "api-sports-odds"

    def __init__(self, provider):
        self.provider = provider; self.configured = provider.configured

    async def list_events(self, sport: str, **kwargs):
        return []

    async def markets_for_fixture(self, fixture_id: str, sport: str, **kwargs) -> list[NormalizedMarket]:
        payload = await self.provider._request("odds", {"fixture": str(fixture_id)})
        return parse_api_sports_odds(payload, fixture_id, sport, self.name)


class TheOddsApiProvider:
    name = "the-odds-api"

    def __init__(self, key: str | None, base_url: str = "https://api.the-odds-api.com/v4", client=None, regions: str = "eu"):
        self.key, self.base_url, self.client, self.regions = key, base_url.rstrip("/"), client, regions; self.configured = bool(key)

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        if not self.configured: raise RuntimeError("The Odds API is not configured")
        if self.client is not None: response = await self.client.get(f"{self.base_url}/{path.lstrip('/')}", params=params)
        else:
            async with httpx.AsyncClient(timeout=15) as client: response = await client.get(f"{self.base_url}/{path.lstrip('/')}", params=params)
        if response.status_code >= 400: raise RuntimeError(f"The Odds API returned HTTP {response.status_code}")
        return response.json()

    async def list_events(self, sport: str, **kwargs) -> list[dict]:
        params = {"apiKey": self.key, "regions": kwargs.get("regions", self.regions), "markets": kwargs.get("markets", "h2h,spreads,totals"), "oddsFormat": "decimal"}
        return await self._get(f"sports/{sport}/odds", params)

    async def markets_for_fixture(self, fixture_id: str, sport: str, **kwargs) -> list[NormalizedMarket]:
        params = {"apiKey": self.key, "regions": kwargs.get("regions", self.regions), "markets": kwargs.get("markets", "h2h,spreads,totals"), "oddsFormat": "decimal"}
        events = await self._get(f"sports/{sport}/events/{fixture_id}/odds", params)
        return parse_the_odds_api(events, fixture_id, sport, self.name)


class BetPawaImportProvider:
    name = "betpawa-import"
    configured = False

    async def list_events(self, sport: str, **kwargs): return []
    async def markets_for_fixture(self, fixture_id: str, sport: str, **kwargs): return []

    @staticmethod
    def from_records(records: list[dict], sport: str = "football") -> list[NormalizedMarket]:
        return [normalize_external_market(fixture_id=str(item["fixture_id"]), sport=sport, provider="betpawa-import", bookmaker=item.get("bookmaker", "BetPawa"), market_name=item["market_name"], selection_name=item["selection"], odds=item["odds"], line=item.get("line"), period=item.get("period", "full_game"), settlement_semantics=item.get("settlement_semantics"), status=item.get("status", "open"), observed_at=item.get("observed_at"), raw=item) for item in records]


def parse_api_sports_odds(payload: dict, fixture_id: str, sport: str, provider: str = "api-sports-odds") -> list[NormalizedMarket]:
    result = []
    for event in payload.get("response", []):
        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("bets", []):
                for value in market.get("values", []):
                    odd = value.get("odd")
                    if odd is None: continue
                    result.append(normalize_external_market(fixture_id=fixture_id, sport=sport, provider=provider, bookmaker=bookmaker.get("name", "Unknown"), market_name=market.get("name", "unknown"), selection_name=value.get("value", "unknown"), odds=odd, line=value.get("handicap"), status="open", source_event_id=str(event.get("fixture", {}).get("id", fixture_id)), raw=value))
    return result


def parse_the_odds_api(payload: list[dict], fixture_id: str, sport: str, provider: str = "the-odds-api") -> list[NormalizedMarket]:
    result = []
    for event in payload if isinstance(payload, list) else []:
        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                for outcome in market.get("outcomes", []):
                    result.append(normalize_external_market(fixture_id=fixture_id, sport=sport, provider=provider, bookmaker=bookmaker.get("title", "Unknown"), market_name=market.get("key", "unknown"), selection_name=outcome.get("name", "unknown"), odds=outcome.get("price"), line=outcome.get("point"), settlement_semantics="including_overtime" if sport == "basketball" and market.get("key") == "h2h" else None, source_event_id=event.get("id"), raw=outcome))
    return result
