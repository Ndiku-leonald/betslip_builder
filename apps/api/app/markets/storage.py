from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OddsSnapshot
from app.odds.ontology import NormalizedMarket


def persist_market_snapshots(db: Session, markets: list[NormalizedMarket]) -> int:
    """Append normalized snapshots; never overwrite a prior observation."""
    for market in markets:
        db.add(OddsSnapshot(fixture_id=market.fixture_id, provider=market.provider, bookmaker=market.bookmaker, source_event_id=market.source_event_id, market_family=market.market_family, market_type=market.market_type, period=market.period, selection=market.selection, line=market.line, decimal_odds=market.decimal_odds, market_status=market.status, settlement_semantics=market.settlement_semantics, observed_at=market.observed_at, provider_updated_at=market.provider_updated_at, payload=market.raw or {}))
    db.commit()
    return len(markets)


def latest_market_snapshots(db: Session, fixture_id: str | None = None, limit: int = 1000) -> list[OddsSnapshot]:
    query = select(OddsSnapshot).order_by(OddsSnapshot.observed_at.desc(), OddsSnapshot.created_at.desc()).limit(limit)
    if fixture_id is not None: query = query.where(OddsSnapshot.fixture_id == fixture_id)
    return list(db.scalars(query))
