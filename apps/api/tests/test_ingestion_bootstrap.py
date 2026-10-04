from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.cache import MemoryCache
from app.db import Base
from app.models import Competition, Fixture, FixtureFeatureSnapshot, ProviderHealth, ProviderUsage, Team
from app.providers.api_sports import ApiSportsProvider, ProviderError, classify_api_error
from app.providers.base import NormalizedFixture
from app.quota import QuotaManager
from app.schemas import IngestionBootstrapRequest
from app.services.bootstrap import BootstrapScope, run_bootstrap


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


def _fixture() -> NormalizedFixture:
    return NormalizedFixture(
        provider="api-football", provider_fixture_id="100", sport="football", competition_name="Premier League", competition_provider_id="39", country_name="England", season_name="2026", home_provider_id="1", home_name="Arsenal", away_provider_id="2", away_name="Chelsea", kickoff_at=datetime(2026, 9, 1, 16, tzinfo=timezone.utc), status="finished", status_detail="Match Finished", home_score=2, away_score=1, period=None, clock=None, observed_at=datetime.now(timezone.utc), raw={}
    )


def _provider(items=None):
    provider = ApiSportsProvider(name="api-football", key="configured", base_url="https://provider.test", cache=MemoryCache(), quota=QuotaManager(mode="standard"))
    provider.configured = True
    async def fixtures_by_date(_date, league=None, season=None):
        provider.last_request_events = []
        return items if items is not None else [_fixture()]
    provider.fixtures_by_date = fixtures_by_date
    return provider


@pytest.mark.asyncio
async def test_bounded_bootstrap_is_idempotent_for_canonical_entities():
    engine = _engine()
    provider = _provider()
    scope = BootstrapScope(competition="39", lookback_days=0, lookahead_days=0, include_statistics=False, include_odds=False)
    with Session(engine) as db:
        first = await run_bootstrap(db, scope, provider=provider, odds_provider=None, record_provider_event=lambda *args: None)
        second = await run_bootstrap(db, scope, provider=provider, odds_provider=None, record_provider_event=lambda *args: None)
        assert first.status == "completed" and second.status == "completed"
        assert db.scalar(select(func.count()).select_from(Fixture)) == 1
        assert db.scalar(select(func.count()).select_from(Competition)) == 1
        assert db.scalar(select(func.count()).select_from(Team)) == 2
        assert db.scalar(select(func.count()).select_from(FixtureFeatureSnapshot)) == 1


@pytest.mark.parametrize(
    ("status_code", "category"),
    [(401, "authentication_failed"), (403, "entitlement_unavailable"), (429, "rate_limited")],
)
@pytest.mark.asyncio
async def test_bootstrap_stops_on_terminal_http_status_without_retrying_other_dates(status_code, category):
    engine = _engine()
    provider = _provider()
    calls = 0
    async def forbidden(_date, league=None, season=None):
        nonlocal calls
        calls += 1
        raise ProviderError("api-football", f"Provider returned HTTP {status_code}", status_code, category=category, terminal=True, external_request=True)
    provider.fixtures_by_date = forbidden
    with Session(engine) as db:
        result = await run_bootstrap(db, BootstrapScope(lookback_days=3, lookahead_days=3, include_statistics=False, include_odds=False), provider=provider, odds_provider=None, record_provider_event=lambda *args: None)
    assert calls == 1
    assert result.status == "failed"
    assert result.providers_unavailable == [{"provider": "api-football", "state": category}]


