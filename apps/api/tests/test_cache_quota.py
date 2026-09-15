from datetime import datetime, timedelta, timezone

import pytest
import redis

from app.cache import MemoryCache, RedisCache
from app.config import Settings
from app.providers.api_sports import ApiSportsProvider, ProviderError
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


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def ping(self) -> bool:
        return True

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value

    def get(self, key: str) -> str | None:
        return self.values.get(key)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict, remaining: str = "97") -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = {"x-ratelimit-requests-remaining": remaining}

    def json(self) -> dict:
        return self._payload


def test_redis_cache_serializes_json_and_falls_back() -> None:
    fake = FakeRedis()
    cache = RedisCache("redis://unused", client=fake)
    cache.set("key", {"value": 1}, 60)
    assert cache.get("key") == {"value": 1}

    class BrokenRedis(FakeRedis):
        def ping(self) -> bool:
            raise redis.RedisError("offline")

    fallback = RedisCache("redis://unused", client=BrokenRedis())
    fallback.set("key", {"value": 2}, 60)
    assert fallback.get("key") == {"value": 2}


def test_quota_manager_uses_utc_reset_and_settings_overrides() -> None:
    quota = QuotaManager(daily_limits={"api-football": 1})
    quota.calls["api-football"] = [datetime.now(timezone.utc) - timedelta(days=1)]
    assert quota.allow("api-football")
    quota.record("api-football")
    assert not quota.allow("api-football")
    assert Settings(quota_mode="free").provider_daily_limits["api-football"] == 100
    assert Settings(quota_mode="free", api_football_daily_limit=7).provider_daily_limits["api-football"] == 7


@pytest.mark.asyncio
async def test_provider_retries_consume_quota_and_cache_hits_do_not(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.providers.api_sports as provider_module

    payload = {"response": [{"fixture": {"id": 1, "date": "2026-09-15T16:00:00+00:00", "status": {"short": "NS"}}, "league": {"id": 1, "name": "Test"}, "teams": {"home": {"id": 1, "name": "Home"}, "away": {"id": 2, "name": "Away"}}, "goals": {"home": None, "away": None}}]}
    responses = [FakeResponse(500, {}), FakeResponse(500, {}), FakeResponse(200, payload)]

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            return responses.pop(0)

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(provider_module.asyncio, "sleep", no_sleep)
    quota = QuotaManager(daily_limits={"api-football": 3})
    provider = ApiSportsProvider(name="api-football", key="configured", base_url="http://test", cache=MemoryCache(), quota=quota)
    assert len(await provider.fixtures_by_date("2026-09-15")) == 1
    assert quota.calls_today("api-football") == 3
    assert len(provider.last_request_events) == 3
    assert len(await provider.fixtures_by_date("2026-09-15")) == 1
    assert quota.calls_today("api-football") == 3
    assert provider.last_cache_hit is True
    assert provider.last_rate_limit_remaining is None
    assert provider.last_error is None
    assert provider.last_latency_ms == 0.0
    with pytest.raises(ProviderError):
        await provider.fixtures_by_date("2026-09-16")
    assert quota.calls_today("api-football") == 3
