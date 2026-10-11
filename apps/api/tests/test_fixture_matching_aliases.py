from datetime import datetime, timedelta, timezone

from app.providers.matching import match_fixture, normalize_team_name


def _fixture(home="Manchester United FC", away="Tottenham Hotspur FC"):
    return {
        "home": home,
        "away": away,
        "competition": "Premier League",
        "kickoff_at": datetime(2026, 10, 20, 15, tzinfo=timezone.utc),
    }


def test_known_aliases_are_canonicalized():
    assert normalize_team_name("Man United") == normalize_team_name("Manchester United FC")
    assert normalize_team_name("Spurs") == normalize_team_name("Tottenham Hotspur FC")
    assert normalize_team_name("Brighton") == normalize_team_name("Brighton & Hove Albion FC")


def test_alias_match_requires_kickoff_signal():
    known = _fixture()
    candidate = {
        "home": "Man United",
        "away": "Spurs",
        "competition": "soccer_epl",
        "kickoff_at": known["kickoff_at"],
    }
    result = match_fixture(candidate, [known])
    assert result["status"] == "matched"
    assert result["match"] == known


def test_wrong_opponent_does_not_match():
    known = _fixture()
    candidate = {
        "home": "Man United",
        "away": "Arsenal",
        "competition": "soccer_epl",
        "kickoff_at": known["kickoff_at"],
    }
    assert match_fixture(candidate, [known])["status"] != "matched"


def test_far_apart_kickoff_does_not_match():
    known = _fixture()
    candidate = {
        "home": "Man United",
        "away": "Spurs",
        "competition": "soccer_epl",
        "kickoff_at": known["kickoff_at"] + timedelta(days=2),
    }
    assert match_fixture(candidate, [known])["status"] != "matched"


def test_duplicate_canonical_fixtures_are_ambiguous():
    known = _fixture()
    candidate = {
        "home": "Man United",
        "away": "Spurs",
        "competition": "soccer_epl",
        "kickoff_at": known["kickoff_at"],
    }
    assert match_fixture(candidate, [known, dict(known)])["status"] == "ambiguous"


def test_coventry_newcastle_upcoming_match():
    known = _fixture("Coventry City FC", "Newcastle United FC")
    candidate = {
        "home": "Coventry City",
        "away": "Newcastle United",
        "competition": "soccer_epl",
        "kickoff_at": known["kickoff_at"],
    }
    result = match_fixture(candidate, [known])
    assert result["status"] == "matched"
    assert result["match"] == known
