from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class QuotaManager:
    mode: str = "free"
    daily_limits: dict[str, int] = field(default_factory=dict)
    calls: dict[str, list[datetime]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        defaults = {"api-football": 100, "api-basketball": 100} if self.mode == "free" else {}
        defaults.update(self.daily_limits)
        self.daily_limits = {provider: limit for provider, limit in defaults.items() if limit > 0}

    def allow(self, provider: str) -> bool:
        limit = self.daily_limits.get(provider)
        if not limit:
            return True
        today = datetime.now(timezone.utc).date()
        current = [stamp for stamp in self.calls.get(provider, []) if stamp.date() == today]
        self.calls[provider] = current
        return len(current) < limit

    def record(self, provider: str) -> None:
        self.calls.setdefault(provider, []).append(datetime.now(timezone.utc))

    def calls_today(self, provider: str) -> int:
        self.allow(provider)
        return len(self.calls.get(provider, []))
