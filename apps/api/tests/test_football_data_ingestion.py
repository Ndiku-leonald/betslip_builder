from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.main as main_module
import app.providers.football_data as provider_module
from app.cache import MemoryCache
from app.db import Base
from app.models import Competition, Fixture, FixtureFeatureSnapshot, ProviderEntityMapping, Team
from app.providers.api_sports import ApiSportsProvider
from app.providers.base import NormalizedFixture
from app.providers.football_data import FootballDataError, FootballDataProvider, normalize_match
from app.quota import QuotaManager
from app.schemas import IngestionBootstrapRequest
from app.services.bootstrap import BootstrapScope, run_football_data_bootstrap
from app.services.ingestion import ingest_fixtures
from app.config import Settings


def _engine():
    return create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)


def _match(*, status="FINISHED", home_score=2, away_score=1, fixture_id=99):
    return {
        "id": fixture_id,
        "utcDate": "2026-09-24T15:00:00Z",
        "status": status,
        "lastUpdated": "2026-09-24T17:01:00Z",
        "competition": {"id": 2021, "name": "Premier League", "code": "PL"},
        "area": {"name": "England"},
        "season": {"startDate": "2026-08-01"},
        "homeTeam": {"id": 65, "name": "Manchester City"},
        "awayTeam": {"id": 66, "name": "Liverpool FC"},
        "score": {"fullTime": {"home": home_score, "away": away_score}},
    }


def _provider():
    return FootballDataProvider("configured", base_url="https://provider.test", cache=MemoryCache(), quota=QuotaManager(mode="standard"))


def _http_response(monkeypatch, payload, *, status_code=200, headers=None, error=None):
    calls = []

    class Response:
        def __init__(self):
            self.status_code = status_code
            self.headers = headers or {}

        def json(self):
            if error:
                raise error
            return payload

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params=None, headers=None):
            calls.append((url, params, headers))
            return Response()

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", Client)
    return calls


def test_primary_provider_setting_has_safe_default_and_rejects_unknown_values():
    assert Settings().football_primary_provider == "api-football"
    assert Settings(football_primary_provider="football-data").football_primary_provider == "football-data"
    with pytest.raises(ValidationError):
        Settings(football_primary_provider="unknown")


def test_primary_provider_selection_does_not_fallback_to_api_football(monkeypatch):
    old = main_module.settings.football_primary_provider
    try:
        monkeypatch.setattr(main_module.settings, "football_primary_provider", "football-data")
        assert main_module.football_primary_provider() is main_module.football_data
        monkeypatch.setattr(main_module.settings, "football_primary_provider", "api-football")
        assert main_module.football_primary_provider() is main_module.football
    finally:
        main_module.settings.football_primary_provider = old


@pytest.mark.asyncio
async def test_football_data_window_uses_one_bounded_pl_request(monkeypatch):
    calls = _http_response(monkeypatch, {"matches": [_match()]}, headers={"X-Requests-Available-Minute": "9"})
    provider = _provider()
    fixtures = await provider.fixtures_by_window("2026-09-23", "2026-09-27", league="PL")
    assert len(fixtures) == 1
    assert len(calls) == 1
    assert calls[0][0].endswith("/matches")
    assert calls[0][1] == {"dateFrom": "2026-09-23", "dateTo": "2026-09-27", "competitions": "PL"}
    assert calls[0][2] == {"X-Auth-Token": "configured"}
    assert provider.last_external_request is True


def test_football_data_normalizes_completed_and_upcoming_results_without_fabrication():
    completed = normalize_match(_match())
    upcoming = normalize_match(_match(status="SCHEDULED", home_score=None, away_score=None, fixture_id=100))
    assert completed.provider == "football-data.org"
    assert completed.competition_provider_id == "2021"
    assert completed.status == "finished"
    assert (completed.home_score, completed.away_score) == (2, 1)
    assert upcoming.status == "scheduled"
    assert upcoming.home_score is None and upcoming.away_score is None


