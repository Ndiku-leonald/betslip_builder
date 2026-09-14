from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.freshness import classify_freshness, data_age_seconds
from app.models import Fixture
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


def test_freshness_is_age_aware() -> None:
    now = datetime.now(timezone.utc)
    assert data_age_seconds(now, now) == 0
    assert classify_freshness(status="live", provider_timestamp=now, now=now).value == "LIVE_CURRENT"
    assert classify_freshness(status="finished", provider_timestamp=now, now=now).value == "RECENT"

