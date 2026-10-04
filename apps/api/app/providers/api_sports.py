import asyncio
import logging
import random
import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from time import monotonic, perf_counter
from typing import Any

import httpx

from app.cache import CacheBackend
from app.providers.base import NormalizedFixture
from app.quota import QuotaManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProviderErrorClassification:
    """Safe classification of an upstream provider error payload."""

    category: str
    reason_code: str
    error_key: str | None = None
    error_shape: str | None = None
    error_entry_count: int = 0
    semantic_tags: tuple[str, ...] = ()
    diagnostic_truncated: bool = False


_ERROR_KEY_ALIASES = {
    "api_key": "api_key",
    "apikey": "api_key",
    "auth": "authentication",
    "authentication": "authentication",
    "competition": "league",
    "date_from": "date",
    "date_to": "date",
    "from": "date",
    "league_id": "league",
    "parameter": "parameter",
    "parameters": "parameters",
    "ratelimit": "rate_limit",
    "rate_limit": "rate_limit",
    "request_limit": "quota",
    "subscription": "subscription",
    "timezone": "timezone",
    "to": "date",
}
_SAFE_ERROR_KEY = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_SAFE_ERROR_KEYS = {
    "api_key", "auth", "authentication", "circuit", "competition", "configuration", "date", "endpoint", "error", "fixture", "id", "league", "live", "message", "missing", "parameters", "parameter", "plan", "query", "quota", "rate_limit", "request_limit", "requests", "response", "season", "status", "subscription", "team", "timezone", "token", "transport", "unknown_key", "unsupported"
}
_MAX_ERROR_DEPTH = 4
_MAX_ERROR_ENTRIES = 32
_MAX_ERROR_TEXT_LENGTH = 256
_SEMANTIC_TAG_ORDER = (
    "date", "plan", "request", "limit", "parameter", "season", "league", "account", "access", "subscription", "auth", "token", "key", "timezone", "fixture", "endpoint"
)


@dataclass
class _ErrorInspection:
    shape: str
    entries: list[tuple[str | None, str]]
    structural_keys: tuple[str, ...]
    entry_count: int
    unknown_key_seen: bool
    semantic_tags: tuple[str, ...]
    truncated: bool


def _safe_error_key(value: Any) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value).strip().casefold()).strip("_")
    if not normalized or not _SAFE_ERROR_KEY.fullmatch(normalized):
        return None
    return _ERROR_KEY_ALIASES.get(normalized, normalized if normalized in _SAFE_ERROR_KEYS else None)


def _error_shape(value: Any, depth: int = 0) -> str:
    if depth > _MAX_ERROR_DEPTH:
        return "malformed_response"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        child_shapes = [_error_shape(item, depth + 1) for item in list(value.values())[:_MAX_ERROR_ENTRIES]]
        if any(shape in {"nested_list", "list"} for shape in child_shapes):
            return "nested_list"
        if any(shape in {"nested_object", "object"} for shape in child_shapes):
            return "nested_object"
        return "object"
    if isinstance(value, list):
        child_shapes = [_error_shape(item, depth + 1) for item in value[:_MAX_ERROR_ENTRIES]]
        if any(shape in {"nested_list", "nested_object", "list", "object"} for shape in child_shapes):
            return "nested_list"
        return "list"
    return "malformed_response"