def test_canonical_ingestion_is_idempotent_and_provider_namespaced():
    engine = _engine()
    Base.metadata.create_all(engine)
    football_data_item = normalize_match(_match())
    with Session(engine) as db:
        ingest_fixtures(db, [football_data_item])
        ingest_fixtures(db, [replace(football_data_item, home_score=3, away_score=2)])
        assert db.scalar(select(func.count()).select_from(Competition)) == 1
        assert db.scalar(select(func.count()).select_from(Team)) == 2
        assert db.scalar(select(func.count()).select_from(Fixture)) == 1
        stored = db.scalar(select(Fixture))
        assert stored is not None and stored.provider == "football-data.org" and stored.home_score == 3
        assert db.scalar(select(func.count()).select_from(ProviderEntityMapping).where(ProviderEntityMapping.provider == "football-data.org")) == 4

        api_item = replace(football_data_item, provider="api-football", provider_fixture_id="99")
        ingest_fixtures(db, [api_item])
        assert db.scalar(select(func.count()).select_from(Fixture)) == 2
        mappings = list(db.scalars(select(ProviderEntityMapping).where(ProviderEntityMapping.entity_type == "fixture")))
        assert {(item.provider, item.provider_entity_id) for item in mappings} == {("football-data.org", "99"), ("api-football", "99")}


@pytest.mark.asyncio
async def test_football_data_bootstrap_is_pl_only_bounded_and_does_not_build_features(monkeypatch):
    calls = _http_response(monkeypatch, {"matches": [_match()]})
    provider = _provider()
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        result = await run_football_data_bootstrap(
            db,
            BootstrapScope(competition="PL", lookback_days=1, lookahead_days=3, include_statistics=True, include_odds=True),
            provider=provider,
            record_provider_event=lambda *args: None,
        )
        assert result.status == "completed"
        assert result.external_requests == 1
        assert result.fixtures_written == 1
        assert result.scope["max_fixture_requests"] == 1
        assert db.scalar(select(func.count()).select_from(FixtureFeatureSnapshot)) == 0
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_football_data_bootstrap_rejects_windows_over_one_three_without_request():
    provider = _provider()
    called = False

    async def forbidden(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider must not be called")

    provider.fixtures_by_window = forbidden
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        result = await run_football_data_bootstrap(db, BootstrapScope(competition="PL", lookback_days=2, lookahead_days=3), provider=provider, record_provider_event=lambda *args: None)
    assert result.error_category == "invalid_scope" and called is False


@pytest.mark.parametrize(
    ("status_code", "category"),
    [(401, "authentication_failed"), (403, "plan_restricted"), (429, "quota_exhausted"), (503, "provider_unavailable")],
)
@pytest.mark.asyncio
async def test_football_data_http_failures_are_terminal_and_single_request(monkeypatch, status_code, category):
    headers = {"X-Requests-Available-Minute": "0"} if status_code == 429 else {}
    calls = _http_response(monkeypatch, {"error": "sensitive provider text"}, status_code=status_code, headers=headers)
    provider = _provider()
    engine = _engine()
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        result = await run_football_data_bootstrap(db, BootstrapScope(competition="PL", lookback_days=1, lookahead_days=3), provider=provider, record_provider_event=lambda *args: None)
    assert len(calls) == 1
    assert result.status == "failed" and result.provider_state == category
    assert result.external_requests == 1


@pytest.mark.asyncio
async def test_football_data_timeout_and_malformed_payload_are_safe(monkeypatch):
    calls = 0

    class Client:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
        async def get(self, *args, **kwargs):
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout("token=secret", request=httpx.Request("GET", "https://provider.test"))

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", Client)
    with pytest.raises(FootballDataError) as caught:
        await _provider().fixtures_by_window("2026-09-23", "2026-09-27", league="PL")
    assert calls == 1 and caught.value.category == "transport_failure" and caught.value.reason_code == "provider_timeout"
    assert "secret" not in str(caught.value)

    _http_response(monkeypatch, {"matches": "not-a-list"})
    with pytest.raises(FootballDataError) as caught:
        await _provider().fixtures_by_window("2026-09-23", "2026-09-27", league="PL")
    assert caught.value.category == "malformed_response"


def test_bootstrap_request_accepts_first_bounded_window():
    request = IngestionBootstrapRequest(competition="PL", lookback_days=1, lookahead_days=3)
    assert request.lookback_days == 1 and request.lookahead_days == 3


@pytest.mark.asyncio
async def test_selected_football_data_bootstrap_never_calls_api_football(monkeypatch):
    old = main_module.settings.football_primary_provider
    monkeypatch.setattr(main_module.settings, "football_primary_provider", "football-data")
    async def forbidden(*args, **kwargs):
        raise AssertionError("API-Football fallback is forbidden")
    monkeypatch.setattr(main_module.football, "fixtures_by_date", forbidden)
    monkeypatch.setattr(main_module.football, "fixtures_by_league_season", forbidden, raising=False)
    try:
        assert main_module.provider_for_sport("football") is main_module.football_data
    finally:
        main_module.settings.football_primary_provider = old