@pytest.mark.asyncio
async def test_http_200_api_level_plan_error_is_terminal_without_opening_circuit(monkeypatch):
    import app.providers.api_sports as module
    calls = 0

    class Response:
        status_code = 200
        headers = {}
        def json(self):
            return {"response": [], "errors": {"plan": "subscription does not support this endpoint; secret=must-not-leak"}}

    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def get(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            return Response()

    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    provider = ApiSportsProvider(name="api-football", key="configured", base_url="https://provider.test", cache=MemoryCache(), quota=QuotaManager(mode="standard"), retry_attempts=1)
    with pytest.raises(ProviderError) as caught:
        await provider.fixtures_by_date("2026-10-01", league="39")
    assert calls == 1
    assert caught.value.category == "plan_restricted"
    assert caught.value.terminal is True
    assert provider.circuit_open_until == 0
    assert provider.last_request_events[0]["external_request"] is True
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    ("error_payload", "expected_category", "expected_reason", "expected_key", "expected_shape"),
    [
        ({"plan": "date outside subscription window; credential=must-not-leak"}, "plan_restricted", "date_outside_subscription_window", "plan", "object"),
        ({"quota": "daily requests limit reached"}, "quota_exhausted", "daily_quota_exhausted", "quota", "object"),
        ({"rateLimit": "too many requests"}, "rate_limited", "rate_limit_exceeded", "rate_limit", "object"),
        ({"token": "invalid api key"}, "authentication_failed", "invalid_api_key", "token", "object"),
        ({"date": "invalid date format"}, "invalid_parameter", "invalid_date", "date", "object"),
        ({"season": "season is required"}, "missing_parameter", "season_required", "season", "object"),
        ({"league": "invalid league"}, "invalid_parameter", "invalid_league", "league", "object"),
        ({"mystery": "opaque provider detail secret=must-not-leak"}, "provider_error", "unknown_provider_error", "unknown_key", "object"),
        (["unexpected provider error secret=must-not-leak"], "provider_error", "unknown_provider_error", None, "list"),
    ],
)
@pytest.mark.asyncio
async def test_http_200_error_shapes_produce_safe_structured_diagnostics(monkeypatch, error_payload, expected_category, expected_reason, expected_key, expected_shape):
    import app.providers.api_sports as module

    class Response:
        status_code = 200
        headers = {}
        def json(self): return {"response": [], "errors": error_payload}

    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def get(self, *args, **kwargs): return Response()

    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    provider = ApiSportsProvider(name="api-football", key="configured", base_url="https://provider.test", cache=MemoryCache(), quota=QuotaManager(mode="standard"), retry_attempts=1)
    with pytest.raises(ProviderError) as caught:
        await provider.fixtures_by_date("2026-10-03", league="39")
    diagnostic = caught.value.diagnostic()
    assert diagnostic["classification"] == expected_category
    assert diagnostic["reason_code"] == expected_reason
    assert diagnostic["error_key"] == expected_key
    assert diagnostic["error_shape"] == expected_shape
    assert diagnostic["error_entry_count"] <= 32
    assert diagnostic["status_code"] == 200
    assert diagnostic["external_request"] is True
    assert diagnostic["terminal"] is True
    assert "must-not-leak" not in str(caught.value)
    assert "must-not-leak" not in str(provider.last_request_events)
    assert provider.consecutive_failures == 0
    assert provider.circuit_open_until == 0


def test_recursive_error_diagnostics_are_bounded_and_structural():
    nested_season = classify_api_error({"parameters": {"season": "required"}})
    assert nested_season.category == "missing_parameter"
    assert nested_season.reason_code == "season_required"
    assert nested_season.error_key == "season"
    assert nested_season.error_shape == "nested_object"

    nested_date = classify_api_error({"parameters": {"date": "invalid"}})
    assert nested_date.category == "invalid_parameter"
    assert nested_date.reason_code == "invalid_date"

    nested_list = classify_api_error({"outer": {"inner": ["opaque secret=must-not-leak"]}})
    assert nested_list.category == "provider_error"
    assert nested_list.error_key == "unknown_key"
    assert nested_list.error_shape == "nested_list"
    assert "must-not-leak" not in str(nested_list)

    deep = "opaque"
    for _ in range(8):
        deep = {"outer": deep}
    deep_result = classify_api_error(deep)
    assert deep_result.diagnostic_truncated is True or deep_result.error_shape == "malformed_response"

    huge = {f"unknown_{index}": "opaque" for index in range(40)}
    huge_result = classify_api_error(huge)
    assert huge_result.error_entry_count <= 32
    assert huge_result.diagnostic_truncated is True


def test_semantic_tags_never_contain_provider_text_or_credentials():
    classification = classify_api_error({"parameters": {"season": "required"}, "message": "api_key=SUPER_SECRET Authorization=Bearer SUPER_SECRET"})
    assert classification.semantic_tags == ("parameter", "season", "auth", "key")
    assert "SUPER_SECRET" not in str(classification)