def _semantic_tags(entries: list[tuple[str | None, str]], structural_keys: tuple[str, ...] = ()) -> tuple[str, ...]:
    keys = {key for key, _ in entries if key} | set(structural_keys)
    text = " ".join(f"{key or ''} {value}" for key, value in entries).casefold()
    rules = {
        "date": bool({"date"} & keys) or bool(re.search(r"\bdate\b", text)),
        "plan": "plan" in keys or bool(re.search(r"\bplan\b", text)),
        "request": "requests" in keys or "request_limit" in keys or bool(re.search(r"\brequests?\b", text)),
        "limit": "quota" in keys or "rate_limit" in keys or bool(re.search(r"\blimit\b|\bquota\b", text)),
        "parameter": "parameter" in keys or "parameters" in keys or bool(re.search(r"\bparameters?\b", text)),
        "season": "season" in keys or bool(re.search(r"\bseason\b", text)),
        "league": "league" in keys or bool(re.search(r"\bleague\b|\bcompetition\b", text)),
        "account": bool(re.search(r"\baccount\b|\bcredential\b", text)),
        "access": bool(re.search(r"\baccess\b|\bentitlement\b|\bforbidden\b|\bdenied\b", text)),
        "subscription": "subscription" in keys or bool(re.search(r"\bsubscription\b", text)),
        "auth": "auth" in keys or "authentication" in keys or bool(re.search(r"\bauth(?:entication|orization)?\b|\bunauthorized\b", text)),
        "token": "token" in keys or bool(re.search(r"\btoken\b", text)),
        "key": "api_key" in keys or bool(re.search(r"\bapi[_ -]?key\b|\binvalid key\b", text)),
        "timezone": "timezone" in keys or bool(re.search(r"\btimezone\b", text)),
        "fixture": "fixture" in keys or bool(re.search(r"\bfixture\b", text)),
        "endpoint": "endpoint" in keys or bool(re.search(r"\bendpoint\b", text)),
    }
    return tuple(tag for tag in _SEMANTIC_TAG_ORDER if rules[tag])


def _inspect_error(value: Any) -> _ErrorInspection:
    entries: list[tuple[str | None, str]] = []
    state = {"unknown_key_seen": False, "truncated": False, "structural_keys": set()}

    def visit(node: Any, depth: int, key_hint: str | None = None) -> None:
        if depth > _MAX_ERROR_DEPTH or len(entries) >= _MAX_ERROR_ENTRIES:
            state["truncated"] = True
            return
        if isinstance(node, dict):
            for raw_key, child in list(node.items())[:_MAX_ERROR_ENTRIES]:
                safe_key = _safe_error_key(raw_key)
                if safe_key is None:
                    state["unknown_key_seen"] = True
                else:
                    state["structural_keys"].add(safe_key)
                visit(child, depth + 1, safe_key or key_hint)
            if len(node) > _MAX_ERROR_ENTRIES:
                state["truncated"] = True
            return
        if isinstance(node, list):
            for child in node[:_MAX_ERROR_ENTRIES]:
                visit(child, depth + 1, key_hint)
            if len(node) > _MAX_ERROR_ENTRIES:
                state["truncated"] = True
            return
        entries.append((key_hint, str(node)[:_MAX_ERROR_TEXT_LENGTH]))

    visit(value, 0)
    return _ErrorInspection(
        shape=_error_shape(value),
        entries=entries,
        structural_keys=tuple(sorted(state["structural_keys"])),
        entry_count=len(entries),
        unknown_key_seen=bool(state["unknown_key_seen"]),
        semantic_tags=_semantic_tags(entries, tuple(sorted(state["structural_keys"]))),
        truncated=bool(state["truncated"]),
    )


def _error_entries(value: Any) -> list[tuple[str | None, str]]:
    return _inspect_error(value).entries


