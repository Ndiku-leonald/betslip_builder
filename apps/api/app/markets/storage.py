from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OddsSnapshot, ProviderObservation
from app.odds.ontology import NormalizedMarket


def persist_market_snapshots(db: Session, markets: list[NormalizedMarket]) -> int:
    """Append normalized snapshots; never overwrite a prior observation."""
    for market in markets:
        db.add(OddsSnapshot(fixture_id=market.fixture_id, provider=market.provider, bookmaker=market.bookmaker, source_event_id=market.source_event_id, market_family=market.market_family, market_type=market.market_type, period=market.period, participant=market.participant, selection=market.selection, line=market.line, decimal_odds=market.decimal_odds, market_status=market.status, settlement_semantics=market.settlement_semantics, observed_at=market.observed_at, provider_updated_at=market.provider_updated_at, payload=market.raw or {}))
    db.commit()
    return len(markets)


def market_identity(market: OddsSnapshot | NormalizedMarket) -> tuple:
    """Identity for one current selection, excluding observation timestamps."""
    return (market.provider, market.bookmaker, market.fixture_id, market.market_family, market.market_type, market.period, market.participant, market.selection, market.line, market.settlement_semantics)


def latest_market_snapshots(db: Session, fixture_id: str | None = None, limit: int = 1000) -> list[OddsSnapshot]:
    """Return one newest observation for each canonical market selection."""
    query = select(OddsSnapshot).order_by(OddsSnapshot.observed_at.desc(), OddsSnapshot.created_at.desc())
    if fixture_id is not None: query = query.where(OddsSnapshot.fixture_id == fixture_id)
    result = []
    seen = set()
    for item in db.scalars(query):
        key = market_identity(item)
        if key in seen: continue
        seen.add(key); result.append(item)
        if len(result) >= limit: break
    return result


def market_snapshot_history(db: Session, fixture_id: str | None = None, limit: int = 5000) -> list[OddsSnapshot]:
    """Return all retained observations in chronological order for movement views."""
    query = select(OddsSnapshot).order_by(OddsSnapshot.observed_at.asc(), OddsSnapshot.created_at.asc()).limit(limit)
    if fixture_id is not None: query = query.where(OddsSnapshot.fixture_id == fixture_id)
    return list(db.scalars(query))


def _observation_value(item, field, default=None):
    if isinstance(item, dict): return item.get(field, default)
    return getattr(item, field, default)


def persist_provider_observation(db: Session, fixture_id: str, observation, *, canonical_home_team: str | None = None, canonical_away_team: str | None = None) -> ProviderObservation:
    row = ProviderObservation(fixture_id=fixture_id, provider=_observation_value(observation, "provider", "unknown"), source_event_id=_observation_value(observation, "source_event_id") or _observation_value(observation, "provider_fixture_id"), observed_at=_observation_value(observation, "observed_at") or datetime.now(timezone.utc), provider_updated_at=_observation_value(observation, "provider_updated_at"), kickoff_at=_observation_value(observation, "kickoff_at"), status=_observation_value(observation, "status"), home_score=_observation_value(observation, "home_score"), away_score=_observation_value(observation, "away_score"), clock=_observation_value(observation, "clock"), period=_observation_value(observation, "period"), canonical_home_team=canonical_home_team or _observation_value(observation, "home_name") or _observation_value(observation, "canonical_home_team"), canonical_away_team=canonical_away_team or _observation_value(observation, "away_name") or _observation_value(observation, "canonical_away_team"), payload=_observation_value(observation, "raw", {}) or _observation_value(observation, "payload", {}) or {})
    db.add(row); db.commit(); return row


def latest_provider_observations(db: Session, fixture_id: str, limit: int = 10, max_age_seconds: int | None = 86400) -> list[ProviderObservation]:
    query = select(ProviderObservation).where(ProviderObservation.fixture_id == fixture_id).order_by(ProviderObservation.observed_at.desc(), ProviderObservation.created_at.desc()).limit(limit)
    latest = {}; result = []
    for item in db.scalars(query):
        if max_age_seconds is not None and item.observed_at is not None:
            observed = item.observed_at.replace(tzinfo=timezone.utc) if item.observed_at.tzinfo is None else item.observed_at
            if (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds() > max_age_seconds: continue
        if item.provider in latest: continue
        latest[item.provider] = item; result.append(item)
    return result
