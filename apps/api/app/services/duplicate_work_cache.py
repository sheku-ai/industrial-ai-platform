from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from threading import Condition, RLock
from time import monotonic
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class DuplicateWorkResult[T]:
    value: T
    cache_hit: bool
    shared_inflight: bool


class BoundedDuplicateWorkCache[T]:
    """Bounded process-local cache with one computation per active key."""

    def __init__(self, *, max_entries: int = 128, ttl_seconds: float = 300.0) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be greater than zero")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be greater than zero")
        self.max_entries = max_entries
        self.ttl_seconds = ttl_seconds
        self._entries: OrderedDict[str, tuple[float, T]] = OrderedDict()
        self._active_keys: set[str] = set()
        self._condition = Condition(RLock())
        self._hits = 0
        self._misses = 0
        self._shared = 0
        self._evictions = 0

    def get_or_compute(self, key: str, compute: Callable[[], T]) -> DuplicateWorkResult[T]:
        canonical_key = key.strip() if isinstance(key, str) else ""
        if not canonical_key:
            raise ValueError("key is required")
        if not callable(compute):
            raise ValueError("compute is required")

        with self._condition:
            cached = self._get_live(canonical_key)
            if cached is not None:
                self._hits += 1
                return DuplicateWorkResult(deepcopy(cached), True, False)

            while canonical_key in self._active_keys:
                self._condition.wait()
                cached = self._get_live(canonical_key)
                if cached is not None:
                    self._hits += 1
                    self._shared += 1
                    return DuplicateWorkResult(deepcopy(cached), True, True)

            self._misses += 1
            self._active_keys.add(canonical_key)

        try:
            value = compute()
        except Exception:
            with self._condition:
                self._active_keys.discard(canonical_key)
                self._condition.notify_all()
            raise

        with self._condition:
            self._entries[canonical_key] = (
                monotonic() + self.ttl_seconds,
                deepcopy(value),
            )
            self._entries.move_to_end(canonical_key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
                self._evictions += 1
            self._active_keys.discard(canonical_key)
            self._condition.notify_all()

        return DuplicateWorkResult(deepcopy(value), False, False)

    def metrics(self) -> dict[str, int]:
        with self._condition:
            self._purge_expired()
            return {
                "duplicate_cache_entries": len(self._entries),
                "duplicate_cache_hits": self._hits,
                "duplicate_cache_misses": self._misses,
                "duplicate_cache_shared_active": self._shared,
                "duplicate_cache_evictions": self._evictions,
                "duplicate_cache_active": len(self._active_keys),
            }

    def _get_live(self, key: str) -> T | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= monotonic():
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return value

    def _purge_expired(self) -> None:
        now = monotonic()
        expired = [key for key, (expires_at, _) in self._entries.items() if expires_at <= now]
        for key in expired:
            del self._entries[key]