def classify_api_error(value: Any) -> ProviderErrorClassification:
    """Classify API-Sports errors without retaining their raw keys or values."""
    inspection = _inspect_error(value)
    entries = inspection.entries
    keys = set(inspection.structural_keys)
    text = " ".join(item for _, item in entries).casefold()
    text_with_keys = f"{' '.join(keys)} {text}"

    def result(category: str, reason_code: str, error_key: str | None = None) -> ProviderErrorClassification:
        return ProviderErrorClassification(category, reason_code, error_key, inspection.shape, inspection.entry_count, inspection.semantic_tags, inspection.truncated)

    if "season" in keys and any(token in text for token in ("required", "missing", "must provide", "needed")):
        return result("missing_parameter", "season_required", "season")
    plan_signal = bool({"plan", "subscription"} & keys) or any(token in text for token in ("subscription", "your plan", "free plan", "not subscribed"))
    date_access_signal = "date" in keys or any(token in text for token in ("date", "historical", "coverage", "allowed dates", "outside"))
    if plan_signal and date_access_signal:
        return result("plan_restricted", "date_outside_subscription_window", "plan" if "plan" in keys else "subscription" if "subscription" in keys else None)
    if ("date" in keys and any(token in text for token in ("invalid", "format", "required"))) or "invalid date" in text:
        return result("invalid_parameter", "invalid_date", "date")
    if "league" in keys and any(token in text for token in ("required", "missing")):
        return result("missing_parameter", "league_required", "league")
    if ("league" in keys and any(token in text for token in ("invalid", "unknown", "not found", "required"))) or any(token in text for token in ("invalid league", "invalid competition")):
        return result("invalid_parameter", "invalid_league", "league")
    if any(token in text_with_keys for token in ("missing parameter", "parameter required", "required parameter", "missing field")):
        return result("missing_parameter", "missing_parameter", "parameter" if "parameter" in keys else None)
    if any(token in text_with_keys for token in ("unsupported", "not supported", "unknown endpoint", "not available for this request")):
        return result("unsupported_request", "unsupported_request", next(iter(keys & {"endpoint", "unsupported"}), None))
    if any(token in text_with_keys for token in ("rate limit", "rate-limit", "ratelimit", "throttle", "too many requests")):
        return result("rate_limited", "rate_limit_exceeded", "rate_limit" if "rate_limit" in keys else None)
    if any(token in text_with_keys for token in ("quota", "daily limit", "daily request", "request limit", "requests limit", "remaining")):
        return result("quota_exhausted", "daily_quota_exhausted" if "daily" in text else "request_quota_exhausted", next(iter(keys & {"quota", "requests", "request_limit"}), None))
    if any(token in text_with_keys for token in ("unauthorized", "authentication", "invalid key", "api key", "token")):
        return result("authentication_failed", "invalid_api_key" if any(token in text for token in ("invalid", "key", "token")) else "authentication_failed", next(iter(keys & {"api_key", "authentication", "token"}), None))
    if plan_signal:
        return result("plan_restricted", "subscription_restricted", next(iter(keys & {"plan", "subscription"}), None))
    if any(token in text_with_keys for token in ("access denied", "forbidden", "entitlement")):
        return result("entitlement_unavailable", "access_denied", None)
    if any(token in text_with_keys for token in ("temporarily unavailable", "internal error", "service unavailable", "try again")):
        return result("temporarily_unavailable", "provider_temporarily_unavailable", None)
    return result("provider_error", "unknown_provider_error", "unknown_key" if inspection.unknown_key_seen else next(iter(keys), None))


def classify_http_error(status_code: int) -> ProviderErrorClassification:
    if status_code == 401:
        return ProviderErrorClassification("authentication_failed", "invalid_api_key", "status")
    if status_code == 403:
        return ProviderErrorClassification("entitlement_unavailable", "access_denied", "status")
    if status_code == 429:
        return ProviderErrorClassification("rate_limited", "rate_limit_exceeded", "status")
    if status_code == 400:
        return ProviderErrorClassification("invalid_parameter", "invalid_parameter", "status")
    if status_code >= 500:
        return ProviderErrorClassification("temporarily_unavailable", "provider_temporarily_unavailable", "status")
    return ProviderErrorClassification("provider_error", "provider_http_error", "status")


