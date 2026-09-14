import asyncio
import logging
from datetime import datetime
from time import perf_counter
from typing import Any

import httpx

from app.cache import CacheBackend
from app.providers.base import NormalizedFixture
from app.quota import QuotaManager

logger = logging.getLogger(__name__)


class ProviderError(RuntimeError):
    def __init__(self, provider: str, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_status(sport: str, short: str | None, long: str | None = None) -> str:
    code = (short or "").upper()
    if sport == "football":
        if code in {"1H", "2H", "ET", "P", "BT", "LIVE"}:
            return "live"
        if code == "HT":
            return "halftime"
        if code in {"FT", "AET", "PEN"}:
            return "finished"
        if code in {"PST", "SUSP", "INT"}:
            return "postponed"
        if code in {"CANC", "ABD", "AWD", "WO"}:
            return "cancelled"
        if code in {"NS", "TBD"}:
            return "scheduled"
        return "unknown"
    if code in {"Q1", "Q2", "Q3", "Q4", "OT", "LIVE", "HT"} or "LIVE" in (long or "").upper():
        return "live" if code != "HT" else "halftime"
    if code in {"FT", "AOT", "POST"}:
        return "finished"
    if code in {"CANC", "ABD", "PST"}:
        return "cancelled" if code == "CANC" else "postponed"
    if code in {"NS", "TBD"}:
        return "scheduled"
    return "unknown"


def normalize_football(payload: dict[str, Any]) -> NormalizedFixture:
    item = payload.get("fixture", {})
    teams = payload.get("teams", {})
    league = payload.get("league", {})
    status = item.get("status", {})
    goals = payload.get("goals", {})
    return NormalizedFixture(
        provider="api-football",
        provider_fixture_id=str(item.get("id")), sport="football",
        competition_name=league.get("name") or "Unknown competition",
        competition_provider_id=str(league["id"]) if league.get("id") is not None else None,
        country_name=league.get("country"),
        season_name=str(league["season"]) if league.get("season") is not None else None,
        home_provider_id=str(teams.get("home", {}).get("id")), home_name=teams.get("home", {}).get("name") or "Unknown home team",
        away_provider_id=str(teams.get("away", {}).get("id")), away_name=teams.get("away", {}).get("name") or "Unknown away team",
        kickoff_at=_parse_dt(item.get("date")),
        status=normalize_status("football", status.get("short"), status.get("long")),
        status_detail=status.get("long"), home_score=goals.get("home"), away_score=goals.get("away"),
        period=status.get("elapsed"), clock=f"{status.get('elapsed')}'" if status.get("elapsed") is not None else None,
        provider_timestamp=_parse_dt(item.get("date")), raw=payload,
    )


def normalize_basketball(payload: dict[str, Any]) -> NormalizedFixture:
    item = payload.get("game", payload)
    teams = item.get("teams", {})
    league = item.get("league", {})
    status = item.get("status", {})
    scores = item.get("scores", {})
    home_score = scores.get("home", {}).get("total") if isinstance(scores.get("home"), dict) else scores.get("home")
    away_score = scores.get("away", {}).get("total") if isinstance(scores.get("away"), dict) else scores.get("away")
    return NormalizedFixture(
        provider="api-basketball",
        provider_fixture_id=str(item.get("id")), sport="basketball",
        competition_name=league.get("name") or "Unknown competition",
        competition_provider_id=str(league["id"]) if league.get("id") is not None else None,
        country_name=league.get("country"), season_name=str(league["season"]) if league.get("season") is not None else None,
        home_provider_id=str(teams.get("home", {}).get("id")), home_name=teams.get("home", {}).get("name") or "Unknown home team",
        away_provider_id=str(teams.get("away", {}).get("id")), away_name=teams.get("away", {}).get("name") or "Unknown away team",
        kickoff_at=_parse_dt(item.get("date")),
        status=normalize_status("basketball", status.get("short"), status.get("long")),
        status_detail=status.get("long") or status.get("short"), home_score=home_score, away_score=away_score,
        period=str(status.get("period")) if status.get("period") is not None else None,
        clock=status.get("clock"), provider_timestamp=_parse_dt(item.get("date")), raw=payload,
    )


class ApiSportsProvider:
    def __init__(self, *, name: str, key: str | None, base_url: str, cache: CacheBackend, quota: QuotaManager) -> None:
        self.name, self.key, self.base_url, self.cache, self.quota = name, key, base_url.rstrip("/"), cache, quota
        self.configured = bool(key)
        self.last_success_at: datetime | None = None
        self.last_error: str | None = None
        self.last_latency_ms: float | None = None
        self.calls_today = 0

    async def _request(self, endpoint: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        if not self.configured:
            raise ProviderError(self.name, "Provider not configured")
        if not self.quota.allow(self.name):
            raise ProviderError(self.name, "Configured quota limit reached")
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        for attempt in range(3):
            started = perf_counter()
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.get(url, params=params, headers={"x-apisports-key": self.key or ""})
                self.last_latency_ms = round((perf_counter() - started) * 1000, 2)
                self.quota.record(self.name)
                self.calls_today += 1
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 2:
                        await asyncio.sleep(0.5 * (2**attempt))
                        continue
                if response.status_code >= 400:
                    raise ProviderError(self.name, f"Provider returned HTTP {response.status_code}", response.status_code)
                self.last_success_at = datetime.utcnow()
                self.last_error = None
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                self.last_error = str(exc)
                if attempt < 2:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                logger.warning("provider request failed provider=%s endpoint=%s", self.name, endpoint)
                raise ProviderError(self.name, "Provider request failed") from exc
        raise ProviderError(self.name, "Provider request failed")

    async def _fixtures(self, params: dict[str, str]) -> list[NormalizedFixture]:
        cache_key = f"{self.name}:fixtures:{sorted(params.items())}"
        ttl = 15 if params.get("live") else (300 if self.quota.mode == "free" else 60)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached
        payload = await self._request("fixtures" if self.name == "api-football" else "games", params)
        normalizer = normalize_football if self.name == "api-football" else normalize_basketball
        fixtures = [normalizer(item) for item in payload.get("response", [])]
        self.cache.set(cache_key, fixtures, ttl)
        return fixtures

    async def fixtures_by_date(self, date: str) -> list[NormalizedFixture]:
        return await self._fixtures({"date": date})

    async def live_fixtures(self) -> list[NormalizedFixture]:
        return await self._fixtures({"live": "all"})

    async def fixture_details(self, provider_fixture_id: str) -> dict[str, Any]:
        endpoint = "fixtures" if self.name == "api-football" else "games"
        return await self._request(endpoint, {"id": provider_fixture_id})

