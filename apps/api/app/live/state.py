from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.providers.api_sports import _parse_dt, normalize_basketball, normalize_football
from app.providers.base import NormalizedFixture


def _number(value: Any, integer: bool = False) -> int | float | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value)) if integer else float(value)
    except (TypeError, ValueError):
        return None


def _clock_minutes(value: Any) -> tuple[int | None, int | None]:
    text = str(value or "").strip().replace("'", "")
    if not text:
        return None, None
    if "+" in text:
        base, extra = text.split("+", 1)
        minute, _ = _clock_minutes(base)
        return minute, _number(extra, integer=True)
    if ":" in text:
        return _number(text.split(":", 1)[0], integer=True), None
    return _number(text, integer=True), None


@dataclass(frozen=True)
class LiveMatchState:
    fixture_id: str
    sport: str
    source_provider: str
    source_event_id: str | None
    status: str
    kickoff_at: datetime | None
    source_timestamp: datetime | None
    observed_at: datetime
    provider_updated_at: datetime | None
    period: str | None = None
    clock: str | None = None
    minute: int | None = None
    stoppage_time: int | None = None
    home_score: int | None = None
    away_score: int | None = None
    halftime_home_score: int | None = None
    halftime_away_score: int | None = None
    statistics: dict[str, Any] = field(default_factory=dict)
    events: tuple[dict[str, Any], ...] = ()
    auxiliary: dict[str, Any] = field(default_factory=dict)

    @property
    def score(self) -> tuple[int | None, int | None]:
        return self.home_score, self.away_score

    @property
    def stats_observed_at(self) -> datetime | None:
        value = self.auxiliary.get("stats_observed_at")
        return _parse_dt(value) if isinstance(value, str) else value or self.provider_updated_at or self.source_timestamp

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["events"] = list(self.events)
        for key in ("kickoff_at", "source_timestamp", "observed_at", "provider_updated_at"):
            if value[key] is not None:
                value[key] = value[key].isoformat()
        return value


def _fixture_input(payload: Any, sport: str) -> tuple[NormalizedFixture, dict[str, Any]]:
    if isinstance(payload, NormalizedFixture):
        return payload, payload.raw or {}
    raw = payload if isinstance(payload, dict) else {}
    if sport == "football":
        return normalize_football(raw), raw
    return normalize_basketball(raw), raw


def _football_stats(raw: dict[str, Any], home_id: str, away_id: str) -> dict[str, Any]:
    result: dict[str, Any] = {"home": {}, "away": {}}
    rows = raw.get("statistics") or raw.get("response", [{}])[0].get("statistics", []) if isinstance(raw.get("response"), list) and raw.get("response") else raw.get("statistics", [])
    for row in rows or []:
        team = row.get("team", {}) if isinstance(row, dict) else {}
        side = "home" if str(team.get("id")) == str(home_id) else "away" if str(team.get("id")) == str(away_id) else None
        if side is None:
            continue
        for item in row.get("statistics", []) or []:
            key = str(item.get("type", "")).lower().replace(" ", "_").replace("%", "pct")
            value = item.get("value")
            if isinstance(value, str) and value.endswith("%"):
                value = _number(value[:-1])
            elif key in {"shots_on_goal", "total_shots", "corner_kicks", "yellow_cards", "red_cards", "fouls"}:
                value = _number(value, integer=True)
            else:
                value = _number(value)
            if value is not None:
                result[side][key] = value
    return result


def _event_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    events = raw.get("events")
    if isinstance(events, dict):
        events = events.get("response") or events.get("events")
    return [item for item in (events or []) if isinstance(item, dict)]


def normalize_football_live_state(payload: Any, *, fixture_id: str | None = None, observed_at: datetime | None = None, provider_updated_at: datetime | None = None) -> LiveMatchState:
    fixture, raw = _fixture_input(payload, "football")
    observed = observed_at or fixture.observed_at or datetime.now(timezone.utc)
    updated = provider_updated_at or fixture.provider_updated_at or _parse_dt((raw.get("fixture") or {}).get("update"))
    minute, stoppage = _clock_minutes(fixture.period or fixture.clock)
    status = (fixture.status or "unknown").lower()
    score = raw.get("score", {}) if isinstance(raw.get("score"), dict) else {}
    halftime = score.get("halftime", {}) if isinstance(score.get("halftime"), dict) else {}
    return LiveMatchState(
        fixture_id=str(fixture_id or fixture.provider_fixture_id), sport="football", source_provider=fixture.provider,
        source_event_id=str(fixture.provider_fixture_id), status=status, kickoff_at=fixture.kickoff_at,
        source_timestamp=updated or observed, observed_at=observed, provider_updated_at=updated,
        period=fixture.period, clock=fixture.clock, minute=minute,
        stoppage_time=stoppage, home_score=fixture.home_score, away_score=fixture.away_score,
        halftime_home_score=_number(halftime.get("home"), integer=True), halftime_away_score=_number(halftime.get("away"), integer=True),
        statistics=_football_stats(raw, fixture.home_provider_id, fixture.away_provider_id), events=tuple(_event_rows(raw)),
        auxiliary={"home_name": fixture.home_name, "away_name": fixture.away_name, "competition": fixture.competition_name, "raw": raw},
    )


