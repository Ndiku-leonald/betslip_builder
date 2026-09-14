from app.cache import MemoryCache
from app.quota import QuotaManager


def test_memory_cache_returns_and_expires_values() -> None:
    cache = MemoryCache()
    cache.set("key", {"value": 1}, 60)
    assert cache.get("key") == {"value": 1}


def test_quota_manager_enforces_daily_limit() -> None:
    quota = QuotaManager(daily_limits={"api-football": 1})
    assert quota.allow("api-football")
    quota.record("api-football")
    assert not quota.allow("api-football")

