"""Read-only adapter for livescoreFootball's documented HTTP API.

This is a secondary source.  It never writes over primary API-Sports data by
itself; callers must pass observations through the consensus service.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

import httpx

from app.providers.base import NormalizedFixture
from app.providers.api_sports import _parse_dt, normalize_status


class LiveScoreFootballError(RuntimeError):
    pass


class LiveScoreFootballProvider:
    name = "livescore-football"
    configured = True
    capabilities = {"leagues": True, "fixtures": True, "live": True, "scores": True, "statistics": True, "events": True, "clubs": True, "standings": True}

    def __init__(self, base_url: str = "https://worldcup26.ir", client=None, timeout: float = 15.0, cache=None):
        self.base_url = base_url.rstrip("/"); self.client = client; self.timeout = timeout; self.cache = cache
        self.last_success_at = None; self.last_error = None; self.last_latency_ms = None
        self._verified_league_mappings: dict[str, dict[str, Any]] = {}

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        cache_key = f"{self.name}:{path}:{sorted((params or {}).items())}"
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None: return cached
        try:
            if self.client is not None:
                response = await self.client.get(f"{self.base_url}/{path.lstrip('/')}", params=params)
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(f"{self.base_url}/{path.lstrip('/')}", params=params)
            if response.status_code >= 400: raise LiveScoreFootballError(f"HTTP {response.status_code}")
            self.last_success_at = datetime.now(timezone.utc); self.last_error = None
            payload = response.json()
            if self.cache is not None: self.cache.set(cache_key, payload, 30 if "scoreboard" in path else 300)
            return payload
        except (httpx.HTTPError, ValueError, LiveScoreFootballError) as exc:
            self.last_error = str(exc); raise LiveScoreFootballError(str(exc)) from exc

    @staticmethod
    def _items(payload: Any, *keys: str) -> list[dict]:
        if isinstance(payload, list): return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in keys:
                value = payload.get(key)
                if isinstance(value, list): return [item for item in value if isinstance(item, dict)]
            for value in payload.values():
                if isinstance(value, list) and all(isinstance(item, dict) for item in value): return value
        return []

    async def leagues(self, *, available: bool = True) -> list[dict]:
        payload = await self._get("get/soccer/leagues", {"kind": "club", "available": str(available).lower()})
        return self._items(payload, "leagues", "data", "response")

    @staticmethod
    def _name_key(value: Any) -> str:
        # Normalize display-name spelling only; never manufacture a provider slug.
        key = re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
        return "laliga" if key == "laliga" else key

    @staticmethod
    def _league_metadata(item: dict) -> dict[str, Any]:
        return {"slug": item.get("slug"), "name": item.get("name"), "country": item.get("country")}

    async def resolve_league(self, canonical_name: str, *, country: str | None = None) -> dict[str, Any]:
        """Resolve a canonical competition only from the provider league catalog."""
        cache_key = f"{self.name}:league-mapping:{self._name_key(canonical_name)}:{self._name_key(country)}"
        cached = self._verified_league_mappings.get(cache_key)
        if cached is None and self.cache is not None:
            cached = self.cache.get(cache_key)
        if isinstance(cached, dict):
            self._verified_league_mappings[cache_key] = cached
            return dict(cached)
        catalog = await self.leagues(available=True)
        requested_name = self._name_key(canonical_name)
        requested_country = self._name_key(country)
        candidates = [item for item in catalog if self._name_key(item.get("name")) == requested_name and item.get("slug")]
        if requested_country:
            country_candidates = [item for item in candidates if self._name_key(item.get("country")) == requested_country]
            if country_candidates:
                candidates = country_candidates
        if len(candidates) == 1:
            result = {"status": "matched", **self._league_metadata(candidates[0])}
        elif len(candidates) > 1:
            result = {"status": "ambiguous_league", "name": canonical_name, "country": country, "candidates": [self._league_metadata(item) for item in candidates]}
        else:
            result = {"status": "not_matched", "name": canonical_name, "country": country}
        if result["status"] == "matched":
            self._verified_league_mappings[cache_key] = result
            if self.cache is not None:
                self.cache.set(cache_key, result, 3600)
        return result

    async def _requested_league_slugs(self, league: str | None) -> list[str]:
        catalog = await self.leagues(available=True)
        if league is not None:
            direct = [item for item in catalog if str(item.get("slug")) == str(league)]
            if len(direct) == 1:
                return [str(direct[0]["slug"])]
            resolved = await self.resolve_league(str(league))
            return [str(resolved["slug"])] if resolved.get("status") == "matched" else []
        return [str(item["slug"]) for item in catalog if item.get("slug")]

    @staticmethod
    def _compact_date(value: str) -> str:
        compact = str(value).replace("-", "")
        if not re.fullmatch(r"\d{8}", compact):
            raise ValueError("LiveScoreFootball dates must be YYYYMMDD or YYYY-MM-DD")
        return compact

    @staticmethod
    def _normalize(item: dict, league: str | None = None) -> NormalizedFixture:
        event = item.get("event", item.get("game", item)); teams = event.get("teams", {})
        home = teams.get("home", event.get("home", {})); away = teams.get("away", event.get("away", {}))
        score = event.get("score", event.get("scores", {})); home_score = score.get("home") if isinstance(score, dict) else None; away_score = score.get("away") if isinstance(score, dict) else None
        if isinstance(home_score, dict): home_score = home_score.get("current", home_score.get("total"))
        if isinstance(away_score, dict): away_score = away_score.get("current", away_score.get("total"))
        status = event.get("status", {}); status_code = status.get("short", status.get("state")) if isinstance(status, dict) else status
        return NormalizedFixture(provider="livescore-football", provider_fixture_id=str(event.get("id", event.get("event_id", item.get("id")))), sport="football", competition_name=str(event.get("league_name", item.get("league", league or "Unknown competition"))), competition_provider_id=str(event.get("league_id", league)) if event.get("league_id", league) is not None else None, country_name=event.get("country"), season_name=str(event.get("season")) if event.get("season") else None, home_provider_id=str(home.get("id", home.get("source_id", ""))), home_name=home.get("name", home.get("display_name", "Unknown home team")), away_provider_id=str(away.get("id", away.get("source_id", ""))), away_name=away.get("name", away.get("display_name", "Unknown away team")), kickoff_at=_parse_dt(event.get("kickoff_at", event.get("date", event.get("start_time")))), status=normalize_status("football", status_code, status.get("long") if isinstance(status, dict) else None), status_detail=status.get("long") if isinstance(status, dict) else str(status), home_score=home_score, away_score=away_score, period=str(event.get("period")) if event.get("period") is not None else None, clock=str(event.get("clock", event.get("minute"))) if event.get("clock", event.get("minute")) is not None else None, raw=item, observed_at=_parse_dt(event.get("last_synced_at", event.get("updated_at"))) or datetime.now(timezone.utc), provider_updated_at=_parse_dt(event.get("last_synced_at")))

    async def fixtures(self, league: str, *, date: str | None = None, start: str | None = None, end: str | None = None) -> list[NormalizedFixture]:
        params = {"status": "all"}
        if date:
            compact = self._compact_date(date); params.update({"from": compact, "to": compact})
        else:
            if start: params["from"] = self._compact_date(start)
            if end: params["to"] = self._compact_date(end)
        payload = await self._get(f"get/soccer/{league}/fixtures", params)
        return [self._normalize(item, league) for item in self._items(payload, "fixtures", "events", "data", "response")]

    async def scoreboard(self, league: str, *, date: str | None = None) -> list[NormalizedFixture]:
        params = {"dates": self._compact_date(date)} if date else None
        payload = await self._get(f"get/soccer/{league}/scoreboard", params)
        return [self._normalize(item, league) for item in self._items(payload, "events", "fixtures", "games", "data", "response")]

    async def fixtures_by_date(self, date: str, league: str | None = None, season: str | None = None) -> list[NormalizedFixture]:
        leagues = await self._requested_league_slugs(league)
        result = []
        for item in leagues:
            result.extend(await self.fixtures(str(item), date=date))
        return result

    async def live_fixtures(self) -> list[NormalizedFixture]:
        result = []
        for league in await self._requested_league_slugs(None):
            result.extend(item for item in await self.scoreboard(str(league)) if item.status in {"live", "halftime"})
        return result

    async def detail(self, league: str, event_id: str, kind: str = "summary") -> dict:
        suffix = "events" if kind in {"summary", "events"} else kind
        return await self._get(f"get/soccer/{league}/{suffix}/{event_id}" if suffix != "events" else f"get/soccer/{league}/events/{event_id}")
