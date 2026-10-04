from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.cache import MemoryCache
from app.db import Base
from app.models import Competition, Fixture, FixtureFeatureSnapshot, Team
from app.providers.api_sports import ApiSportsProvider, ProviderError
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


@pytest.mark.asyncio
async def test_bootstrap_reports_provider_entitlement_without_retrying_other_dates():
    engine = _engine()
    provider = _provider()
    calls = 0
    async def forbidden(_date, league=None, season=None):
        nonlocal calls
        calls += 1
        raise ProviderError("api-football", "Provider returned HTTP 403", 403)
    provider.fixtures_by_date = forbidden
    with Session(engine) as db:
        result = await run_bootstrap(db, BootstrapScope(lookback_days=3, lookahead_days=3, include_statistics=False, include_odds=False), provider=provider, odds_provider=None, record_provider_event=lambda *args: None)
    assert calls == 1
    assert result.status == "failed"
    assert result.providers_unavailable == [{"provider": "api-football", "state": "entitlement_unavailable"}]


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
