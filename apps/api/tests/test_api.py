from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
import app.main as main_module
from app.main import _app_today, app
from app.models import Fixture, ProviderHealth, ProviderUsage
from app.providers.api_sports import normalize_football
from app.services.ingestion import ingest_fixtures


def _football_fixture(status: str, fixture_id: int, date: str = "2026-09-15") -> dict:
    return {
        "fixture": {"id": fixture_id, "date": f"{date}T16:00:00+00:00", "status": {"short": status, "long": status}},
        "league": {"id": 39, "name": "Test League", "country": "Test", "season": 2026},
        "teams": {"home": {"id": fixture_id + 1, "name": "Home"}, "away": {"id": fixture_id + 2, "name": "Away"}},
        "goals": {"home": 1, "away": 0},
    }


def test_live_endpoint_includes_halftime_and_respects_limit() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ingest_fixtures(db, [normalize_football(_football_fixture("HT", 101)), normalize_football(_football_fixture("NS", 102))])

    def override_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/api/fixtures/live?limit=1")
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["status"] == "halftime"
    finally:
        app.dependency_overrides.clear()


def test_provider_usage_counts_real_calls_not_cache_hits() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        db.add_all([
            ProviderUsage(provider="api-football", endpoint="fixtures", requested_at=now, status_code=200, cache_hit=False),
            ProviderUsage(provider="api-football", endpoint="fixtures", requested_at=now, status_code=200, cache_hit=True),
        ])
        db.add(ProviderHealth(provider="api-football", configured=True, healthy=False, last_error="persisted provider error", calls_today=7))
        db.commit()

    def override_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/api/provider-usage")
        assert response.status_code == 200
        football = next(item for item in response.json() if item["provider"] == "api-football")
        assert football["calls_today"] == 1

        status = next(item for item in TestClient(app).get("/api/providers/status").json() if item["provider"] == "api-football")
        assert status["last_error"] == "persisted provider error"
        assert status["calls_today"] == 7
    finally:
        app.dependency_overrides.clear()


def test_today_query_filters_before_limit() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    today = _app_today()
    historical = (today - timedelta(days=2)).isoformat()
    with Session(engine) as db:
        items = [normalize_football(_football_fixture("NS", fixture_id, historical)) for fixture_id in range(200, 205)]
        items.append(normalize_football(_football_fixture("NS", 205, today.isoformat())))
        ingest_fixtures(db, items)

    def override_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        response = TestClient(app).get("/api/fixtures/today?limit=1")
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["kickoff_at"].startswith(today.isoformat())
    finally:
        app.dependency_overrides.clear()


def test_provider_request_events_are_persisted(monkeypatch) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    provider = main_module.providers["football"]
    original_configured = provider.configured
    original_events = provider.last_request_events
    original_blocked = provider.last_quota_blocked
    provider.configured = True
    provider.last_quota_blocked = False
    provider.last_request_events = [
        {"endpoint": "fixtures", "status_code": 500, "latency_ms": 12.0, "rate_limit_remaining": 98, "error": "retry", "cache_hit": False, "external_request": True},
        {"endpoint": "fixtures", "status_code": 200, "latency_ms": 8.0, "rate_limit_remaining": 97, "error": None, "cache_hit": False, "external_request": True},
    ]
    monkeypatch.setattr(main_module, "SessionLocal", lambda: Session(engine))
    try:
        main_module._record_usage(provider, "fixtures", status_code=200)
        with Session(engine) as db:
            rows = list(db.scalars(select(ProviderUsage).order_by(ProviderUsage.requested_at)))
        assert len(rows) == 2
        assert rows[0].status_code == 500
        assert rows[0].latency_ms == 12.0
        assert rows[0].rate_limit_remaining == 98
        assert rows[1].status_code == 200
        assert rows[1].external_request is True
    finally:
        provider.configured = original_configured
        provider.last_request_events = original_events
        provider.last_quota_blocked = original_blocked


@pytest.mark.asyncio
async def test_scheduler_lifecycle_is_single_instance_and_free_mode_skips_live_jobs(monkeypatch) -> None:
    class FakeScheduler:
        instances = []

        def __init__(self, **kwargs):
            self.running = False
            self.jobs = []
            FakeScheduler.instances.append(self)

        def add_job(self, func, trigger, **kwargs):
            self.jobs.append((func, trigger, kwargs))

        def start(self):
            self.running = True

        def shutdown(self, wait=False):
            self.running = False

    monkeypatch.setattr(main_module, "AsyncIOScheduler", FakeScheduler)
    monkeypatch.setattr(main_module.settings, "enable_scheduled_ingestion", True)
    monkeypatch.setattr(main_module.settings, "quota_mode", "free")
    await main_module.stop_scheduler()
    await main_module.start_scheduler()
    await main_module.start_scheduler()
    assert len(FakeScheduler.instances) == 1
    assert len(FakeScheduler.instances[0].jobs) == 2
    await main_module.stop_scheduler()
    assert main_module.scheduler is None


@pytest.mark.asyncio
async def test_statistics_detail_uses_stats_capability_and_statistics_payload(monkeypatch) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ingest_fixtures(db, [normalize_football(_football_fixture("NS", 301))])
        fixture_id = db.scalar(select(Fixture.id))

    provider = main_module.providers["football"]
    original_configured = provider.configured
    provider.configured = True

    async def fake_detail(kind: str, provider_fixture_id: str) -> dict:
        assert kind == "stats"
        assert provider_fixture_id == "301"
        return {"response": [{"statistics": [{"team": "Home"}]}]}

    def no_record(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(provider, "detail", fake_detail)
    monkeypatch.setattr(main_module, "_record_usage", no_record)
    try:
        with Session(engine) as db:
            result = await main_module._detail(fixture_id, "stats", db, response_key="statistics")
        assert result.available is True
        assert result.availability == "available"
        assert result.data == [{"team": "Home"}]
    finally:
        provider.configured = original_configured
