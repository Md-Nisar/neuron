"""`APP_PROVIDER_MAX_REQUESTS_PER_MINUTE` makes model calls wait for a slot instead of failing."""

from __future__ import annotations

from typing import Any

import pytest

from neuron_agent.config.settings import Settings
from neuron_agent.models.factory import agent_middleware
from neuron_agent.models.throttle import RequestThrottle, ThrottledModelCalls, shared_throttle
from neuron_agent.tools.registry import builtin_registry

pytestmark = pytest.mark.anyio


def test_the_throttle_is_off_unless_configured() -> None:
    settings = Settings(env="test")
    assert settings.provider_max_requests_per_minute is None
    assert not isinstance(agent_middleware(settings, builtin_registry())[-1], ThrottledModelCalls)


def test_the_configured_rate_wraps_the_provider_call_with_one_shared_throttle() -> None:
    settings = Settings(env="test", provider_max_requests_per_minute=36)
    last = agent_middleware(settings, builtin_registry())[-1]
    assert isinstance(last, ThrottledModelCalls)
    assert shared_throttle(36).limit == 36
    assert shared_throttle(36) is shared_throttle(36)


@pytest.mark.parametrize("value", [0, -1])
def test_the_rate_must_be_positive(value: int) -> None:
    with pytest.raises(ValueError, match="provider_max_requests_per_minute"):
        Settings(env="test", provider_max_requests_per_minute=value)


async def test_calls_beyond_the_rate_wait_for_the_window() -> None:
    now = [0.0]
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)
        now[0] += seconds

    throttle = RequestThrottle(2, 60.0, clock=lambda: now[0], sleep=sleep)

    class _Inner:
        async def awrap_model_call(self, request: Any, handler: Any) -> Any:
            return await handler(request)

    wrapper = ThrottledModelCalls(_Inner(), throttle)  # type: ignore[arg-type]

    async def handler(request: Any) -> str:
        return "ok"

    for _ in range(3):
        assert await wrapper.awrap_model_call("r", handler) == "ok"
    assert waits == [60.0]
