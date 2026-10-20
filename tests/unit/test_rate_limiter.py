from __future__ import annotations

import pytest

from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def test_allows_requests_up_to_capacity() -> None:
    clock = _FakeClock()
    limiter = InMemoryTokenBucketRateLimiter(
        capacity=3, requests_per_window=3, window_seconds=60, clock=clock
    )
    for _ in range(3):
        assert limiter.check("client-a").allowed is True


def test_denies_once_capacity_is_exhausted() -> None:
    clock = _FakeClock()
    limiter = InMemoryTokenBucketRateLimiter(
        capacity=1, requests_per_window=1, window_seconds=60, clock=clock
    )
    assert limiter.check("client-a").allowed is True
    decision = limiter.check("client-a")
    assert decision.allowed is False
    assert decision.retry_after_seconds == pytest.approx(60.0)


def test_refills_over_time() -> None:
    clock = _FakeClock()
    limiter = InMemoryTokenBucketRateLimiter(
        capacity=1, requests_per_window=1, window_seconds=60, clock=clock
    )
    assert limiter.check("client-a").allowed is True
    assert limiter.check("client-a").allowed is False
    clock.advance(60.0)
    assert limiter.check("client-a").allowed is True


def test_tracks_keys_independently() -> None:
    clock = _FakeClock()
    limiter = InMemoryTokenBucketRateLimiter(
        capacity=1, requests_per_window=1, window_seconds=60, clock=clock
    )
    assert limiter.check("client-a").allowed is True
    assert limiter.check("client-b").allowed is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"capacity": 1, "requests_per_window": 1, "window_seconds": 60, "max_buckets": 0},
        {"capacity": 0, "requests_per_window": 1, "window_seconds": 60},
        {"capacity": 1, "requests_per_window": 0, "window_seconds": 60},
        {"capacity": 1, "requests_per_window": 1, "window_seconds": 0},
    ],
)
def test_rejects_invalid_configuration(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        InMemoryTokenBucketRateLimiter(**kwargs)


def _buckets(limiter: InMemoryTokenBucketRateLimiter) -> int:
    return len(limiter._buckets)  # noqa: SLF001


def test_bucket_count_stays_bounded_under_many_distinct_keys() -> None:
    clock = _FakeClock()
    limiter = InMemoryTokenBucketRateLimiter(
        capacity=1, requests_per_window=1, window_seconds=60, clock=clock, max_buckets=50
    )
    for i in range(1000):
        limiter.check(f"ip-{i}")
        clock.advance(0.001)
    assert _buckets(limiter) <= 50


def test_idle_buckets_are_evicted_only_after_they_would_have_refilled() -> None:
    clock = _FakeClock()
    limiter = InMemoryTokenBucketRateLimiter(
        capacity=2, requests_per_window=2, window_seconds=2, clock=clock
    )
    limiter.check("idle")  # full refill takes capacity / rate = 2 seconds
    clock.advance(1.9)
    limiter.check("other")
    assert _buckets(limiter) == 2
    clock.advance(0.2)
    limiter.check("other")
    assert _buckets(limiter) == 1


def test_hard_cap_evicts_oldest_first() -> None:
    clock = _FakeClock()
    limiter = InMemoryTokenBucketRateLimiter(
        capacity=1, requests_per_window=1, window_seconds=60, clock=clock, max_buckets=2
    )
    limiter.check("a")
    clock.advance(1)
    limiter.check("b")
    clock.advance(1)
    limiter.check("a")  # refreshes a, so b is now the oldest
    clock.advance(1)
    limiter.check("c")
    assert list(limiter._buckets) == ["a", "c"]  # noqa: SLF001


def test_eviction_never_grants_more_than_a_full_bucket() -> None:
    clock = _FakeClock()
    limiter = InMemoryTokenBucketRateLimiter(
        capacity=2, requests_per_window=2, window_seconds=60, clock=clock, max_buckets=1
    )
    assert limiter.check("a").allowed is True
    assert limiter.check("a").allowed is True
    assert limiter.check("a").allowed is False
    limiter.check("b")  # evicts a through the hard cap
    # a restarts with a full bucket: exactly capacity requests, then denied.
    assert limiter.check("a").allowed is True
    assert limiter.check("a").allowed is True
    assert limiter.check("a").allowed is False
