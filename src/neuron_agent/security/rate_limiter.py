# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""In-process rate limiting for the API boundary (ADR 0004)."""

from __future__ import annotations

import time
from collections import OrderedDict
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


# Hard cap on tracked keys. Each bucket is about 200 bytes, so this holds memory to a
# few MB, while far exceeding the number of clients one worker serves at once.
DEFAULT_MAX_BUCKETS = 10_000


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class InMemoryTokenBucketRateLimiter:
    """Single-process token-bucket limiter keyed by an opaque string.

    Not safe across multiple worker processes or instances. A distributed
    backend must implement the `RateLimiter` protocol to replace this for
    multi-instance deployments (see ADR 0004).

    Memory is bounded. A bucket idle for `capacity / refill_rate` seconds has
    refilled completely, so dropping it is indistinguishable from keeping it.
    If more than `max_buckets` keys are active at once, the least recently used
    are dropped; such a key restarts with a full bucket, never more.
    """

    def __init__(
        self,
        *,
        capacity: int,
        requests_per_window: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
        max_buckets: int = DEFAULT_MAX_BUCKETS,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if requests_per_window < 1:
            raise ValueError("requests_per_window must be >= 1")
        if window_seconds < 1:
            raise ValueError("window_seconds must be >= 1")
        if max_buckets < 1:
            raise ValueError("max_buckets must be >= 1")
        self._max_buckets = max_buckets
        self._capacity = float(capacity)
        self._refill_rate = requests_per_window / window_seconds
        self._clock = clock
        # Ordered by last use, oldest first.
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()

    def check(self, key: str) -> RateLimitDecision:
        now = self._clock()
        self._evict(now)
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=self._capacity, last_refill=now)
            self._buckets[key] = bucket
            while len(self._buckets) > self._max_buckets:
                self._buckets.popitem(last=False)
        else:
            self._buckets.move_to_end(key)
            elapsed = max(0.0, now - bucket.last_refill)
            bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._refill_rate)
            bucket.last_refill = now

        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return RateLimitDecision(allowed=True, retry_after_seconds=0.0)

        missing = 1.0 - bucket.tokens
        return RateLimitDecision(allowed=False, retry_after_seconds=missing / self._refill_rate)

    def _evict(self, now: float) -> None:
        """Drop buckets idle long enough to have refilled to capacity."""
        full_refill_seconds = self._capacity / self._refill_rate
        while self._buckets:
            oldest = next(iter(self._buckets.values()))
            if now - oldest.last_refill < full_refill_seconds:
                break
            self._buckets.popitem(last=False)
