from dataclasses import replace
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.freshness import classify_freshness, data_age_seconds
from app.models import Competition, Fixture, Season
from app.providers.api_sports import normalize_football
from app.services.ingestion import ingest_fixtures


def payload() -> dict:
    return {"fixture": {"id": 789, "date": "2026-09-14T16:00:00+00:00", "status": {"short": "NS", "long": "Not Started"}}, "league": {"id": 1, "name": "Test League", "country": "Test", "season": 2026}, "teams": {"home": {"id": 11, "name": "Home"}, "away": {"id": 12, "name": "Away"}}, "goals": {"home": None, "away": None}}


def test_ingestion_is_idempotent() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    item = normalize_football(payload())
    with Session(engine) as db:
        assert ingest_fixtures(db, [item]) == 1
        assert ingest_fixtures(db, [item]) == 1
        assert len(db.scalars(select(Fixture)).all()) == 1
        assert len(db.scalars(select(Season)).all()) == 1


def test_ingestion_keeps_same_named_provider_competitions_separate() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    first = normalize_football(payload())
    second = replace(first, provider_fixture_id="790", competition_provider_id="99")
    with Session(engine) as db:
        ingest_fixtures(db, [first, second])
        competitions = db.scalars(select(Competition)).all()
    assert len(competitions) == 2


def test_freshness_is_age_aware() -> None:
    now = datetime.now(timezone.utc)
    assert data_age_seconds(now, now) == 0
    assert classify_freshness(status="live", observed_at=now - timedelta(seconds=45), now=now).value == "LIVE_CURRENT"
    assert classify_freshness(status="live", observed_at=now - timedelta(seconds=91), now=now).value == "STALE"
    assert classify_freshness(status="finished", observed_at=now, now=now).value == "RECENT"


def test_freshness_uses_observation_not_kickoff() -> None:
    now = datetime.now(timezone.utc)
    item = replace(normalize_football(payload()), status="live", kickoff_at=now - timedelta(minutes=45), observed_at=now)
    assert item.provider_updated_at is None
    assert classify_freshness(status=item.status, observed_at=item.observed_at, now=now).value == "LIVE_CURRENT"
    upcoming = replace(item, kickoff_at=now + timedelta(hours=2), observed_at=now - timedelta(hours=1))
    assert classify_freshness(status=upcoming.status, observed_at=upcoming.observed_at, now=now).value == "STALE"

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ingest_fixtures(db, [item])
        stored = db.scalar(select(Fixture))
        assert stored is not None
        assert stored.observed_at is not None
        assert data_age_seconds(stored.observed_at, now=now) <= 1
        assert stored.freshness == "LIVE_CURRENT"
