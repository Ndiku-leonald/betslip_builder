from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import ProviderHealth, ProviderUsage
from app.providers.api_sports import normalize_football
from app.services.ingestion import ingest_fixtures


def _football_fixture(status: str, fixture_id: int) -> dict:
    return {
        "fixture": {"id": fixture_id, "date": "2026-09-15T16:00:00+00:00", "status": {"short": status, "long": status}},
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
