from datetime import datetime, timezone

from app.models import Freshness


def data_age_seconds(provider_timestamp: datetime | None, now: datetime | None = None) -> int | None:
    if provider_timestamp is None:
        return None
    current = now or datetime.now(timezone.utc)
    value = provider_timestamp
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return max(0, int((current - value).total_seconds()))


def classify_freshness(*, status: str, provider_timestamp: datetime | None, now: datetime | None = None) -> Freshness:
    age = data_age_seconds(provider_timestamp, now)
    if age is None:
        return Freshness.UNKNOWN
    if status in {"live", "halftime"} and age <= 90:
        return Freshness.LIVE_CURRENT
    if age <= 900:
        return Freshness.RECENT
    return Freshness.STALE

