from __future__ import annotations

from datetime import datetime, timezone
import re
from time import perf_counter
from typing import Any, Protocol

import httpx

from app.odds.ontology import NormalizedMarket, extract_line, normalize_external_market
from app.providers.api_sports import _parse_dt
from app.providers.matching import normalize_team_name
from app.quota import QuotaManager


class OddsProvider(Protocol):
    name: str
    configured: bool

    async def list_events(self, sport: str, **kwargs) -> list[dict]: ...
    async def markets_for_fixture(self, fixture_id: str, sport: str, **kwargs) -> list[NormalizedMarket]: ...


class OddsApiError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _team_participant(value: Any, event: dict) -> str | None:
    candidate = normalize_team_name(str(value or ""))
    home = normalize_team_name(event.get("home_team") or event.get("teams", {}).get("home", {}).get("name"))
    away = normalize_team_name(event.get("away_team") or event.get("teams", {}).get("away", {}).get("name"))
    if candidate and candidate == home: return "home"
    if candidate and candidate == away: return "away"
    if not home and not away and candidate in {"home", "away"}: return candidate
    return None


def _participant(value: Any, market_key: str, event: dict) -> str | None:
    participant = _team_participant(value, event)
    if participant: return participant
    label = str(value or "").strip().lower()
    participant_market = any(token in market_key for token in ("spread", "handicap", "team total", "team_total"))
    if participant_market:
        side_with_line = r"(?:\s+[+\-]?\d+(?:\.\d+)?)?"
        if re.fullmatch(rf"(?:home|home team|1|team 1){side_with_line}", label): return "home"
        if re.fullmatch(rf"(?:away|away team|2|team 2){side_with_line}", label): return "away"
        if re.fullmatch(rf"(?:draw|x){side_with_line}", label) and "handicap" in market_key: return "none"
        # Some team-total feeds put the side in the bet/value label while the
        # selection itself is only Over/Under.
        if re.search(r"\bhome\b", label) and re.search(r"\bteam\b|\btotal\b", label): return "home"
        if re.search(r"\baway\b", label) and re.search(r"\bteam\b|\btotal\b", label): return "away"
        if re.search(r"\bhome\b", market_key) and "total" in market_key: return "home"
        if re.search(r"\baway\b", market_key) and "total" in market_key: return "away"
    if participant_market and ("spread" in market_key or "handicap" in market_key):
        raise ValueError(f"ambiguous team normalization for spread outcome: {value!r}")
    if market_key in {"h2h", "moneyline", "match winner", "1x2"} and label == "draw": return "none"
    if market_key in {"totals", "game total", "btts"}: return "none"
    return "none"


def _status_value(value: Any) -> str:
    return str(value or "open").lower()


class ApiSportsOddsProvider:
    name = "api-sports-odds"

    def __init__(self, provider):
        self.provider = provider; self.configured = provider.configured

    async def list_events(self, sport: str, **kwargs): return []

    async def markets_for_fixture(self, fixture_id: str, sport: str, **kwargs) -> list[NormalizedMarket]:
        fetched_at = datetime.now(timezone.utc); payload = await self.provider._request("odds", {"fixture": str(fixture_id)})
        return parse_api_sports_odds(payload, fixture_id, sport, self.name, fetched_at=fetched_at)


