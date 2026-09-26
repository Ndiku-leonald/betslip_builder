from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Fixture, TeamMatchStatistic
from app.providers.api_sports import ApiSportsProvider
from app.providers.base import NormalizedFixture
from app.services.ingestion import ingest_fixtures


def _number(value: Any) -> float | None:
    if value is None: return None
    try: return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError): return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def normalize_football_stats(payload: dict[str, Any]) -> list[dict[str, Any]]:
    response = payload.get("response", [])
    result = []
    for item in response:
        team_id = str(item.get("team", {}).get("id"))
        mapped: dict[str, Any] = {"provider_team_id": team_id, "raw": item}
        for stat in item.get("statistics", []):
            name, value = stat.get("type"), stat.get("value")
            key = {"Total Shots": "shots", "Shots on Goal": "shots_on_target", "Ball Possession": "possession", "Corner Kicks": "corners", "Fouls": "fouls", "Yellow cards": "yellow_cards", "Red cards": "red_cards", "expected_goals": "expected_goals"}.get(name)
            if key: mapped[key] = _number(value)
        result.append(mapped)
    return result


def normalize_basketball_stats(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for item in payload.get("response", []):
        team = item.get("team", {})
        mapped: dict[str, Any] = {"provider_team_id": str(team.get("id")), "raw": item}
        for source, target in (("field_goals", ("field_goals_made", "field_goals_attempted")), ("threepoint_goals", ("three_pointers_made", "three_pointers_attempted")), ("freethrows_goals", ("free_throws_made", "free_throws_attempted"))):
            value = item.get(source) or {}
            if isinstance(value, dict):
                mapped[target[0]], mapped[target[1]] = _integer(value.get("made")), _integer(value.get("attempted"))
        for source, target in (("rebounds", "total_rebounds"), ("assists", "assists"), ("steals", "steals"), ("blocks", "blocks"), ("turnovers", "turnovers"), ("personal_fouls", "personal_fouls")):
            value = item.get(source)
            if isinstance(value, dict): value = value.get("total") or value.get("count")
            mapped[target] = _integer(value)
        result.append(mapped)
    return result


def _provider_team_id(item: NormalizedFixture, internal_team_id: str, is_home: bool) -> str:
    return item.home_provider_id if is_home else item.away_provider_id


def store_statistics(db: Session, fixture: Fixture, normalized: NormalizedFixture, payload: dict[str, Any]) -> int:
    rows = normalize_football_stats(payload) if normalized.sport == "football" else normalize_basketball_stats(payload)
    saved = 0
    for row in rows:
        provider_id = row["provider_team_id"]
        is_home = provider_id == str(normalized.home_provider_id)
        team_id = fixture.home_team_id if is_home else fixture.away_team_id if provider_id == str(normalized.away_provider_id) else None
        if team_id is None: continue
        values = {key: value for key, value in row.items() if key in TeamMatchStatistic.__table__.columns and key not in {"id", "fixture_id", "team_id"}}
        values["is_home"] = is_home; values["goals"] = fixture.home_score if is_home else fixture.away_score; values["points"] = fixture.home_score if is_home else fixture.away_score; values["observed_at"] = normalized.observed_at or datetime.now(timezone.utc)
        existing = db.scalar(select(TeamMatchStatistic).where(TeamMatchStatistic.fixture_id == fixture.id, TeamMatchStatistic.team_id == team_id))
        if existing is None: db.add(TeamMatchStatistic(fixture_id=fixture.id, team_id=team_id, **values)); saved += 1
        else:
            for key, value in values.items(): setattr(existing, key, value)
    db.commit(); return saved


def checkpoint_path(sport: str, league: str | None, season: str | None) -> Path:
    root = Path(__file__).resolve().parents[3] / "artifacts" / "checkpoints"; root.mkdir(parents=True, exist_ok=True)
    safe = "_".join(str(x or "all").replace("/", "-") for x in (sport, league, season))
    return root / f"{safe}.json"


async def ingest_range(db: Session, provider: ApiSportsProvider, start: date, end: date, *, league: str | None = None, season: str | None = None, max_requests: int | None = None, dry_run: bool = False, resume: bool = True, include_stats: bool = True) -> dict[str, int]:
    path = checkpoint_path(provider.name, league, season)
    cursor = start
    if resume and path.exists():
        try: cursor = max(start, date.fromisoformat(json.loads(path.read_text(encoding="utf-8")).get("last_date", start.isoformat())) )
        except (ValueError, OSError, json.JSONDecodeError): pass
    if dry_run: return {"dates": (end - cursor).days + 1, "fixtures": 0, "statistics": 0, "logical_operations": 0, "external_requests": 0, "cache_hits": 0}
    logical_operations = external_requests = cache_hits = fixtures_count = stats_count = 0
    while cursor <= end:
        if max_requests is not None and external_requests >= max_requests: break
        provider.request_budget = None if max_requests is None else max_requests - external_requests
        items = await provider.fixtures_by_date(cursor.isoformat(), league=league, season=season); logical_operations += 1
        events = list(provider.last_request_events); external_requests += sum(event.get("external_request", False) for event in events); cache_hits += int(provider.last_cache_hit)
        fixtures_count += ingest_fixtures(db, [x for x in items if x.status == "finished"])
        if include_stats:
            for item in items:
                if item.status != "finished" or max_requests is not None and external_requests >= max_requests: continue
                fixture = db.scalar(select(Fixture).where(Fixture.provider == item.provider, Fixture.provider_fixture_id == item.provider_fixture_id))
                if fixture is None: continue
                provider.request_budget = None if max_requests is None else max_requests - external_requests
                payload = await provider.detail("stats", item.provider_fixture_id); logical_operations += 1
                events = list(provider.last_request_events); external_requests += sum(event.get("external_request", False) for event in events); cache_hits += int(provider.last_cache_hit)
                stats_count += store_statistics(db, fixture, item, payload)
        path.write_text(json.dumps({"last_date": cursor.isoformat()}), encoding="utf-8")
        cursor = date.fromordinal(cursor.toordinal() + 1)
    provider.request_budget = None
    return {"dates": (cursor - start).days, "fixtures": fixtures_count, "statistics": stats_count, "logical_operations": logical_operations, "external_requests": external_requests, "cache_hits": cache_hits}


async def ingest_league_season(db: Session, provider: ApiSportsProvider, league: str, season: str) -> dict[str, int | str]:
    """Ingest one explicitly selected football league-season without stats."""
    items = await provider.football_fixtures_by_league_season(league, season)
    saved = ingest_fixtures(db, items)
    return {
        "league": str(league),
        "season": str(season),
        "fixtures": saved,
        "finished": sum(item.status == "finished" for item in items),
        "statistics": 0,
    }
