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
        {"capacity": 0, "requests_per_window": 1, "window_seconds": 60},
        {"capacity": 1, "requests_per_window": 0, "window_seconds": 60},
        {"capacity": 1, "requests_per_window": 1, "window_seconds": 0},
    ],
)
def test_rejects_invalid_configuration(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        InMemoryTokenBucketRateLimiter(**kwargs)
