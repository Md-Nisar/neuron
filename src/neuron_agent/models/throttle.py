# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""A sliding-window limit on model calls.

A hosted provider answers `429` above its request rate and, without `Retry-After`, the retries
only add to the load. Waiting here for a free slot turns those failures into latency. It is
off unless `APP_PROVIDER_MAX_REQUESTS_PER_MINUTE` is set, and the eval runs use it too.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware


class RequestThrottle:
    """Sliding-window limiter: at most `limit` acquisitions in any `window` seconds.

    It is process-wide state for one eval run, shared by every suite. The check and the
    reservation happen without an `await` in between, so concurrent tasks cannot overbook it.
    `clock` and `sleep` are injectable for tests.
    """

    def __init__(
        self,
        limit: int,
        window: float = 60.0,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.limit = limit
        self._window = window
        self._clock = clock
        self._sleep = sleep
        self._starts: list[float] = []
        self.acquired = 0

    async def acquire(self) -> None:
        while True:
            now = self._clock()
            self._starts = [t for t in self._starts if now - t < self._window]
            if len(self._starts) < self.limit:
                self._starts.append(now)
                self.acquired += 1
                return
            await self._sleep(self._window - (now - self._starts[0]))


class ThrottledModelCalls(AgentMiddleware[Any, Any]):
    """Waits for the throttle before each model call, including each provider retry."""

    def __init__(self, inner: AgentMiddleware, throttle: RequestThrottle) -> None:
        super().__init__()
        self._inner = inner
        self._throttle = throttle

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        async def throttled(inner_request: Any) -> Any:
            await self._throttle.acquire()
            return await handler(inner_request)

        return await self._inner.awrap_model_call(request, throttled)


_shared: RequestThrottle | None = None


def shared_throttle(limit: int) -> RequestThrottle:
    """The process-wide throttle for `limit` calls per minute (replaced if the limit changes)."""
    global _shared  # noqa: PLW0603 - one limit per process is the point
    if _shared is None or _shared.limit != limit:
        _shared = RequestThrottle(limit)
    return _shared
