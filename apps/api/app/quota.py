from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from threading import RLock
from typing import Any


CountCallback = Callable[[str, date], int]
ReserveCallback = Callable[[str, str, int], Any | None]
CompleteCallback = Callable[[Any, int | None, float | None, int | None, str | None], None]


@dataclass(frozen=True)
class QuotaReservation:
    token: Any | None = None
    persistent: bool = False


@dataclass
class QuotaManager:
    mode: str = "free"
    daily_limits: dict[str, int] = field(default_factory=dict)
    calls: dict[str, list[datetime]] = field(default_factory=dict)
    count_callback: CountCallback | None = None
    reserve_callback: ReserveCallback | None = None
    complete_callback: CompleteCallback | None = None
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)
    _reported_remaining: dict[str, tuple[date, int]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        defaults = {"api-football": 100, "api-basketball": 100} if self.mode == "free" else {}
        defaults.update(self.daily_limits)
        self.daily_limits = {provider: limit for provider, limit in defaults.items() if limit > 0}

    def allow(self, provider: str) -> bool:
        limit = self.daily_limits.get(provider)
        if not limit:
            return True
        with self._lock:
            today = datetime.now(timezone.utc).date()
            current = [stamp for stamp in self.calls.get(provider, []) if stamp.astimezone(timezone.utc).date() == today]
            self.calls[provider] = current
            reported = self._reported_remaining.get(provider)
            if reported and reported[0] == today and reported[1] <= 0:
                return False
            persisted = self.count_callback(provider, today) if self.count_callback else 0
            return persisted + (0 if self.reserve_callback else len(current)) < limit

    def reserve(self, provider: str, endpoint: str) -> QuotaReservation | None:
        """Reserve one real outbound attempt before network I/O.

        A persistent callback inserts the usage row atomically with its count
        check. Without one, the manager retains the original in-memory mode.
        """
        limit = self.daily_limits.get(provider)
        with self._lock:
            today = datetime.now(timezone.utc).date()
            reported = self._reported_remaining.get(provider)
            if limit and reported and reported[0] == today and reported[1] <= 0:
                return None
            if limit and not self.allow(provider):
                return None
            if self.reserve_callback and limit:
                token = self.reserve_callback(provider, endpoint, limit)
                if token is None:
                    return None
                self.consume_reported_remaining(provider)
                return QuotaReservation(token=token, persistent=True)
            self.consume_reported_remaining(provider)
            return QuotaReservation()

    def record(self, provider: str, reservation: QuotaReservation | None = None) -> None:
        if reservation and reservation.persistent:
            return
        with self._lock:
            self.calls.setdefault(provider, []).append(datetime.now(timezone.utc))

    def complete(self, provider: str, reservation: QuotaReservation | None, *, status_code: int | None, latency_ms: float | None, rate_limit_remaining: int | None, error: str | None = None) -> None:
        if reservation and reservation.persistent and self.complete_callback:
            self.complete_callback(reservation.token, status_code, latency_ms, rate_limit_remaining, error)
        self.observe_provider_remaining(provider, rate_limit_remaining)

    def observe_provider_remaining(self, provider: str, remaining: int | None) -> None:
        if remaining is None:
            return
        today = datetime.now(timezone.utc).date()
        with self._lock:
            previous = self._reported_remaining.get(provider)
            self._reported_remaining[provider] = (today, min(previous[1], remaining) if previous and previous[0] == today else remaining)

    def consume_reported_remaining(self, provider: str) -> None:
        today = datetime.now(timezone.utc).date()
        with self._lock:
            previous = self._reported_remaining.get(provider)
            if previous and previous[0] == today:
                self._reported_remaining[provider] = (today, max(0, previous[1] - 1))

    def calls_today(self, provider: str) -> int:
        limit = self.daily_limits.get(provider)
        if self.count_callback and limit:
            return self.count_callback(provider, datetime.now(timezone.utc).date())
        self.allow(provider)
        return len(self.calls.get(provider, []))
