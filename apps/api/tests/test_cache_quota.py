from datetime import datetime, timedelta, timezone

import pytest
import redis
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.cache import MemoryCache, RedisCache
from app.config import Settings
from app.models import ProviderUsage
from app.providers.api_sports import ApiSportsProvider, ProviderError
from app.quota import QuotaManager
from app.quota_store import PersistentQuotaStore


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


def _quota_store() -> tuple[object, PersistentQuotaStore]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine, PersistentQuotaStore(lambda: Session(engine))


def _usage(provider: str, stamp: datetime, *, cache_hit: bool = False, external_request: bool = True) -> ProviderUsage:
    return ProviderUsage(provider=provider, endpoint="fixtures", requested_at=stamp, status_code=200, cache_hit=cache_hit, external_request=external_request)


def _persistent_manager(store: PersistentQuotaStore, limit: int = 100, provider: str = "api-football") -> QuotaManager:
    return QuotaManager(daily_limits={provider: limit}, count_callback=store.count_today, reserve_callback=store.reserve, complete_callback=store.complete)


def test_persistent_quota_survives_fresh_manager_and_ignores_non_network_rows() -> None:
    engine, store = _quota_store()
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        db.add_all([_usage("api-football", now), _usage("api-football", now, cache_hit=True), _usage("api-football", now, external_request=False)])
        db.commit()
    first = _persistent_manager(store)
    second = _persistent_manager(store)
    assert first.calls_today("api-football") == 1
    assert second.calls_today("api-football") == 1


def test_persistent_quota_blocks_request_101_after_restart() -> None:
    engine, store = _quota_store()
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        db.add_all([_usage("api-football", now) for _ in range(100)])
        db.commit()
    fresh = _persistent_manager(store)
    assert fresh.allow("api-football") is False
    assert fresh.reserve("api-football", "fixtures") is None


def test_persistent_quota_uses_utc_day_boundaries_and_override() -> None:
    engine, store = _quota_store()
    today = datetime.now(timezone.utc).date()
    start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    with Session(engine) as db:
        db.add_all([
            _usage("api-football", start - timedelta(microseconds=1)),
            _usage("api-football", start),
            *[_usage("api-football", start + timedelta(seconds=index + 1)) for index in range(6)],
        ])
        db.commit()
    assert store.count_today("api-football", today) == 7
    assert store.count_today("api-football", today - timedelta(days=1)) == 1
    fresh = _persistent_manager(store, limit=7)
    assert fresh.allow("api-football") is False


def test_provider_header_can_only_reduce_remaining_allowance() -> None:
    quota = QuotaManager(daily_limits={"api-football": 100})
    quota.observe_provider_remaining("api-football", 1)
    assert quota.reserve("api-football", "fixtures") is not None
    assert quota.reserve("api-football", "fixtures") is None


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


@pytest.mark.asyncio
async def test_persistent_quota_counts_each_retry_and_fresh_manager_sees_them(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.providers.api_sports as provider_module

    engine, store = _quota_store()
    payload = {"response": [{"game": {"id": 1, "date": "2026-09-15T16:00:00+00:00", "status": {"short": "NS"}}, "league": {"id": 1, "name": "Test"}, "teams": {"home": {"id": 1, "name": "Home"}, "away": {"id": 2, "name": "Away"}}, "scores": {"home": 0, "away": 0}}]}
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
    quota = _persistent_manager(store, limit=3, provider="api-basketball")
    provider = ApiSportsProvider(name="api-basketball", key="configured", base_url="http://test", cache=MemoryCache(), quota=quota)
    assert len(await provider.fixtures_by_date("2026-09-15")) == 1
    assert store.count_today("api-basketball", datetime.now(timezone.utc).date()) == 3
    assert _persistent_manager(store, limit=3, provider="api-basketball").allow("api-basketball") is False
    with Session(engine) as db:
        rows = list(db.scalars(select(ProviderUsage).where(ProviderUsage.provider == "api-basketball")))
    assert [row.status_code for row in rows] == [500, 500, 200]


def test_quota_block_does_not_create_external_request_row() -> None:
    engine, store = _quota_store()
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        db.add(_usage("api-football", now))
        db.commit()
    quota = _persistent_manager(store, limit=1)
    assert quota.reserve("api-football", "fixtures") is None
    with Session(engine) as db:
        rows = list(db.scalars(select(ProviderUsage).where(ProviderUsage.provider == "api-football")))
    assert len(rows) == 1
