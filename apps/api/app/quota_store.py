"""Persistent provider quota reservations backed by ProviderUsage."""

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from app.models import ProviderUsage


def _utc_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


class PersistentQuotaStore:
    """Repository injected into QuotaManager; provider code stays SQLAlchemy-free."""

    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    def count_today(self, provider: str, day: date) -> int:
        start, end = _utc_bounds(day)
        with self.session_factory() as db:
            return int(db.scalar(select(func.count(ProviderUsage.id)).where(ProviderUsage.provider == provider, ProviderUsage.requested_at >= start, ProviderUsage.requested_at < end, ProviderUsage.external_request.is_(True), ProviderUsage.cache_hit.is_(False))) or 0)

    def reserve(self, provider: str, endpoint: str, limit: int) -> Any | None:
        today = datetime.now(timezone.utc).date()
        with self.session_factory() as db:
            start, end = _utc_bounds(today)
            count = db.scalar(select(func.count(ProviderUsage.id)).where(ProviderUsage.provider == provider, ProviderUsage.requested_at >= start, ProviderUsage.requested_at < end, ProviderUsage.external_request.is_(True), ProviderUsage.cache_hit.is_(False))) or 0
            if count >= limit:
                return None
            row = ProviderUsage(provider=provider, endpoint=endpoint, requested_at=datetime.now(timezone.utc), status_code=None, latency_ms=None, cache_hit=False, external_request=True, rate_limit_remaining=None, error=None)
            db.add(row)
            db.flush()
            token = row.id
            db.commit()
            return token

    def complete(self, token: Any, status_code: int | None, latency_ms: float | None, rate_limit_remaining: int | None, error: str | None) -> None:
        with self.session_factory() as db:
            row = db.get(ProviderUsage, token)
            if row is None:
                return
            row.status_code = status_code
            row.latency_ms = latency_ms
            row.rate_limit_remaining = rate_limit_remaining
            row.error = error
            db.commit()
