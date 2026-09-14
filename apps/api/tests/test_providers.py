from app.providers.api_sports import normalize_basketball, normalize_football, normalize_status


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

