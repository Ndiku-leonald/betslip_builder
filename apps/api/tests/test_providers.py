import pytest

from app.cache import MemoryCache
from app.providers.api_sports import normalize_basketball, normalize_football, normalize_status
from app.providers.api_sports import ApiSportsProvider
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
