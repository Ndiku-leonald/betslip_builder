"""Official football-data.org v4 adapter.

This provider is deliberately secondary.  It supplies fixture/results,
competition and standings context, but it is not treated as a source of
bookmaker odds, lineups, injuries, or live statistics.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

import httpx

from app.cache import CacheBackend
from app.providers.api_sports import _parse_dt
from app.providers.base import NormalizedFixture
from app.quota import QuotaManager


class FootballDataError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, *, category: str | None = None, reason_code: str | None = None, external_request: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.category = category
        self.reason_code = reason_code
        self.external_request = external_request


def _safe_header_int(headers: Any, name: str, *, maximum: int = 2_147_483_647) -> int | None:
    """Read a documented numeric response header without exposing its value raw."""
    value = headers.get(name)
    if value is None:
        return None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if 0 <= parsed <= maximum else None


def _status(value: str | None) -> str:
    return {
        "TIMED": "scheduled",
        "SCHEDULED": "scheduled",
        "IN_PLAY": "live",
        "PAUSED": "halftime",
        "FINISHED": "finished",
        "POSTPONED": "postponed",
        "SUSPENDED": "postponed",
        "CANCELLED": "cancelled",
    }.get((value or "").upper(), "unknown")


def normalize_match(payload: dict[str, Any]) -> NormalizedFixture:
    if not isinstance(payload, dict):
        raise FootballDataError("Provider response was malformed", category="malformed_response", reason_code="match_payload_malformed")
    competition = payload.get("competition")
    home_team = payload.get("homeTeam")
    away_team = payload.get("awayTeam")
    if not payload.get("id") or not isinstance(competition, dict) or competition.get("id") is None or not competition.get("name") or not isinstance(home_team, dict) or home_team.get("id") is None or not home_team.get("name") or not isinstance(away_team, dict) or away_team.get("id") is None or not away_team.get("name"):
        raise FootballDataError("Provider response was malformed", category="malformed_response", reason_code="match_payload_malformed")
    score = payload.get("score") or {}
    full_time = score.get("fullTime") if isinstance(score, dict) and isinstance(score.get("fullTime"), dict) else {}
    half_time = score.get("halfTime") if isinstance(score, dict) and isinstance(score.get("halfTime"), dict) else {}
    status = str(payload.get("status") or "")
    minute = payload.get("minute")
    return NormalizedFixture(
        provider="football-data.org",
        provider_fixture_id=str(payload.get("id")),
        sport="football",
        competition_name=str(competition["name"]),
        competition_provider_id=str(competition["id"]),
        country_name=str((payload.get("area") or {}).get("name")) if (payload.get("area") or {}).get("name") else None,
        season_name=str((payload.get("season") or {}).get("startDate")) if (payload.get("season") or {}).get("startDate") else None,
        home_provider_id=str(home_team["id"]),
        home_name=str(home_team["name"]),
        away_provider_id=str(away_team["id"]),
        away_name=str(away_team["name"]),
        kickoff_at=_parse_dt(payload.get("utcDate")),
        status=_status(status),
        status_detail=status or None,
        home_score=full_time.get("home") if full_time.get("home") is not None else half_time.get("home"),
        away_score=full_time.get("away") if full_time.get("away") is not None else half_time.get("away"),
        period=str(payload.get("stage")) if payload.get("stage") else None,
        clock=f"{minute}'" if minute is not None else None,
        raw=payload,
        observed_at=datetime.now(timezone.utc),
        provider_updated_at=_parse_dt(payload.get("lastUpdated")),
    )


class FootballDataProvider:
    name = "football-data.org"
    capabilities = {
        "fixtures": True,
        "historical_results": True,
        "competitions": True,
        "standings": True,
        "team_statistics": False,
        "player_statistics": False,
        "lineups": False,
        "injuries": False,
        "events": False,
        "live": False,
        "live_statistics": False,
        "prematch_odds": False,
        "live_odds": False,
    }

    def __init__(self, key: str | None, *, base_url: str = "https://api.football-data.org/v4", cache: CacheBackend | None = None, quota: QuotaManager | None = None, timeout: float = 15.0) -> None:
        self.key = key
        self.base_url = base_url.rstrip("/")
        self.cache = cache
        self.quota = quota
        self.timeout = timeout
        self.configured = bool(key)
        self.last_success_at: datetime | None = None
        self.last_error: str | None = None
        self.last_latency_ms: float | None = None
        self.last_status_code: int | None = None
        self.last_rate_limit_remaining: int | None = None
        self.last_external_request = False
        self.calls_today = 0
        self.last_cache_hit = False

    @staticmethod
    def _diagnostic_result(*, configured: bool, reachable: bool, authenticated: bool | None, available: bool, http_status: int | None, classification: str, reason_code: str, rate_limit_remaining: int | None = None, rate_limit_reset_seconds: int | None = None) -> dict[str, Any]:
        return {
            "provider": "football-data.org",
            "configured": configured,
            "reachable": reachable,
            "authenticated": authenticated,
            "available": available,
            "http_status": http_status,
            "classification": classification,
            "reason_code": reason_code,
            "rate_limit_remaining": rate_limit_remaining,
            "rate_limit_reset_seconds": rate_limit_reset_seconds,
        }

    async def status_diagnostic(self) -> dict[str, Any]:
        """Perform one safe, isolated authentication/capability check.

        The v4 ``/matches`` list is used because the official API policy says
        unauthenticated clients can access only area and competition lists.
        This method deliberately bypasses cache, quota accounting, ingestion
        events, provider health, and circuit state. It also never returns the
        response body or provider error text.
        """
        if not self.configured:
            return self._diagnostic_result(
                configured=False,
                reachable=False,
                authenticated=False,
                available=False,
                http_status=None,
                classification="not_configured",
                reason_code="provider_not_configured",
            )

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                response = await client.get(
                    f"{self.base_url}/matches",
                    headers={"X-Auth-Token": self.key or ""},
                )
        except httpx.TimeoutException:
            return self._diagnostic_result(
                configured=True,
                reachable=False,
                authenticated=None,
                available=False,
                http_status=None,
                classification="transport_failure",
                reason_code="provider_timeout",
            )
        except httpx.HTTPError:
            return self._diagnostic_result(
                configured=True,
                reachable=False,
                authenticated=None,
                available=False,
                http_status=None,
                classification="transport_failure",
                reason_code="provider_request_failed",
            )

        rate_limit_remaining = _safe_header_int(response.headers, "X-RequestsAvailable")
        rate_limit_reset_seconds = _safe_header_int(response.headers, "X-RequestCounter-Reset", maximum=86_400)
        status_code = response.status_code
        if status_code == 401:
            return self._diagnostic_result(configured=True, reachable=True, authenticated=False, available=False, http_status=status_code, classification="authentication_failure", reason_code="authentication_failed", rate_limit_remaining=rate_limit_remaining, rate_limit_reset_seconds=rate_limit_reset_seconds)
        if status_code == 403:
            # This check has no competition parameter, so a 403 is not
            # misreported as a competition restriction. The official API docs
            # describe this response as a restricted resource, including paid
            # plan access.
            return self._diagnostic_result(configured=True, reachable=True, authenticated=None, available=False, http_status=status_code, classification="plan_restricted", reason_code="restricted_resource", rate_limit_remaining=rate_limit_remaining, rate_limit_reset_seconds=rate_limit_reset_seconds)
        if status_code == 429:
            classification = "quota_exhausted" if rate_limit_remaining == 0 else "rate_limited"
            reason_code = "rate_limit_exhausted" if classification == "quota_exhausted" else "provider_rate_limited"
            return self._diagnostic_result(configured=True, reachable=True, authenticated=True, available=False, http_status=status_code, classification=classification, reason_code=reason_code, rate_limit_remaining=rate_limit_remaining, rate_limit_reset_seconds=rate_limit_reset_seconds)
        if status_code >= 500:
            return self._diagnostic_result(configured=True, reachable=True, authenticated=None, available=False, http_status=status_code, classification="provider_unavailable", reason_code="provider_http_5xx", rate_limit_remaining=rate_limit_remaining, rate_limit_reset_seconds=rate_limit_reset_seconds)
        if status_code >= 400:
            return self._diagnostic_result(configured=True, reachable=True, authenticated=None, available=False, http_status=status_code, classification="provider_error", reason_code=f"provider_http_{status_code}", rate_limit_remaining=rate_limit_remaining, rate_limit_reset_seconds=rate_limit_reset_seconds)

        try:
            payload = response.json()
        except (TypeError, ValueError):
            payload = None
        if not isinstance(payload, dict) or not isinstance(payload.get("matches"), list):
            return self._diagnostic_result(configured=True, reachable=True, authenticated=True, available=False, http_status=status_code, classification="malformed_response", reason_code="matches_payload_malformed", rate_limit_remaining=rate_limit_remaining, rate_limit_reset_seconds=rate_limit_reset_seconds)
        return self._diagnostic_result(configured=True, reachable=True, authenticated=True, available=True, http_status=status_code, classification="successful_usable_response", reason_code="authenticated_matches_response", rate_limit_remaining=rate_limit_remaining, rate_limit_reset_seconds=rate_limit_reset_seconds)

    async def _request(self, path: str, params: dict[str, Any] | None = None, *, ttl: int = 300) -> dict[str, Any]:
        self.last_cache_hit = False
        self.last_external_request = False
        self.last_error = None
        self.last_status_code = None
        cache_key = f"{self.name}:{path}:{sorted((params or {}).items())}"
        if self.cache is not None:
            cached = self.cache.get(cache_key)
            if cached is not None:
                self.last_cache_hit = True
                self.last_status_code = 200
                self.last_latency_ms = 0.0
                return cached
        if not self.configured:
            self.last_error = "Provider not configured"
            raise FootballDataError(self.last_error, category="missing", reason_code="provider_not_configured")
        reservation = self.quota.reserve(self.name, path) if self.quota is not None else None
        if self.quota is not None and reservation is None:
            self.last_status_code = 429
            self.last_error = "Configured quota limit reached"
            raise FootballDataError(self.last_error, 429, category="quota_exhausted", reason_code="request_quota_exhausted")
        started = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/{path.lstrip('/')}", params=params, headers={"X-Auth-Token": self.key or ""})
            self.last_external_request = True
            self.last_latency_ms = round((perf_counter() - started) * 1000, 2)
            self.last_status_code = response.status_code
            remaining = response.headers.get("X-Requests-Available-Minute")
            self.last_rate_limit_remaining = int(remaining) if remaining and remaining.isdigit() else None
            if response.status_code >= 400:
                self.last_error = f"Provider returned HTTP {response.status_code}"
                if response.status_code == 401:
                    category, reason = "authentication_failed", "authentication_failed"
                elif response.status_code == 403:
                    category, reason = "plan_restricted", "restricted_resource"
                elif response.status_code == 429:
                    category = "quota_exhausted" if self.last_rate_limit_remaining == 0 else "rate_limited"
                    reason = "rate_limit_exhausted" if category == "quota_exhausted" else "provider_rate_limited"
                elif response.status_code >= 500:
                    category, reason = "provider_unavailable", "provider_http_5xx"
                else:
                    category, reason = "provider_error", f"provider_http_{response.status_code}"
                raise FootballDataError(self.last_error, response.status_code, category=category, reason_code=reason, external_request=True)
            payload = response.json()
            if path.rstrip("/") == "matches" and (not isinstance(payload, dict) or not isinstance(payload.get("matches"), list)):
                self.last_error = "Provider response was malformed"
                raise FootballDataError(self.last_error, self.last_status_code, category="malformed_response", reason_code="matches_payload_malformed", external_request=True)
            self.last_success_at = datetime.now(timezone.utc)
            if self.cache is not None:
                self.cache.set(cache_key, payload, ttl)
            return payload
        except FootballDataError:
            raise
        except httpx.TimeoutException as exc:
            self.last_error = "Provider request timed out"
            raise FootballDataError(self.last_error, category="transport_failure", reason_code="provider_timeout", external_request=self.last_external_request) from exc
        except httpx.HTTPError as exc:
            self.last_error = "Provider request failed"
            raise FootballDataError(self.last_error, category="transport_failure", reason_code="provider_request_failed", external_request=self.last_external_request) from exc
        except (TypeError, ValueError) as exc:
            self.last_error = "Provider response was malformed"
            raise FootballDataError(self.last_error, self.last_status_code, category="malformed_response", reason_code="matches_payload_malformed", external_request=self.last_external_request) from exc
        finally:
            if self.quota is not None:
                self.quota.record(self.name, reservation)
                self.quota.complete(self.name, reservation, status_code=self.last_status_code, latency_ms=self.last_latency_ms, rate_limit_remaining=self.last_rate_limit_remaining, error=self.last_error)
                if reservation is not None:
                    self.calls_today += 1

    async def fixtures_by_date(self, date: str, league: str | None = None, season: str | None = None) -> list[NormalizedFixture]:
        return await self.fixtures_by_window(date, date, league=league, season=season)

    async def fixtures_by_window(self, date_from: str, date_to: str, *, league: str | None = None, season: str | None = None) -> list[NormalizedFixture]:
        params: dict[str, Any] = {"dateFrom": date_from, "dateTo": date_to}
        if league:
            params["competitions"] = league
        payload = await self._request("matches", params)
        return [normalize_match(item) for item in payload["matches"]]

    async def live_fixtures(self) -> list[NormalizedFixture]:
        payload = await self._request("matches", {"status": "IN_PLAY,PAUSED"}, ttl=15)
        return [normalize_match(item) for item in payload.get("matches", [])]

    async def fixture_details(self, provider_fixture_id: str) -> dict[str, Any]:
        return await self._request(f"matches/{provider_fixture_id}", {}, ttl=60)

    async def competitions(self) -> list[dict[str, Any]]:
        return (await self._request("competitions", {}, ttl=3600)).get("competitions", [])

    async def standings(self, competition: str) -> dict[str, Any]:
        return await self._request(f"competitions/{competition}/standings", {}, ttl=900)
