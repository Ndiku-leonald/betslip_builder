from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Freshness(StrEnum):
    LIVE_CURRENT = "LIVE_CURRENT"
    RECENT = "RECENT"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class FixtureStatus(StrEnum):
    SCHEDULED = "scheduled"
    LIVE = "live"
    HALFTIME = "halftime"
    FINISHED = "finished"
    POSTPONED = "postponed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Sport(TimestampMixin, Base):
    __tablename__ = "sports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))


class Country(TimestampMixin, Base):
    __tablename__ = "countries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str | None] = mapped_column(String(8))


class Competition(TimestampMixin, Base):
    __tablename__ = "competitions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sport_id: Mapped[str] = mapped_column(ForeignKey("sports.id"), index=True)
    country_id: Mapped[str | None] = mapped_column(ForeignKey("countries.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    provider_id: Mapped[str | None] = mapped_column(String(80))


class Season(TimestampMixin, Base):
    __tablename__ = "seasons"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    competition_id: Mapped[str] = mapped_column(ForeignKey("competitions.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    provider_id: Mapped[str | None] = mapped_column(String(80))


class Team(TimestampMixin, Base):
    __tablename__ = "teams"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sport_id: Mapped[str] = mapped_column(ForeignKey("sports.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    short_name: Mapped[str | None] = mapped_column(String(80))
    logo_url: Mapped[str | None] = mapped_column(String(500))


class Player(TimestampMixin, Base):
    __tablename__ = "players"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sport_id: Mapped[str] = mapped_column(ForeignKey("sports.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))


class Venue(TimestampMixin, Base):
    __tablename__ = "venues"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(120))


class Fixture(TimestampMixin, Base):
    __tablename__ = "fixtures"
    __table_args__ = (UniqueConstraint("sport_id", "provider", "provider_fixture_id", name="uq_fixture_provider"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sport_id: Mapped[str] = mapped_column(ForeignKey("sports.id"), index=True)
    competition_id: Mapped[str | None] = mapped_column(ForeignKey("competitions.id"), nullable=True, index=True)
    season_id: Mapped[str | None] = mapped_column(ForeignKey("seasons.id"), nullable=True)
    home_team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    venue_id: Mapped[str | None] = mapped_column(ForeignKey("venues.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(60), index=True)
    provider_fixture_id: Mapped[str] = mapped_column(String(100), index=True)
    kickoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default=FixtureStatus.UNKNOWN.value, index=True)
    status_detail: Mapped[str | None] = mapped_column(String(80))
    home_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    away_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    period: Mapped[str | None] = mapped_column(String(40))
    clock: Mapped[str | None] = mapped_column(String(40))
    # Kept for compatibility with the immutable Phase 1 migration. It is no longer
    # used for freshness; kickoff_at is never an observation timestamp.
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    freshness: Mapped[str] = mapped_column(String(30), default=Freshness.UNKNOWN.value)


class ProviderEntityMapping(Base):
    __tablename__ = "provider_entity_mappings"
    __table_args__ = (UniqueConstraint("provider", "entity_type", "provider_entity_id", name="uq_provider_entity"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    provider_entity_id: Mapped[str] = mapped_column(String(100))
    internal_entity_id: Mapped[str] = mapped_column(String(36), index=True)


class MatchEvent(TimestampMixin, Base):
    __tablename__ = "match_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    fixture_id: Mapped[str] = mapped_column(ForeignKey("fixtures.id"), index=True)
    provider_event_id: Mapped[str | None] = mapped_column(String(100))
    minute: Mapped[int | None] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class MatchStatSnapshot(TimestampMixin, Base):
    __tablename__ = "match_stat_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    fixture_id: Mapped[str] = mapped_column(ForeignKey("fixtures.id"), index=True)
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    freshness: Mapped[str] = mapped_column(String(30), default=Freshness.UNKNOWN.value)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Lineup(TimestampMixin, Base):
    __tablename__ = "lineups"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    fixture_id: Mapped[str] = mapped_column(ForeignKey("fixtures.id"), index=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SimpleFixturePayload(TimestampMixin, Base):
    __abstract__ = True
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    fixture_id: Mapped[str] = mapped_column(ForeignKey("fixtures.id"), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Injury(SimpleFixturePayload):
    __tablename__ = "injuries"


class StandingSnapshot(SimpleFixturePayload):
    __tablename__ = "standings_snapshots"


class TeamFormSnapshot(SimpleFixturePayload):
    __tablename__ = "team_form_snapshots"


class WeatherSnapshot(SimpleFixturePayload):
    __tablename__ = "weather_snapshots"


class Market(TimestampMixin, Base):
    __tablename__ = "markets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    sport_id: Mapped[str] = mapped_column(ForeignKey("sports.id"))
    key: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(160))


class MarketSelection(TimestampMixin, Base):
    __tablename__ = "market_selections"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    market_id: Mapped[str] = mapped_column(ForeignKey("markets.id"))
    fixture_id: Mapped[str] = mapped_column(ForeignKey("fixtures.id"))
    label: Mapped[str] = mapped_column(String(160))


class OddsSnapshot(TimestampMixin, Base):
    __tablename__ = "odds_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    fixture_id: Mapped[str] = mapped_column(ForeignKey("fixtures.id"), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    provider: Mapped[str] = mapped_column(String(60))


class ProviderUsage(TimestampMixin, Base):
    __tablename__ = "provider_usage"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(60), index=True)
    endpoint: Mapped[str] = mapped_column(String(200))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    external_request: Mapped[bool] = mapped_column(Boolean, default=True)
    rate_limit_remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProviderHealth(TimestampMixin, Base):
    __tablename__ = "provider_health"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(60), unique=True)
    configured: Mapped[bool] = mapped_column(Boolean, default=False)
    healthy: Mapped[bool] = mapped_column(Boolean, default=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    calls_today: Mapped[int] = mapped_column(Integer, default=0)


class DataConflict(TimestampMixin, Base):
    __tablename__ = "data_conflicts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str] = mapped_column(String(36))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ModelVersion(TimestampMixin, Base):
    __tablename__ = "model_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    version: Mapped[str] = mapped_column(String(80))


class Prediction(TimestampMixin, Base):
    __tablename__ = "predictions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    fixture_id: Mapped[str] = mapped_column(ForeignKey("fixtures.id"), index=True)
    model_version_id: Mapped[str | None] = mapped_column(ForeignKey("model_versions.id"), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Slip(TimestampMixin, Base):
    __tablename__ = "slips"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    risk: Mapped[str] = mapped_column(String(30))
    target_odds: Mapped[float | None] = mapped_column(Float, nullable=True)


class SlipLeg(Base):
    __tablename__ = "slip_legs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slip_id: Mapped[str] = mapped_column(ForeignKey("slips.id"), index=True)
    market_selection_id: Mapped[str] = mapped_column(ForeignKey("market_selections.id"))
