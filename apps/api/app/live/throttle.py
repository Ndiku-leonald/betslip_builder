from __future__ import annotations

from datetime import datetime, timezone


def refresh_key(provider: str, fixture_id: str) -> str:
    return f"live-refresh:{provider}:{fixture_id}"


def claim_refresh(cache, provider: str, fixture_id: str, cooldown_seconds: int) -> tuple[bool, int]:
    """Atomically-ish claim a local/Redis cooldown key for manual refreshes."""
    key = refresh_key(provider, fixture_id)
    if cache.get(key) is not None:
        return False, cooldown_seconds
    cache.set(key, datetime.now(timezone.utc).isoformat(), cooldown_seconds)
    return True, 0
