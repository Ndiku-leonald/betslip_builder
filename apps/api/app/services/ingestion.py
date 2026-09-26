import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.freshness import classify_freshness
from app.live.persistence import persist_live_match_snapshot
from app.live.state import normalize_basketball_live_state, normalize_football_live_state
from app.models import Competition, Country, Fixture, ProviderEntityMapping, Season, Sport, Team
from app.providers.base import NormalizedFixture

logger = logging.getLogger(__name__)


def _get_or_create(db: Session, model, filters: dict, values: dict):
    item = db.scalar(select(model).filter_by(**filters))
    if item is None:
        item = model(**filters, **values)
        db.add(item)
        db.flush()
    else:
        for key, value in values.items():
            setattr(item, key, value)
    return item


def _mapping(db: Session, provider: str, entity_type: str, provider_id: str, internal_id: str) -> None:
    item = db.scalar(select(ProviderEntityMapping).filter_by(provider=provider, entity_type=entity_type, provider_entity_id=provider_id))
    if item is None:
        db.add(ProviderEntityMapping(provider=provider, entity_type=entity_type, provider_entity_id=provider_id, internal_entity_id=internal_id))
    elif item.internal_entity_id != internal_id:
        logger.warning("provider entity remapped provider=%s type=%s id=%s", provider, entity_type, provider_id)
        item.internal_entity_id = internal_id


def ingest_fixtures(db: Session, items: list[NormalizedFixture]) -> int:
    for item in items:
        observed_at = item.observed_at or datetime.now(timezone.utc)
        sport = _get_or_create(db, Sport, {"slug": item.sport}, {"name": item.sport.title()})
        country = None
        if item.country_name:
            country = _get_or_create(db, Country, {"name": item.country_name}, {"code": None})
        competition_filters = {"sport_id": sport.id, "name": item.competition_name}
        if item.competition_provider_id:
            competition_filters["provider_id"] = item.competition_provider_id
        competition_values = {"country_id": country.id if country else None}
        if "provider_id" not in competition_filters:
            competition_values["provider_id"] = item.competition_provider_id
        competition = _get_or_create(db, Competition, competition_filters, competition_values)
        season = None
        if item.season_name:
            season = _get_or_create(
                db,
                Season,
                {"competition_id": competition.id, "name": item.season_name},
                {"provider_id": item.season_name},
            )
        home = _get_or_create(db, Team, {"sport_id": sport.id, "name": item.home_name}, {"short_name": None, "logo_url": None})
        away = _get_or_create(db, Team, {"sport_id": sport.id, "name": item.away_name}, {"short_name": None, "logo_url": None})
        _mapping(db, item.provider, "team", item.home_provider_id, home.id)
        _mapping(db, item.provider, "team", item.away_provider_id, away.id)
        _mapping(db, item.provider, "competition", item.competition_provider_id or item.competition_name, competition.id)
        fixture = db.scalar(select(Fixture).filter_by(sport_id=sport.id, provider=item.provider, provider_fixture_id=item.provider_fixture_id))
        values = {
            "competition_id": competition.id, "season_id": season.id if season else None, "home_team_id": home.id, "away_team_id": away.id,
            "kickoff_at": item.kickoff_at, "status": item.status, "status_detail": item.status_detail,
            "home_score": item.home_score, "away_score": item.away_score, "period": item.period, "clock": item.clock,
            "provider_timestamp": None, "observed_at": observed_at,
            "provider_updated_at": item.provider_updated_at, "ingested_at": datetime.now(timezone.utc),
            "freshness": classify_freshness(status=item.status, observed_at=observed_at, provider_updated_at=item.provider_updated_at).value,
        }
        if fixture is None:
            fixture = Fixture(sport_id=sport.id, provider=item.provider, provider_fixture_id=item.provider_fixture_id, **values)
            db.add(fixture)
            db.flush()
        else:
            for key, value in values.items():
                setattr(fixture, key, value)
        _mapping(db, item.provider, "fixture", item.provider_fixture_id, fixture.id)
        if item.status in {"live", "halftime"}:
            state = normalize_football_live_state(item, fixture_id=fixture.id) if item.sport == "football" else normalize_basketball_live_state(item, fixture_id=fixture.id)
            persist_live_match_snapshot(db, state)
    db.commit()
    return len(items)