class TheOddsApiProvider:
    name = "the-odds-api"

    def __init__(self, key: str | None, base_url: str = "https://api.the-odds-api.com/v4", client=None, regions: str = "eu", quota: QuotaManager | None = None):
        self.key, self.base_url, self.client, self.regions, self.quota = key, base_url.rstrip("/"), client, regions, quota; self.configured = bool(key)
        self.last_success_at: datetime | None = None; self.last_error: str | None = None; self.last_status_code: int | None = None; self.last_rate_limit_remaining: int | None = None; self.last_latency_ms: float | None = None; self.calls_today = 0

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        self.last_error = None; self.last_status_code = None; self.last_rate_limit_remaining = None
        if not self.configured: raise OddsApiError("The Odds API is not configured")
        endpoint = path.lstrip("/"); reservation = self.quota.reserve(self.name, endpoint) if self.quota is not None else None
        if self.quota is not None and reservation is None:
            self.last_status_code = 429; self.last_error = "Configured quota limit reached"
            raise OddsApiError(self.last_error, 429)
        started = perf_counter()
        try:
            if self.client is not None: response = await self.client.get(f"{self.base_url}/{endpoint}", params={"apiKey": self.key, **params})
            else:
                async with httpx.AsyncClient(timeout=15) as client: response = await client.get(f"{self.base_url}/{endpoint}", params={"apiKey": self.key, **params})
            self.last_latency_ms = round((perf_counter() - started) * 1000, 2); self.last_status_code = response.status_code
            remaining = response.headers.get("x-requests-remaining")
            self.last_rate_limit_remaining = int(remaining) if remaining and remaining.isdigit() else None
            if response.status_code >= 400:
                self.last_error = f"The Odds API returned HTTP {response.status_code}"
                raise OddsApiError(self.last_error, response.status_code)
            payload = response.json(); self.last_success_at = datetime.now(timezone.utc)
            return payload
        except OddsApiError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            self.last_error = "The Odds API request failed"
            raise OddsApiError(self.last_error) from exc
        finally:
            if self.quota is not None:
                self.quota.record(self.name, reservation); self.quota.complete(self.name, reservation, status_code=self.last_status_code, latency_ms=self.last_latency_ms, rate_limit_remaining=self.last_rate_limit_remaining, error=self.last_error)
                if reservation is not None: self.calls_today += 1

    async def list_events(self, sport: str, **kwargs) -> list[dict]:
        params = {"apiKey": self.key, "regions": kwargs.get("regions", self.regions), "markets": kwargs.get("markets", "h2h,spreads,totals"), "oddsFormat": "decimal"}
        return await self._get(f"sports/{sport}/odds", params)

    async def markets_for_fixture(self, fixture_id: str, sport: str, **kwargs) -> list[NormalizedMarket]:
        params = {"apiKey": self.key, "regions": kwargs.get("regions", self.regions), "markets": kwargs.get("markets", "h2h,spreads,totals"), "oddsFormat": "decimal"}
        fetched_at = datetime.now(timezone.utc); events = await self._get(f"sports/{sport}/events/{fixture_id}/odds", params)
        return parse_the_odds_api(events, fixture_id, sport, self.name, fetched_at=fetched_at)


class BetPawaImportProvider:
    name = "betpawa-import"
    configured = False

    async def list_events(self, sport: str, **kwargs): return []
    async def markets_for_fixture(self, fixture_id: str, sport: str, **kwargs): return []

    @staticmethod
    def from_records(records: list[dict], sport: str = "football") -> list[NormalizedMarket]:
        return [normalize_external_market(fixture_id=str(item["fixture_id"]), sport=sport, provider="betpawa-import", bookmaker=item.get("bookmaker", "BetPawa"), market_name=item["market_name"], selection_name=item["selection"], odds=item["odds"], line=item.get("line"), participant=item.get("participant"), period=item.get("period", "full_game"), settlement_semantics=item.get("settlement_semantics"), status=item.get("status", "open"), observed_at=item.get("observed_at"), provider_updated_at=item.get("provider_updated_at"), raw=item) for item in records]


def _timestamp(*values: Any) -> datetime | None:
    for value in values:
        parsed = _parse_dt(value)
        if parsed is not None: return parsed
    return None


