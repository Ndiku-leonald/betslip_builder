from datetime import datetime, timezone

from app.models import Freshness


def newest_observation_at(observed_at: datetime | None, provider_updated_at: datetime | None = None) -> datetime | None:
    # A local fetch/ingestion timestamp is not evidence that the upstream
    # observation changed. Prefer the provider timestamp whenever supplied.
    value = provider_updated_at if provider_updated_at is not None else observed_at
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def data_age_seconds(observed_at: datetime | None, provider_updated_at: datetime | None = None, now: datetime | None = None) -> int | None:
    observation = newest_observation_at(observed_at, provider_updated_at)
    if observation is None:
        return None
    current = now or datetime.now(timezone.utc)
    return max(0, int((current - observation).total_seconds()))


def classify_freshness(*, status: str, observed_at: datetime | None, provider_updated_at: datetime | None = None, now: datetime | None = None) -> Freshness:
    age = data_age_seconds(observed_at, provider_updated_at, now)
    if age is None:
        return Freshness.UNKNOWN
    if status in {"live", "halftime"}:
        return Freshness.LIVE_CURRENT if age <= 90 else Freshness.STALE
    if age <= 900:
        return Freshness.RECENT
    return Freshness.STALE