def _basketball_stats(raw: dict[str, Any], home_id: str, away_id: str) -> dict[str, Any]:
    result: dict[str, Any] = {"home": {}, "away": {}}
    rows = raw.get("statistics") or raw.get("response") or []
    if isinstance(rows, dict):
        rows = rows.get("response") or rows.get("statistics") or []
    for row in rows:
        team = row.get("team", {}) if isinstance(row, dict) else {}
        side = "home" if str(team.get("id")) == str(home_id) else "away" if str(team.get("id")) == str(away_id) else None
        if side is None:
            continue
        values = row.get("statistics", row.get("stats", [])) or []
        if isinstance(values, dict):
            values = [{"type": key, "value": value} for key, value in values.items()]
        for item in values:
            key = str(item.get("type", item.get("name", ""))).lower().replace(" ", "_").replace("%", "pct")
            value = item.get("value", item.get("total")) if isinstance(item, dict) else None
            if isinstance(value, str) and "/" in value:
                made, attempted = value.split("/", 1)
                result[side][f"{key}_made"] = _number(made, integer=True)
                result[side][f"{key}_attempted"] = _number(attempted, integer=True)
            else:
                parsed = _number(value)
                if parsed is not None:
                    result[side][key] = parsed
    return result


def normalize_basketball_live_state(payload: Any, *, fixture_id: str | None = None, observed_at: datetime | None = None, provider_updated_at: datetime | None = None) -> LiveMatchState:
    fixture, raw = _fixture_input(payload, "basketball")
    observed = observed_at or fixture.observed_at or datetime.now(timezone.utc)
    updated = provider_updated_at or fixture.provider_updated_at or _parse_dt((raw.get("game") or {}).get("update"))
    return LiveMatchState(
        fixture_id=str(fixture_id or fixture.provider_fixture_id), sport="basketball", source_provider=fixture.provider,
        source_event_id=str(fixture.provider_fixture_id), status=(fixture.status or "unknown").lower(), kickoff_at=fixture.kickoff_at,
        source_timestamp=updated or observed, observed_at=observed, provider_updated_at=updated,
        period=fixture.period, clock=fixture.clock, minute=None, home_score=fixture.home_score, away_score=fixture.away_score,
        halftime_home_score=_number(((raw.get("scores") or {}).get("halftime") or {}).get("home"), integer=True) if isinstance(raw.get("scores"), dict) else None,
        halftime_away_score=_number(((raw.get("scores") or {}).get("halftime") or {}).get("away"), integer=True) if isinstance(raw.get("scores"), dict) else None,
        statistics=_basketball_stats(raw, fixture.home_provider_id, fixture.away_provider_id), events=tuple(_event_rows(raw)),
        auxiliary={"home_name": fixture.home_name, "away_name": fixture.away_name, "competition": fixture.competition_name, "raw": raw},
    )


def state_from_fixture(fixture: Any, sport: str, *, observed_at: datetime | None = None) -> LiveMatchState:
    observed = observed_at or getattr(fixture, "observed_at", None) or datetime.now(timezone.utc)
    return LiveMatchState(
        fixture_id=fixture.id, sport=sport, source_provider=fixture.provider, source_event_id=fixture.provider_fixture_id,
        status=fixture.status, kickoff_at=fixture.kickoff_at, source_timestamp=fixture.provider_updated_at or fixture.observed_at,
        observed_at=observed, provider_updated_at=fixture.provider_updated_at, period=fixture.period, clock=fixture.clock,
        minute=_number(fixture.period, integer=True) if sport == "football" else None, home_score=fixture.home_score, away_score=fixture.away_score,
    )
