import json
import logging
from dataclasses import dataclass
from time import monotonic
from typing import Any

import redis

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    value: Any
    expires_at: float


class MemoryCache:
    def __init__(self) -> None:
        self._items: dict[str, CacheEntry] = {}

    def get(self, key: str) -> Any | None:
        item = self._items.get(key)
        if not item:
            return None
        if item.expires_at <= monotonic():
            self._items.pop(key, None)
            return None
        return item.value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self._items[key] = CacheEntry(value, monotonic() + ttl_seconds)

    def clear(self) -> None:
        self._items.clear()

    def acquire_lock(self, key: str, ttl_seconds: int) -> bool:
        if self.get(key) is not None:
            return False
        self.set(key, "locked", ttl_seconds)
        return True

    def close(self) -> None:
        self.clear()


class RedisCache:
    def __init__(self, url: str, *, client: Any | None = None, fallback: MemoryCache | None = None, required: bool = False, namespace: str = "slipiq") -> None:
        self.fallback = fallback or MemoryCache()
        self.namespace = namespace.strip(":")
        self.required = required
        try:
            self.client = client or redis.Redis.from_url(url, decode_responses=True)
        except (redis.RedisError, ValueError) as exc:
            if required:
                raise RuntimeError("Redis configuration is invalid") from exc
            logger.warning("redis cache configuration invalid; using memory fallback: %s", exc)
            self.client = None
        self.available = False
        if self.client is None:
            return
        try:
            self.client.ping()
            self.available = True
        except redis.RedisError as exc:
            if required:
                raise RuntimeError("Redis is required but unavailable") from exc
            logger.warning("redis cache unavailable; using memory fallback: %s", exc)

    def _key(self, key: str) -> str:
        return f"{self.namespace}:{key}"

    def get(self, key: str) -> Any | None:
        if not self.available:
            return self.fallback.get(key)
        try:
            raw = self.client.get(self._key(key))
            return json.loads(raw) if raw is not None else None
        except (redis.RedisError, TypeError, ValueError) as exc:
            if self.required:
                raise RuntimeError("Redis cache read failed") from exc
            logger.warning("redis cache read failed; using memory fallback: %s", exc)
            self.available = False
            return self.fallback.get(key)

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        if not self.available:
            self.fallback.set(key, value, ttl_seconds)
            return
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            self.client.setex(self._key(key), ttl_seconds, encoded)
        except (redis.RedisError, TypeError, ValueError) as exc:
            if self.required:
                raise RuntimeError("Redis cache write failed") from exc
            logger.warning("redis cache write failed; using memory fallback: %s", exc)
            self.available = False
            self.fallback.set(key, value, ttl_seconds)

    def acquire_lock(self, key: str, ttl_seconds: int) -> bool:
        if not self.available:
            return self.fallback.acquire_lock(key, ttl_seconds)
        try:
            return bool(self.client.set(self._key(key), "locked", ex=ttl_seconds, nx=True))
        except redis.RedisError as exc:
            if self.required:
                raise RuntimeError("Redis lock unavailable") from exc
            self.available = False
            return self.fallback.acquire_lock(key, ttl_seconds)

    def close(self) -> None:
        if self.client is not None:
            self.client.close()


class CacheBackend:
    def __init__(self, redis_url: str | None = None, *, required: bool = False, namespace: str = "slipiq") -> None:
        self.memory = MemoryCache()
        if required and not redis_url:
            raise RuntimeError("Redis is required but REDIS_URL is missing")
        self.backend: RedisCache | MemoryCache = RedisCache(redis_url, fallback=self.memory, required=required, namespace=namespace) if redis_url else self.memory

    def get(self, key: str) -> Any | None:
        return self.backend.get(key)

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self.backend.set(key, value, ttl_seconds)

    @property
    def available(self) -> bool:
        return isinstance(self.backend, RedisCache) and self.backend.available

    @property
    def degraded(self) -> bool:
        return not self.available

    def acquire_lock(self, key: str, ttl_seconds: int) -> bool:
        return self.backend.acquire_lock(key, ttl_seconds)

    def close(self) -> None:
        self.backend.close()


cache = CacheBackend()