class ProviderError(RuntimeError):
    def __init__(self, provider: str, message: str, status_code: int | None = None, *, category: str | None = None, reason_code: str | None = None, error_key: str | None = None, error_shape: str | None = None, error_entry_count: int = 0, semantic_tags: tuple[str, ...] = (), diagnostic_truncated: bool = False, terminal: bool = False, retryable: bool = False, external_request: bool | None = None, endpoint: str | None = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.category = category
        self.reason_code = reason_code
        self.error_key = _safe_error_key(error_key)
        self.error_shape = error_shape
        self.error_entry_count = min(max(error_entry_count, 0), _MAX_ERROR_ENTRIES)
        self.semantic_tags = tuple(tag for tag in semantic_tags if tag in _SEMANTIC_TAG_ORDER)
        self.diagnostic_truncated = diagnostic_truncated
        self.terminal = terminal
        self.retryable = retryable
        self.external_request = external_request
        self.endpoint = endpoint

    def diagnostic(self, *, endpoint: str | None = None) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "endpoint": endpoint or self.endpoint,
            "classification": self.category or "provider_error",
            "reason_code": self.reason_code or "provider_error",
            "error_key": self.error_key,
            "error_shape": self.error_shape,
            "error_entry_count": self.error_entry_count,
            "semantic_tags": list(self.semantic_tags),
            "diagnostic_truncated": self.diagnostic_truncated,
            "status_code": self.status_code,
            "external_request": bool(self.external_request),
            "terminal": self.terminal,
            "retryable": self.retryable,
        }


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
        if name == "api-football":
            self.capabilities.update({"fixtures": True, "competitions": True, "injuries": True, "standings": True, "prematch_odds": True, "live_odds": True})
        self.last_success_at: datetime | None = None
        self.last_error: str | None = None
        self.last_latency_ms: float | None = None
        self.last_status_code: int | None = None
        self.last_cache_hit = False
        self.last_rate_limit_remaining: int | None = None
        self.last_observed_at: datetime | None = None
        self.last_request_events: list[dict[str, Any]] = []
        self.last_quota_blocked = False
        self.last_circuit_blocked = False
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
        self.last_circuit_blocked = False

    def _request_event(self, endpoint: str, *, status_code: int | None, latency_ms: float | None, rate_limit_remaining: int | None, error: str | None = None, classification: str | None = None, reason_code: str | None = None, error_key: str | None = None, error_shape: str | None = None, error_entry_count: int = 0, semantic_tags: tuple[str, ...] = (), diagnostic_truncated: bool = False, external_request: bool = True, requested_at: datetime | None = None, usage_id: str | None = None) -> None:
        self.last_request_events.append({"endpoint": endpoint, "requested_at": requested_at or datetime.now(timezone.utc), "usage_id": usage_id, "status_code": status_code, "latency_ms": latency_ms, "rate_limit_remaining": rate_limit_remaining, "error": error, "error_category": classification, "reason_code": reason_code, "error_key": error_key, "error_shape": error_shape, "error_entry_count": error_entry_count, "semantic_tags": list(semantic_tags), "diagnostic_truncated": diagnostic_truncated, "cache_hit": False, "external_request": external_request})

    def _complete_attempt(self, reservation, *, status_code: int | None, latency_ms: float | None, rate_limit_remaining: int | None, error: str | None = None) -> None:
        self.quota.record(self.name, reservation)
        self.quota.complete(self.name, reservation, status_code=status_code, latency_ms=latency_ms, rate_limit_remaining=rate_limit_remaining, error=error)
        self.calls_today += 1

    async def _request(self, endpoint: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        self._reset_request_state()
        if not self.configured:
            self.last_error = "Provider not configured"
            self.last_status_code = None
            raise ProviderError(self.name, self.last_error, category="missing", reason_code="provider_not_configured", terminal=True, external_request=False, endpoint=endpoint)
        if monotonic() < self.circuit_open_until:
            self.last_error = "Provider circuit is temporarily open"
            self.last_status_code = 503
            self.last_circuit_blocked = True
            self._request_event(endpoint, status_code=503, latency_ms=0.0, rate_limit_remaining=None, error=self.last_error, classification="temporarily_unavailable", reason_code="circuit_open", error_key="circuit", external_request=False)
            raise ProviderError(self.name, self.last_error, 503, category="temporarily_unavailable", reason_code="circuit_open", error_key="circuit", terminal=True, external_request=False, endpoint=endpoint)
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        for attempt in range(self.retry_attempts):
            if self.request_budget is not None and self.request_budget <= 0:
                self.last_error = "Historical request budget reached"
                self.last_status_code = 429
                self.last_quota_blocked = True
                self._request_event(endpoint, status_code=429, latency_ms=0.0, rate_limit_remaining=None, error=self.last_error, classification="quota_exhausted", reason_code="request_quota_exhausted", error_key="quota", external_request=False)
                raise ProviderError(self.name, self.last_error, 429, category="quota_exhausted", reason_code="request_quota_exhausted", error_key="quota", terminal=True, external_request=False, endpoint=endpoint)
            reservation = self.quota.reserve(self.name, endpoint)
            if reservation is None:
                self.last_error = "Configured quota limit reached"
                self.last_status_code = 429
                self.last_quota_blocked = True
                self._request_event(endpoint, status_code=429, latency_ms=0.0, rate_limit_remaining=None, error=self.last_error, classification="quota_exhausted", reason_code="request_quota_exhausted", error_key="quota", external_request=False)
                raise ProviderError(self.name, self.last_error, 429, category="quota_exhausted", reason_code="request_quota_exhausted", error_key="quota", terminal=True, external_request=False, endpoint=endpoint)
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
                    classification = classify_http_error(response.status_code)
                    self._complete_attempt(reservation, status_code=attempt_status, latency_ms=self.last_latency_ms, rate_limit_remaining=attempt_remaining, error=self.last_error)
                    self._request_event(endpoint, requested_at=requested_at, usage_id=reservation.token if reservation.persistent else None, status_code=response.status_code, latency_ms=self.last_latency_ms, rate_limit_remaining=self.last_rate_limit_remaining, error=self.last_error, classification=classification.category, reason_code=classification.reason_code, error_key=classification.error_key)
                    if attempt < self.retry_attempts - 1:
                        retry_after = response.headers.get("retry-after")
                        delay = self.retry_base_seconds * (2**attempt)
                        if retry_after and retry_after.isdigit():
                            delay = max(delay, min(float(retry_after), 30.0))
                        await asyncio.sleep(delay + random.uniform(0, min(delay * 0.1, 0.25)))
                        continue
                if response.status_code >= 400:
                    self.last_error = f"Provider returned HTTP {response.status_code}"
                    classification = classify_http_error(response.status_code)
                    if response.status_code < 500 and response.status_code != 429:
                        self._complete_attempt(reservation, status_code=attempt_status, latency_ms=self.last_latency_ms, rate_limit_remaining=attempt_remaining, error=self.last_error)
                        self._request_event(endpoint, requested_at=requested_at, usage_id=reservation.token if reservation.persistent else None, status_code=response.status_code, latency_ms=self.last_latency_ms, rate_limit_remaining=self.last_rate_limit_remaining, error=self.last_error, classification=classification.category, reason_code=classification.reason_code, error_key=classification.error_key)
                    if response.status_code >= 500:
                        self._record_failure()
                    raise ProviderError(self.name, self.last_error, response.status_code, category=classification.category, reason_code=classification.reason_code, error_key=classification.error_key, terminal=response.status_code < 500 or response.status_code == 429, retryable=response.status_code >= 500, endpoint=endpoint)
                payload = response.json()
                if not isinstance(payload, dict):
                    classification = ProviderErrorClassification("provider_error", "unknown_provider_error", "response", "malformed_response")
                    message = "Provider API error (provider_error)"
                    self.last_error = message
                    self._complete_attempt(reservation, status_code=attempt_status, latency_ms=self.last_latency_ms, rate_limit_remaining=attempt_remaining, error=message)
                    self._request_event(endpoint, requested_at=requested_at, usage_id=reservation.token if reservation.persistent else None, status_code=response.status_code, latency_ms=self.last_latency_ms, rate_limit_remaining=self.last_rate_limit_remaining, error=message, classification=classification.category, reason_code=classification.reason_code, error_key=classification.error_key, error_shape=classification.error_shape)
                    raise ProviderError(self.name, message, response.status_code, category=classification.category, reason_code=classification.reason_code, error_key=classification.error_key, error_shape=classification.error_shape, terminal=True, endpoint=endpoint)
                errors = payload.get("errors") if isinstance(payload, dict) else None
                if errors:
                    classification = classify_api_error(errors)
                    message = f"Provider API error ({classification.category})"
                    self.last_error = message
                    self._complete_attempt(reservation, status_code=attempt_status, latency_ms=self.last_latency_ms, rate_limit_remaining=attempt_remaining, error=message)
                    self._request_event(endpoint, requested_at=requested_at, usage_id=reservation.token if reservation.persistent else None, status_code=response.status_code, latency_ms=self.last_latency_ms, rate_limit_remaining=self.last_rate_limit_remaining, error=message, classification=classification.category, reason_code=classification.reason_code, error_key=classification.error_key, error_shape=classification.error_shape, error_entry_count=classification.error_entry_count, semantic_tags=classification.semantic_tags, diagnostic_truncated=classification.diagnostic_truncated)
                    # HTTP 200 plus an API-level error is a terminal semantic
                    # response for this bounded operation, not a transport
                    # failure. Do not trip the circuit breaker.
                    raise ProviderError(self.name, message, response.status_code, category=classification.category, reason_code=classification.reason_code, error_key=classification.error_key, error_shape=classification.error_shape, error_entry_count=classification.error_entry_count, semantic_tags=classification.semantic_tags, diagnostic_truncated=classification.diagnostic_truncated, terminal=True, retryable=False, external_request=True, endpoint=endpoint)
                self.last_observed_at = datetime.now(timezone.utc)
                self.last_success_at = self.last_observed_at
                self.last_error = None
                self._record_success()
                self._complete_attempt(reservation, status_code=attempt_status, latency_ms=self.last_latency_ms, rate_limit_remaining=attempt_remaining)
                self._request_event(endpoint, requested_at=requested_at, usage_id=reservation.token if reservation.persistent else None, status_code=response.status_code, latency_ms=self.last_latency_ms, rate_limit_remaining=self.last_rate_limit_remaining)
                return payload
            except (httpx.HTTPError, ValueError) as exc:
                self.last_error = "Provider request failed"
                self.last_latency_ms = round((perf_counter() - started) * 1000, 2)
                self._complete_attempt(reservation, status_code=attempt_status, latency_ms=self.last_latency_ms, rate_limit_remaining=attempt_remaining, error=self.last_error)
                self._request_event(endpoint, requested_at=requested_at, usage_id=reservation.token if reservation.persistent else None, status_code=attempt_status, latency_ms=self.last_latency_ms, rate_limit_remaining=attempt_remaining, error="Provider request failed", classification="temporarily_unavailable", reason_code="provider_request_failed", error_key="transport")
                self._record_failure()
                if attempt < self.retry_attempts - 1:
                    delay = self.retry_base_seconds * (2**attempt)
                    await asyncio.sleep(delay + random.uniform(0, min(delay * 0.1, 0.25)))
                    continue
                logger.warning("provider request failed provider=%s endpoint=%s", self.name, endpoint)
                raise ProviderError(self.name, "Provider request failed", category="temporarily_unavailable", reason_code="provider_request_failed", retryable=True, endpoint=endpoint) from exc
        raise ProviderError(self.name, "Provider request failed", category="temporarily_unavailable", reason_code="provider_request_failed", retryable=True, endpoint=endpoint)

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

    async def football_fixtures_by_league_season(self, league: str, season: str) -> list[NormalizedFixture]:
        """Fetch one explicitly selected API-Football league season."""
        if self.name != "api-football":
            raise ProviderError(self.name, "league-season fixtures are only supported by api-football")
        return await self._fixtures({"league": str(league), "season": str(season)})

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

    async def football_leagues(self, *, league: str | None = None, season: str | None = None) -> dict[str, Any]:
        if self.name != "api-football":
            raise ProviderError(self.name, "competitions is not supported by this provider")
        params: dict[str, str] = {}
        if league: params["id"] = str(league)
        if season: params["season"] = str(season)
        return await self._request("leagues", params)

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
