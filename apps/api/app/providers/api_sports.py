import asyncio
import logging
import random
from dataclasses import asdict, replace
from datetime import datetime, timezone
from time import monotonic, perf_counter
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
        provider_updated_at=_parse_dt(item.get("update")),
        raw=payload,
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
        clock=status.get("clock"), raw=payload, provider_updated_at=_parse_dt(item.get("update")),
    )


class ApiSportsProvider:
    def __init__(self, *, name: str, key: str | None, base_url: str, cache: CacheBackend, quota: QuotaManager, connect_timeout: float = 5.0, read_timeout: float = 15.0, retry_attempts: int = 3, retry_base_seconds: float = 0.5, circuit_failure_threshold: int = 5, circuit_cooldown_seconds: int = 30) -> None:
        self.name, self.key, self.base_url, self.cache, self.quota = name, key, base_url.rstrip("/"), cache, quota
        self.configured = bool(key)
        self.capabilities = {"stats": True, "player_stats": True, "events": name == "api-football", "lineups": name == "api-football"}
        self.last_success_at: datetime | None = None
        self.last_error: str | None = None
        self.last_latency_ms: float | None = None
        self.last_status_code: int | None = None
        self.last_cache_hit = False
        self.last_rate_limit_remaining: int | None = None
        self.last_observed_at: datetime | None = None
        self.last_request_events: list[dict[str, Any]] = []
        self.last_quota_blocked = False
        self.request_budget: int | None = None
        self.calls_today = 0
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.retry_attempts = retry_attempts
        self.retry_base_seconds = retry_base_seconds
        self.circuit_failure_threshold = circuit_failure_threshold
        self.circuit_cooldown_seconds = circuit_cooldown_seconds
        self.consecutive_failures = 0
        self.circuit_open_until = 0.0

    def _record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.circuit_failure_threshold:
            self.circuit_open_until = monotonic() + self.circuit_cooldown_seconds

    def _record_success(self) -> None:
        self.consecutive_failures = 0
        self.circuit_open_until = 0.0

    def _reset_request_state(self) -> None:
        self.last_cache_hit = False
        self.last_status_code = None
        self.last_latency_ms = None
        self.last_rate_limit_remaining = None
        self.last_observed_at = None
        self.last_request_events = []
        self.last_error = None
        self.last_quota_blocked = False

    def _request_event(self, endpoint: str, *, status_code: int | None, latency_ms: float | None, rate_limit_remaining: int | None, error: str | None = None, external_request: bool = True, requested_at: datetime | None = None, usage_id: str | None = None) -> None:
        self.last_request_events.append({"endpoint": endpoint, "requested_at": requested_at or datetime.now(timezone.utc), "usage_id": usage_id, "status_code": status_code, "latency_ms": latency_ms, "rate_limit_remaining": rate_limit_remaining, "error": error, "cache_hit": False, "external_request": external_request})

    def _complete_attempt(self, reservation, *, status_code: int | None, latency_ms: float | None, rate_limit_remaining: int | None, error: str | None = None) -> None:
        self.quota.record(self.name, reservation)
        self.quota.complete(self.name, reservation, status_code=status_code, latency_ms=latency_ms, rate_limit_remaining=rate_limit_remaining, error=error)
        self.calls_today += 1

    async def _request(self, endpoint: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        self._reset_request_state()
        if not self.configured:
            self.last_error = "Provider not configured"
            self.last_status_code = None
            raise ProviderError(self.name, "Provider not configured")
        if monotonic() < self.circuit_open_until:
            self.last_error = "Provider circuit is temporarily open"
            raise ProviderError(self.name, self.last_error, 503)
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        for attempt in range(self.retry_attempts):
            if self.request_budget is not None and self.request_budget <= 0:
                self.last_error = "Historical request budget reached"
                self.last_status_code = 429
                self.last_quota_blocked = True
                self._request_event(endpoint, status_code=429, latency_ms=0.0, rate_limit_remaining=None, error=self.last_error, external_request=False)
                raise ProviderError(self.name, self.last_error, 429)
            reservation = self.quota.reserve(self.name, endpoint)
            if reservation is None:
                self.last_error = "Configured quota limit reached"
                self.last_status_code = 429
                self.last_quota_blocked = True
                self._request_event(endpoint, status_code=429, latency_ms=0.0, rate_limit_remaining=None, error=self.last_error, external_request=False)
                raise ProviderError(self.name, self.last_error, 429)
            started = perf_counter()
            requested_at = datetime.now(timezone.utc)
            if self.request_budget is not None: self.request_budget -= 1
            attempt_status: int | None = None
            attempt_remaining: int | None = None
            try:
                timeout = httpx.Timeout(self.read_timeout, connect=self.connect_timeout)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(url, params=params, headers={"x-apisports-key": self.key or ""})
                self.last_latency_ms = round((perf_counter() - started) * 1000, 2)
                self.last_status_code = response.status_code
                attempt_status = response.status_code
                remaining = response.headers.get("x-ratelimit-requests-remaining")
                self.last_rate_limit_remaining = int(remaining) if remaining and remaining.isdigit() else None
                attempt_remaining = self.last_rate_limit_remaining
                if response.status_code == 429 or response.status_code >= 500:
                    self.last_error = f"Provider returned HTTP {response.status_code}"
                    self._complete_attempt(reservation, status_code=attempt_status, latency_ms=self.last_latency_ms, rate_limit_remaining=attempt_remaining, error=self.last_error)
                    self._request_event(endpoint, requested_at=requested_at, usage_id=reservation.token if reservation.persistent else None, status_code=response.status_code, latency_ms=self.last_latency_ms, rate_limit_remaining=self.last_rate_limit_remaining, error=self.last_error)
                    if attempt < self.retry_attempts - 1:
                        retry_after = response.headers.get("retry-after")
                        delay = self.retry_base_seconds * (2**attempt)
                        if retry_after and retry_after.isdigit():
                            delay = max(delay, min(float(retry_after), 30.0))
                        await asyncio.sleep(delay + random.uniform(0, min(delay * 0.1, 0.25)))
                        continue
                if response.status_code >= 400:
                    self.last_error = f"Provider returned HTTP {response.status_code}"
                    if response.status_code < 500 and response.status_code != 429:
                        self._complete_attempt(reservation, status_code=attempt_status, latency_ms=self.last_latency_ms, rate_limit_remaining=attempt_remaining, error=self.last_error)
                        self._request_event(endpoint, requested_at=requested_at, usage_id=reservation.token if reservation.persistent else None, status_code=response.status_code, latency_ms=self.last_latency_ms, rate_limit_remaining=self.last_rate_limit_remaining, error=self.last_error)
                    self._record_failure()
                    raise ProviderError(self.name, f"Provider returned HTTP {response.status_code}", response.status_code)
                payload = response.json()
                errors = payload.get("errors") if isinstance(payload, dict) else None
                if errors:
                    message = "; ".join(f"{key}: {value}" for key, value in errors.items()) if isinstance(errors, dict) else str(errors)
                    self.last_error = message
                    self._complete_attempt(reservation, status_code=attempt_status, latency_ms=self.last_latency_ms, rate_limit_remaining=attempt_remaining, error=message)
                    self._request_event(endpoint, requested_at=requested_at, usage_id=reservation.token if reservation.persistent else None, status_code=response.status_code, latency_ms=self.last_latency_ms, rate_limit_remaining=self.last_rate_limit_remaining, error=message)
                    self._record_failure()
                    raise ProviderError(self.name, message, response.status_code)
                self.last_observed_at = datetime.now(timezone.utc)
                self.last_success_at = self.last_observed_at
                self.last_error = None
                self._record_success()
                self._complete_attempt(reservation, status_code=attempt_status, latency_ms=self.last_latency_ms, rate_limit_remaining=attempt_remaining)
                self._request_event(endpoint, requested_at=requested_at, usage_id=reservation.token if reservation.persistent else None, status_code=response.status_code, latency_ms=self.last_latency_ms, rate_limit_remaining=self.last_rate_limit_remaining)
                return payload
            except (httpx.HTTPError, ValueError) as exc:
                self.last_error = str(exc)
                self.last_latency_ms = round((perf_counter() - started) * 1000, 2)
                self._complete_attempt(reservation, status_code=attempt_status, latency_ms=self.last_latency_ms, rate_limit_remaining=attempt_remaining, error=self.last_error)
                self._request_event(endpoint, requested_at=requested_at, usage_id=reservation.token if reservation.persistent else None, status_code=attempt_status, latency_ms=self.last_latency_ms, rate_limit_remaining=attempt_remaining, error=self.last_error)
                self._record_failure()
                if attempt < self.retry_attempts - 1:
                    delay = self.retry_base_seconds * (2**attempt)
                    await asyncio.sleep(delay + random.uniform(0, min(delay * 0.1, 0.25)))
                    continue
                logger.warning("provider request failed provider=%s endpoint=%s", self.name, endpoint)
                raise ProviderError(self.name, "Provider request failed") from exc
        raise ProviderError(self.name, "Provider request failed")

    async def _fixtures(self, params: dict[str, str]) -> list[NormalizedFixture]:
        self._reset_request_state()
        cache_key = f"{self.name}:fixtures:{sorted(params.items())}"
        ttl = 15 if params.get("live") else (300 if self.quota.mode == "free" else 60)
        cached = self.cache.get(cache_key)
        if cached is not None:
            if isinstance(cached, list) and all(isinstance(item, dict) for item in cached):
                cached = [self._from_cache(item) for item in cached]
            self.last_cache_hit = True
            self.last_status_code = 200
            self.last_latency_ms = 0.0
            self.last_error = None
            self.last_rate_limit_remaining = None
            return cached
        payload = await self._request("fixtures" if self.name == "api-football" else "games", params)
        normalizer = normalize_football if self.name == "api-football" else normalize_basketball
        fixtures = []
        for item in payload.get("response", []):
            normalized = normalizer(item)
            fixtures.append(replace(normalized, observed_at=self.last_observed_at, provider_updated_at=normalized.provider_updated_at))
        self.cache.set(cache_key, [self._to_cache(item) for item in fixtures], ttl)
        return fixtures

    @staticmethod
    def _to_cache(item: NormalizedFixture) -> dict[str, Any]:
        value = asdict(item)
        for key in ("kickoff_at", "observed_at", "provider_updated_at"):
            if value[key] is not None:
                value[key] = value[key].isoformat()
        return value

    @staticmethod
    def _from_cache(value: dict[str, Any]) -> NormalizedFixture:
        for key in ("kickoff_at", "observed_at", "provider_updated_at"):
            if value.get(key):
                value[key] = _parse_dt(value[key])
        return NormalizedFixture(**value)

    async def fixtures_by_date(self, date: str, league: str | None = None, season: str | None = None) -> list[NormalizedFixture]:
        params = {"date": date}
        if league: params["league"] = str(league)
        if season: params["season"] = str(season)
        return await self._fixtures(params)

    async def live_fixtures(self) -> list[NormalizedFixture]:
        return await self._fixtures({"live": "all"})

    async def football_fixture_details(self, provider_fixture_id: str) -> dict[str, Any]:
        return await self._request("fixtures", {"id": provider_fixture_id})

    async def football_statistics(self, provider_fixture_id: str) -> dict[str, Any]:
        return await self.football_fixture_details(provider_fixture_id)

    async def football_events(self, provider_fixture_id: str) -> dict[str, Any]:
        return await self.football_fixture_details(provider_fixture_id)

    async def football_lineups(self, provider_fixture_id: str) -> dict[str, Any]:
        return await self.football_fixture_details(provider_fixture_id)

    async def basketball_game_details(self, provider_fixture_id: str) -> dict[str, Any]:
        return await self._request("games", {"id": provider_fixture_id})

    async def basketball_team_statistics(self, provider_fixture_id: str) -> dict[str, Any]:
        return await self._request("games/statistics/teams", {"id": provider_fixture_id})

    async def basketball_player_statistics(self, provider_fixture_id: str) -> dict[str, Any]:
        return await self._request("games/statistics/players", {"id": provider_fixture_id})

    async def detail(self, kind: str, provider_fixture_id: str) -> dict[str, Any]:
        if not self.capabilities.get(kind, False):
            raise ProviderError(self.name, f"{kind} is not supported by {self.name}")
        if self.name == "api-football":
            return await {"stats": self.football_statistics, "player_stats": self.football_fixture_details, "events": self.football_events, "lineups": self.football_lineups}[kind](provider_fixture_id)
        if kind == "stats":
            return await self.basketball_team_statistics(provider_fixture_id)
        return await self.basketball_player_statistics(provider_fixture_id)

    async def fixture_details(self, provider_fixture_id: str) -> dict[str, Any]:
        return await (self.football_fixture_details(provider_fixture_id) if self.name == "api-football" else self.basketball_game_details(provider_fixture_id))
