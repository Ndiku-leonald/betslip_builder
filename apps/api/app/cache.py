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


class RedisCache:
    def __init__(self, url: str, *, client: Any | None = None, fallback: MemoryCache | None = None) -> None:
        self.fallback = fallback or MemoryCache()
        try:
            self.client = client or redis.Redis.from_url(url, decode_responses=True)
        except (redis.RedisError, ValueError) as exc:
            logger.warning("redis cache configuration invalid; using memory fallback: %s", exc)
            self.client = None
        self.available = False
        if self.client is None:
            return
        try:
            self.client.ping()
            self.available = True
        except redis.RedisError as exc:
            logger.warning("redis cache unavailable; using memory fallback: %s", exc)

    def get(self, key: str) -> Any | None:
        if not self.available:
            return self.fallback.get(key)
        try:
            raw = self.client.get(key)
            return json.loads(raw) if raw is not None else None
        except (redis.RedisError, TypeError, ValueError) as exc:
            logger.warning("redis cache read failed; using memory fallback: %s", exc)
            self.available = False
            return self.fallback.get(key)

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        if not self.available:
            self.fallback.set(key, value, ttl_seconds)
            return
        try:
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            self.client.setex(key, ttl_seconds, encoded)
        except (redis.RedisError, TypeError, ValueError) as exc:
            logger.warning("redis cache write failed; using memory fallback: %s", exc)
            self.available = False
            self.fallback.set(key, value, ttl_seconds)


class CacheBackend:
    def __init__(self, redis_url: str | None = None) -> None:
        self.memory = MemoryCache()
        self.backend: RedisCache | MemoryCache = RedisCache(redis_url, fallback=self.memory) if redis_url else self.memory

    def get(self, key: str) -> Any | None:
        return self.backend.get(key)

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self.backend.set(key, value, ttl_seconds)


cache = CacheBackend()
