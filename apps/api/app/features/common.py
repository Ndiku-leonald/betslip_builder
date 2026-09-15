from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Fixture, FixtureFeatureSnapshot, TeamMatchStatistic


def mean(values: list[float], fallback: float = 0.0) -> float:
    clean = [float(value) for value in values if value is not None and isfinite(float(value))]
    return sum(clean) / len(clean) if clean else fallback


def safe_ratio(numerator: float, denominator: float, fallback: float = 0.0) -> float:
    return numerator / denominator if denominator else fallback


@dataclass
class FeatureRow:
    fixture_id: str
    sport: str
    data_cutoff_at: datetime
    values: dict[str, float] = field(default_factory=dict)
    data_quality: dict[str, Any] = field(default_factory=dict)
    actual: dict[str, float] | None = None


def load_history(db: Session, sport: str) -> tuple[list[Fixture], dict[tuple[str, str], TeamMatchStatistic]]:
    from app.models import Sport
    sport_id = db.scalar(select(Sport.id).where(Sport.slug == sport))
    fixtures = list(db.scalars(select(Fixture).where(Fixture.sport_id == sport_id, Fixture.status == "finished").order_by(Fixture.kickoff_at, Fixture.id))) if sport_id else []
    stats = db.scalars(select(TeamMatchStatistic).where(TeamMatchStatistic.fixture_id.in_([item.id for item in fixtures]))).all() if fixtures else []
    return fixtures, {(item.fixture_id, item.team_id): item for item in stats}


def persist_features(db: Session, rows: list[FeatureRow], feature_version: str) -> int:
    saved = 0
    for row in rows:
        cutoff = row.data_cutoff_at.astimezone(timezone.utc).replace(tzinfo=None) if row.data_cutoff_at.tzinfo else row.data_cutoff_at
        existing = db.scalar(select(FixtureFeatureSnapshot).where(FixtureFeatureSnapshot.fixture_id == row.fixture_id, FixtureFeatureSnapshot.feature_version == feature_version, FixtureFeatureSnapshot.data_cutoff_at == cutoff))
        if existing is None:
            db.add(FixtureFeatureSnapshot(fixture_id=row.fixture_id, sport=row.sport, feature_version=feature_version, data_cutoff_at=cutoff, values=row.values, data_quality=row.data_quality))
            saved += 1
    db.commit()
    return saved
