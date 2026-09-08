"""In-process rate limiting for the API boundary (ADR 0004)."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RateLimitDecision:
    """Outcome of a single rate-limit check."""

    allowed: bool
    retry_after_seconds: float


class RateLimiter(Protocol):
    """Decides whether a request identified by `key` may proceed."""

    def check(self, key: str) -> RateLimitDecision: ...


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class InMemoryTokenBucketRateLimiter:
    """Single-process token-bucket limiter keyed by an opaque string.

    Not safe across multiple worker processes or instances. A distributed
    backend must implement the `RateLimiter` protocol to replace this for
    multi-instance deployments (see ADR 0004).
    """

    def __init__(
        self,
        *,
        capacity: int,
        requests_per_window: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if requests_per_window < 1:
            raise ValueError("requests_per_window must be >= 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be >= 1")
        self._capacity = float(capacity)
        self._refill_rate = requests_per_window / window_seconds
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}

    def check(self, key: str) -> RateLimitDecision:
        now = self._clock()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=self._capacity, last_refill=now)
            self._buckets[key] = bucket
        else:
            elapsed = max(0.0, now - bucket.last_refill)
            bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._refill_rate)
            bucket.last_refill = now

        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return RateLimitDecision(allowed=True, retry_after_seconds=0.0)

        missing = 1.0 - bucket.tokens
        return RateLimitDecision(allowed=False, retry_after_seconds=missing / self._refill_rate)