def parse_api_sports_odds(payload: dict, fixture_id: str, sport: str, provider: str = "api-sports-odds", *, fetched_at: datetime | None = None) -> list[NormalizedMarket]:
    result = []
    for event in payload.get("response", []):
        fixture = event.get("fixture", {})
        teams = event.get("teams", {})
        identity_event = {"home_team": teams.get("home", {}).get("name"), "away_team": teams.get("away", {}).get("name")}
        event_updated = _timestamp(fixture.get("update"), fixture.get("updated_at"), fixture.get("last_update"), event.get("update"), event.get("updated_at"), event.get("last_update"))
        for bookmaker in event.get("bookmakers", []):
            bookmaker_updated = _timestamp(bookmaker.get("update"), bookmaker.get("last_update"), bookmaker.get("updated_at"))
            for market in bookmaker.get("bets", []):
                market_name = market.get("name", "unknown"); market_updated = _timestamp(market.get("update"), market.get("last_update"), market.get("updated_at"))
                for value in market.get("values", []):
                    odd = value.get("odd")
                    if odd is None: continue
                    try:
                        if float(odd) <= 1: continue
                    except (TypeError, ValueError):
                        continue
                    raw_name = value.get("value", "unknown"); resolved_participant = _participant(raw_name, market_name.lower(), identity_event)
                    h2h = any(token in market_name.lower() for token in ("winner", "h2h", "1x2", "moneyline"))
                    structured_line = value.get("handicap") if value.get("handicap") is not None else value.get("line") if value.get("line") is not None else market.get("handicap") if market.get("handicap") is not None else market.get("line")
                    if structured_line is None and any(token in market_name.lower() for token in ("handicap", "spread")):
                        side_line = re.search(r"(?:home|away|draw|1|2)\s*([+\-]?\d+(?:\.\d+)?)", str(raw_name), re.IGNORECASE)
                        structured_line = float(side_line.group(1)) if side_line else None
                    normalized = normalize_external_market(fixture_id=fixture_id, sport=sport, provider=provider, bookmaker=bookmaker.get("name", "Unknown"), market_name=market_name, selection_name=(resolved_participant if h2h and resolved_participant in {"home", "away"} else raw_name), odds=odd, line=structured_line if structured_line is not None else extract_line(raw_name) or extract_line(market_name), participant=None if h2h else resolved_participant, status="open", observed_at=fetched_at or datetime.now(timezone.utc), provider_updated_at=market_updated or bookmaker_updated or event_updated, source_event_id=str(fixture.get("id", fixture_id)), raw=value)
                    result.append(normalized)
    return result


def parse_the_odds_api(payload: list[dict], fixture_id: str, sport: str, provider: str = "the-odds-api", *, fetched_at: datetime | None = None) -> list[NormalizedMarket]:
    result = []
    for event in payload if isinstance(payload, list) else []:
        for bookmaker in event.get("bookmakers", []):
            bookmaker_updated = _parse_dt(bookmaker.get("last_update"))
            for market in bookmaker.get("markets", []):
                market_key = market.get("key", "unknown"); market_updated = _parse_dt(market.get("last_update"))
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name", "unknown"); selection = str(name).strip().lower()
                    try:
                        if float(outcome.get("price")) <= 1: continue
                    except (TypeError, ValueError):
                        continue
                    participant = _participant(name, market_key, event)
                    if market_key in {"totals", "team_totals"}: participant = _participant(outcome.get("description") or name, "totals", event)
                    if market_key in {"h2h", "spreads"} and participant == "none" and selection != "draw":
                        raise ValueError(f"ambiguous team normalization for The Odds API outcome: {name!r}")
                    line = outcome.get("point") if outcome.get("point") is not None else extract_line(name)
                    h2h = market_key == "h2h"
                    result.append(normalize_external_market(fixture_id=fixture_id, sport=sport, provider=provider, bookmaker=bookmaker.get("title", "Unknown"), market_name=market_key, selection_name=(participant if h2h and participant in {"home", "away"} else name), odds=outcome.get("price"), line=line, participant="none" if h2h else participant, settlement_semantics="including_overtime" if sport == "basketball" and market_key == "h2h" else None, source_event_id=event.get("id"), observed_at=fetched_at or datetime.now(timezone.utc), provider_updated_at=market_updated or bookmaker_updated, raw=outcome))
    return result
