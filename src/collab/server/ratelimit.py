"""Lightweight stdlib rate limiters for authentication, registration, and chat."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True)
class _BucketState:
    tokens: float
    updated_at: float


class TokenBucketLimiter:
    """Thread-safe keyed token-bucket rate limiter using immutable state entries."""

    def __init__(self, *, rate: float, burst: int) -> None:
        self.rate = max(0.01, float(rate))
        self.burst = max(1, int(burst))
        self._lock = threading.Lock()
        self._buckets: dict[str, _BucketState] = {}

    def allow(self, key: str, cost: float = 1.0) -> bool:
        now = time.monotonic()
        with self._lock:
            prev = self._buckets.get(key)
            if prev is None:
                available = float(self.burst)
            else:
                elapsed = max(0.0, now - prev.updated_at)
                available = min(float(self.burst), prev.tokens + elapsed * self.rate)
            if available < cost:
                self._buckets[key] = _BucketState(tokens=available, updated_at=now)
                return False
            self._buckets[key] = _BucketState(tokens=available - cost, updated_at=now)
            return True

    def remove(self, key: str) -> None:
        with self._lock:
            self._buckets.pop(key, None)


class SlidingWindowLimiter:
    """Thread-safe per-key sliding-window counter using immutable timestamp tuples."""

    def __init__(self, *, limit: int, window_sec: float = 60.0, max_keys: int = 4096) -> None:
        self.limit = max(1, int(limit))
        self.window_sec = max(0.1, float(window_sec))
        self.max_keys = max(16, int(max_keys))
        self._lock = threading.Lock()
        self._events: dict[str, tuple[float, ...]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_sec
        with self._lock:
            if key not in self._events and len(self._events) >= self.max_keys:
                self._prune_stale(cutoff)
            recent = tuple(ts for ts in self._events.get(key, ()) if ts >= cutoff)
            if len(recent) >= self.limit:
                self._events[key] = recent
                return False
            self._events[key] = (*recent, now)
            return True

    def _prune_stale(self, cutoff: float) -> None:
        stale_keys = [
            k for k, stamps in self._events.items() if not stamps or stamps[-1] < cutoff
        ]
        for k in stale_keys:
            self._events.pop(k, None)
