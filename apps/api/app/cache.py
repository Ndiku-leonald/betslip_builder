from dataclasses import dataclass
from time import monotonic
from typing import Any


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


class CacheBackend:
    def __init__(self) -> None:
        self.memory = MemoryCache()

    def get(self, key: str) -> Any | None:
        return self.memory.get(key)

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        self.memory.set(key, value, ttl_seconds)


cache = CacheBackend()