@pytest.mark.parametrize(
    ("error_payload", "expected_category"),
    [
        ({"quota": "daily requests limit reached"}, "quota_exhausted"),
        ({"subscription": "endpoint is not available on your plan"}, "plan_restricted"),
    ],
)
@pytest.mark.asyncio
async def test_http_200_api_level_terminal_error_stops_bootstrap_dates(monkeypatch, error_payload, expected_category):
    import app.providers.api_sports as module
    calls = 0

    class Response:
        status_code = 200
        headers = {}
        def json(self): return {"response": [], "errors": error_payload}

    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def get(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            return Response()

    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    provider = ApiSportsProvider(name="api-football", key="configured", base_url="https://provider.test", cache=MemoryCache(), quota=QuotaManager(mode="standard"), retry_attempts=1)
    with Session(_engine()) as db:
        result = await run_bootstrap(db, BootstrapScope(lookback_days=3, lookahead_days=3, include_statistics=False, include_odds=False), provider=provider, odds_provider=None, record_provider_event=lambda *args: None)
    assert calls == 1
    assert result.status == "failed"
    assert result.provider_state == expected_category
    assert result.external_requests == 1
    assert provider.circuit_open_until == 0


@pytest.mark.asyncio
async def test_http_200_empty_response_is_no_data_and_does_not_trip_circuit(monkeypatch):
    import app.providers.api_sports as module

    class Response:
        status_code = 200
        headers = {}
        def json(self): return {"response": [], "errors": {}}

    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def get(self, *args, **kwargs): return Response()

    monkeypatch.setattr(module.httpx, "AsyncClient", Client)
    provider = ApiSportsProvider(name="api-football", key="configured", base_url="https://provider.test", cache=MemoryCache(), quota=QuotaManager(mode="standard"), retry_attempts=1)
    assert await provider.fixtures_by_date("2026-10-01", league="39") == []
    assert provider.consecutive_failures == 0
    assert provider.circuit_open_until == 0
    assert provider.last_success_at is not None


@pytest.mark.asyncio
async def test_empty_date_does_not_stop_later_permitted_dates():
    engine = _engine()
    provider = _provider()
    calls = 0

    async def dates(_date, league=None, season=None):
        nonlocal calls
        calls += 1
        provider.last_request_events = [{"external_request": True}]
        return [] if calls == 1 else [_fixture()]

    provider.fixtures_by_date = dates
    with Session(engine) as db:
        result = await run_bootstrap(db, BootstrapScope(lookback_days=1, lookahead_days=1, include_statistics=False, include_odds=False), provider=provider, odds_provider=None, record_provider_event=lambda *args: None)
        assert result.status == "completed"
        assert result.provider_state is None
        assert result.external_requests == 3
        assert db.scalar(select(func.count()).select_from(Fixture)) == 1
    assert calls == 3


@pytest.mark.asyncio
async def test_partial_bootstrap_persists_successful_dates_and_stops_after_terminal_failure():
    engine = _engine()
    provider = _provider()
    calls = 0
    async def mixed(_date, league=None, season=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            provider.last_request_events = [{"external_request": True}]
            return [_fixture()]
        provider.last_request_events = [{"external_request": True}]
        raise ProviderError("api-football", "Provider API error (quota_exhausted)", 200, category="quota_exhausted", terminal=True, external_request=True)
    provider.fixtures_by_date = mixed
    with Session(engine) as db:
        result = await run_bootstrap(db, BootstrapScope(lookback_days=3, lookahead_days=3, include_statistics=False, include_odds=False), provider=provider, odds_provider=None, record_provider_event=lambda *args: None)
        assert result.status == "partial"
        assert result.provider_state == "quota_exhausted"
        assert result.external_requests == 2
        assert db.scalar(select(func.count()).select_from(Fixture)) == 1
    assert calls == 2


@pytest.mark.asyncio
async def test_open_circuit_stops_without_counting_external_request():
    from time import monotonic
    provider = ApiSportsProvider(name="api-football", key="configured", base_url="https://provider.test", cache=MemoryCache(), quota=QuotaManager(mode="standard"), retry_attempts=1)
    provider.circuit_open_until = monotonic() + 30
    calls = 0

    async def call(_date, league=None, season=None):
        nonlocal calls
        calls += 1

        return await provider._fixtures({"date": _date, "league": str(league)})

    provider.fixtures_by_date = call
    with Session(_engine()) as db:
        result = await run_bootstrap(db, BootstrapScope(lookback_days=3, lookahead_days=3, include_statistics=False, include_odds=False), provider=provider, odds_provider=None, record_provider_event=lambda *args: None)
    assert result.status == "failed" and result.external_requests == 0
    assert calls == 1
    assert provider.last_request_events[0]["external_request"] is False


def test_structured_provider_diagnostics_are_persisted_without_raw_messages(monkeypatch):
    engine = _engine()
    provider = main_module.providers["football"]
    original_events = provider.last_request_events
    original_configured = provider.configured
    provider.configured = True
    provider.last_request_events = [{
        "endpoint": "fixtures",
        "status_code": 200,
        "latency_ms": 4.0,
        "rate_limit_remaining": None,
        "error": "Provider API error (invalid_parameter)",
        "error_category": "invalid_parameter",
        "reason_code": "season_required",
        "error_key": "season",
        "error_shape": "nested_object",
        "error_entry_count": 1,
        "semantic_tags": ["parameter", "season"],
        "diagnostic_truncated": False,
        "cache_hit": False,
        "external_request": True,
    }]
    monkeypatch.setattr(main_module, "SessionLocal", lambda: Session(engine))
    try:
        main_module._record_usage(provider, "bootstrap/fixtures", status_code=200, error="raw secret=must-not-leak")
        with Session(engine) as db:
            usage = db.scalar(select(ProviderUsage).where(ProviderUsage.provider == provider.name))
            health = db.scalar(select(ProviderHealth).where(ProviderHealth.provider == provider.name))
        assert usage is not None and usage.error_category == "invalid_parameter" and usage.reason_code == "season_required" and usage.error_key == "season" and usage.error_shape == "nested_object" and usage.semantic_tags == ["parameter", "season"]
        assert health is not None and health.state == "invalid_parameter" and health.reason_code == "season_required" and health.error_key == "season" and health.error_shape == "nested_object"
        assert "must-not-leak" not in (usage.error or "")
        assert "must-not-leak" not in (health.last_error or "")
    finally:
        provider.configured = original_configured
        provider.last_request_events = original_events


def test_bootstrap_auth_and_bounds(monkeypatch):
    old_token, old_env = main_module.settings.admin_token, main_module.settings.app_env
    monkeypatch.setattr(main_module.settings, "admin_token", "server-only")
    monkeypatch.setattr(main_module.settings, "app_env", "production")
    try:
        client = TestClient(main_module.app)
        assert client.post("/admin/ingestion/bootstrap", json={}).status_code == 401
        assert client.post("/admin/ingestion/bootstrap?token=server-only", json={}).status_code == 401
        assert client.post("/admin/ingestion/bootstrap", json={"lookback_days": 8}, headers={"Authorization": "Bearer server-only"}).status_code == 422

        async def fake_run(*args, **kwargs):
            from app.services.bootstrap import BootstrapResult
            return BootstrapResult(sport="football", scope={"lookback_days": 3})
        monkeypatch.setattr(main_module, "run_bootstrap", fake_run)
        response = client.post("/admin/ingestion/bootstrap", json={"include_odds": False}, headers={"Authorization": "Bearer server-only"})
        assert response.status_code == 200
        assert "server-only" not in response.text
        assert main_module._bootstrap_lock.acquire(blocking=False)
        try:
            assert client.post("/admin/ingestion/bootstrap", json={}, headers={"Authorization": "Bearer server-only"}).status_code == 409
        finally:
            main_module._bootstrap_lock.release()
        assert client.get("/admin/ingestion/status").status_code == 401
        assert client.get("/admin/ingestion/status", headers={"Authorization": "Bearer server-only"}).status_code == 200
    finally:
        main_module.settings.admin_token, main_module.settings.app_env = old_token, old_env


def test_bootstrap_request_rejects_urls_and_unbounded_windows():
    with pytest.raises(ValueError):
        IngestionBootstrapRequest(competition="https://provider.example", lookback_days=1)
    with pytest.raises(ValueError):
        IngestionBootstrapRequest(lookahead_days=8)
