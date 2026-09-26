import pytest

from app.cache import MemoryCache
from app.providers.api_sports import normalize_basketball, normalize_football, normalize_status
from app.providers.api_sports import ApiSportsProvider
from app.providers.livescore_football import LiveScoreFootballProvider
from app.quota import QuotaManager


def test_football_normalization_maps_live_status_and_scores() -> None:
    item = normalize_football({
        "fixture": {"id": 123, "date": "2026-09-14T16:00:00+00:00", "status": {"short": "2H", "long": "Second Half", "elapsed": 61}},
        "league": {"id": 39, "name": "Premier League", "country": "England", "season": 2026},
        "teams": {"home": {"id": 1, "name": "Home"}, "away": {"id": 2, "name": "Away"}},
        "goals": {"home": 1, "away": 0},
    })
    assert item.provider_fixture_id == "123"
    assert item.status == "live"
    assert item.home_score == 1
    assert item.clock == "61'"
    assert item.observed_at is None
    assert item.provider_updated_at is None


def test_basketball_normalization_maps_period_and_total_score() -> None:
    item = normalize_basketball({
        "id": 456, "date": "2026-09-14T18:00:00+00:00", "status": {"short": "Q3", "period": 3, "clock": "04:21"},
        "league": {"id": 10, "name": "Example League", "country": "World", "season": 2026},
        "teams": {"home": {"id": 3, "name": "Home"}, "away": {"id": 4, "name": "Away"}},
        "scores": {"home": {"total": 70}, "away": {"total": 66}},
    })
    assert item.sport == "basketball"
    assert item.status == "live"
    assert item.home_score == 70
    assert item.period == "3"


def test_status_normalization_handles_finished_and_unknown() -> None:
    assert normalize_status("football", "FT") == "finished"
    assert normalize_status("basketball", "NS") == "scheduled"
    assert normalize_status("football", "???") == "unknown"


@pytest.mark.asyncio
async def test_livescore_league_catalog_resolves_canonical_names_without_slug_guessing() -> None:
    import app.providers.livescore_football as module

    calls = []
    catalog = {"leagues": [
        {"slug": "eng.1", "name": "Premier League", "country": "England"},
        {"slug": "esp.1", "name": "LaLiga", "country": "Spain"},
    ]}

    class Response:
        status_code = 200
        headers = {}

        def __init__(self, payload): self.payload = payload
        def json(self): return self.payload

    class Client:
        async def get(self, url, params=None, **kwargs):
            calls.append((url, params))
            return Response(catalog if url.endswith("/leagues") else {"fixtures": []})

    provider = LiveScoreFootballProvider("https://provider.test", client=Client(), cache=MemoryCache())
    assert (await provider.resolve_league("Premier League"))["slug"] == "eng.1"
    assert (await provider.resolve_league("La Liga"))["slug"] == "esp.1"
    unknown = await provider.resolve_league("Unknown Competition")
    assert unknown["status"] == "not_matched"
    assert all("premier-league" not in str(item) for item in calls)


@pytest.mark.asyncio
async def test_livescore_date_contract_uses_compact_fixture_range_and_scoreboard_date() -> None:
    calls = []

    class Response:
        status_code = 200
        headers = {}
        def json(self): return {"fixtures": []}

    class Client:
        async def get(self, url, params=None, **kwargs):
            calls.append((url, params)); return Response()

    provider = LiveScoreFootballProvider("https://provider.test", client=Client(), cache=MemoryCache())
    await provider.fixtures("eng.1", date="2026-09-16")
    await provider.scoreboard("eng.1", date="2026-09-16")
    assert calls[0] == ("https://provider.test/get/soccer/eng.1/fixtures", {"status": "all", "from": "20260916", "to": "20260916"})
    assert calls[1] == ("https://provider.test/get/soccer/eng.1/scoreboard", {"dates": "20260916"})


@pytest.mark.asyncio
async def test_basketball_statistics_capabilities_use_documented_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.providers.api_sports as provider_module

    payload = {"response": [{"game": {"id": 123}, "team": {"id": 10}, "field_goals": {"total": 22}}]}
    calls = []

    class FakeResponse:
        status_code = 200
        headers = {}

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, params=None, **kwargs):
            calls.append((url, params))
            return FakeResponse()

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", FakeClient)
    provider = ApiSportsProvider(name="api-basketball", key="configured", base_url="https://v1.basketball.api-sports.io", cache=MemoryCache(), quota=QuotaManager(mode="standard"))
    team_data = await provider.basketball_team_statistics("123")
    player_data = await provider.basketball_player_statistics("123")
    assert team_data["response"][0]["team"]["id"] == 10
    assert [url for url, _ in calls] == ["https://v1.basketball.api-sports.io/games/statistics/teams", "https://v1.basketball.api-sports.io/games/statistics/players"]
    assert [params for _, params in calls] == [{"id": "123"}, {"id": "123"}]
    assert provider.capabilities == {"stats": True, "player_stats": True, "events": False, "lineups": False}
    assert player_data["response"] == payload["response"]


@pytest.mark.asyncio
async def test_football_data_v4_normalizes_timezone_and_uses_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.providers.football_data as provider_module
    from app.providers.football_data import FootballDataProvider

    calls = []
    payload = {"matches": [{
        "id": 99,
        "utcDate": "2026-09-24T15:00:00Z",
        "status": "FINISHED",
        "lastUpdated": "2026-09-24T17:01:00Z",
        "competition": {"id": 2021, "name": "Premier League"},
        "area": {"name": "England"},
        "season": {"startDate": "2026-08-01"},
        "homeTeam": {"id": 65, "name": "Manchester City"},
        "awayTeam": {"id": 66, "name": "Liverpool FC"},
        "score": {"fullTime": {"home": 2, "away": 1}},
    }]}

    class Response:
        status_code = 200
        headers = {"X-Requests-Available-Minute": "9"}

        def json(self):
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
    provider = FootballDataProvider("configured", cache=MemoryCache(), quota=QuotaManager(mode="standard"))
    fixtures = await provider.fixtures_by_date("2026-09-24")

    assert fixtures[0].status == "finished"
    assert fixtures[0].kickoff_at is not None and fixtures[0].kickoff_at.tzinfo is not None
    assert fixtures[0].home_score == 2 and fixtures[0].away_score == 1
    assert calls[0][0].endswith("/matches")
    assert calls[0][2] == {"X-Auth-Token": "configured"}
    assert provider.last_rate_limit_remaining == 9


@pytest.mark.asyncio
async def test_api_football_league_season_uses_explicit_params(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = ApiSportsProvider(name="api-football", key="key", base_url="https://example.test", cache=MemoryCache(), quota=QuotaManager(mode="standard"))
    captured = {}

    async def fake_fixtures(params):
        captured.update(params)
        return []

    monkeypatch.setattr(provider, "_fixtures", fake_fixtures)
    fixtures = await provider.football_fixtures_by_league_season("39", "2024")
    assert fixtures == []
    assert captured == {"league": "39", "season": "2024"}
