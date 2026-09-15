from __future__ import annotations

from collections import Counter
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import Fixture, Sport, TeamMatchStatistic


def audit(db: Session, sport: str) -> dict:
    sport_id = db.scalar(select(Sport.id).where(Sport.slug == sport))
    fixtures = list(db.scalars(select(Fixture).where(Fixture.sport_id == sport_id).order_by(Fixture.kickoff_at))) if sport_id else []
    keys = [(x.provider, x.provider_fixture_id) for x in fixtures]
    duplicate_count = len(keys) - len(set(keys))
    invalid = sum(1 for x in fixtures if x.status == "finished" and (x.home_score is None or x.away_score is None or x.home_score < 0 or x.away_score < 0))
    stats = db.scalar(select(TeamMatchStatistic).join(Fixture).where(Fixture.sport_id == sport_id).count()) if False else len(db.scalars(select(TeamMatchStatistic).where(TeamMatchStatistic.fixture_id.in_([x.id for x in fixtures]))).all()) if fixtures else 0
    return {"sport": sport, "fixture_count": len(fixtures), "finished_count": sum(x.status == "finished" for x in fixtures), "duplicate_fixtures": duplicate_count, "invalid_scores": invalid, "stat_snapshot_count": stats, "competition_counts": dict(Counter(x.competition_id for x in fixtures)), "date_start": fixtures[0].kickoff_at.isoformat() if fixtures and fixtures[0].kickoff_at else None, "date_end": fixtures[-1].kickoff_at.isoformat() if fixtures and fixtures[-1].kickoff_at else None}


if __name__ == "__main__":
    import argparse
    from app.db import SessionLocal
    parser = argparse.ArgumentParser(); parser.add_argument("--sport", choices=("football", "basketball"), required=True)
    args = parser.parse_args()
    with SessionLocal() as db: print(audit(db, args.sport))
