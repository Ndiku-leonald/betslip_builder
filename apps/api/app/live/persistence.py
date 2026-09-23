from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.live.state import LiveMatchState, state_from_fixture
from app.models import Fixture, LiveMatchSnapshot, LivePredictionSnapshot


def persist_live_match_snapshot(db: Session, state: LiveMatchState, *, data_quality: dict | None = None) -> LiveMatchSnapshot:
    existing = db.scalar(select(LiveMatchSnapshot).where(LiveMatchSnapshot.fixture_id == state.fixture_id, LiveMatchSnapshot.source_provider == state.source_provider, LiveMatchSnapshot.observed_at == state.observed_at))
    if existing is not None:
        return existing
    row = LiveMatchSnapshot(
        fixture_id=state.fixture_id, source_provider=state.source_provider, source_event_id=state.source_event_id,
        source_timestamp=state.source_timestamp, observed_at=state.observed_at, ingested_at=datetime.now(timezone.utc),
        status=state.status, period=state.period, clock=state.clock, minute=state.minute, stoppage_time=state.stoppage_time,
        home_score=state.home_score, away_score=state.away_score, halftime_home_score=state.halftime_home_score,
        halftime_away_score=state.halftime_away_score, statistics=state.statistics, events=list(state.events), auxiliary=state.auxiliary, data_quality=data_quality or {},
    )
    db.add(row)
    db.flush()
    return row


def latest_live_match_snapshot(db: Session, fixture_id: str) -> LiveMatchSnapshot | None:
    return db.scalar(select(LiveMatchSnapshot).where(LiveMatchSnapshot.fixture_id == fixture_id).order_by(LiveMatchSnapshot.observed_at.desc(), LiveMatchSnapshot.ingested_at.desc()).limit(1))


def live_state_from_snapshot(row: LiveMatchSnapshot) -> LiveMatchState:
    return LiveMatchState(
        fixture_id=row.fixture_id, sport="basketball" if str(row.period or "").upper().startswith(("Q", "OT")) else "football",
        source_provider=row.source_provider, source_event_id=row.source_event_id, status=row.status, kickoff_at=None,
        source_timestamp=row.source_timestamp, observed_at=row.observed_at, provider_updated_at=row.source_timestamp,
        period=row.period, clock=row.clock, minute=row.minute, stoppage_time=row.stoppage_time,
        home_score=row.home_score, away_score=row.away_score, halftime_home_score=row.halftime_home_score,
        halftime_away_score=row.halftime_away_score, statistics=row.statistics or {}, events=tuple(row.events or []), auxiliary=row.auxiliary or {},
    )


def live_prediction_history(db: Session, fixture_id: str, limit: int = 500) -> list[LivePredictionSnapshot]:
    return list(db.scalars(select(LivePredictionSnapshot).where(LivePredictionSnapshot.fixture_id == fixture_id).order_by(LivePredictionSnapshot.observed_at.asc()).limit(limit)))


def state_for_fixture(db: Session, fixture: Fixture, sport: str) -> LiveMatchState:
    row = latest_live_match_snapshot(db, fixture.id)
    return replace(live_state_from_snapshot(row), sport=sport, kickoff_at=fixture.kickoff_at) if row is not None else state_from_fixture(fixture, sport)
