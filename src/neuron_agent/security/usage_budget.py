"""Process-local rolling provider-token budgets."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    retry_after_seconds: int = 0


class TokenBudget(Protocol):
    def check(self, key: str) -> BudgetDecision: ...

    def charge(self, key: str, tokens: int) -> None: ...


class InMemoryRollingTokenBudget:
    """Rolling token accounting for one process; use a shared implementation across replicas."""

    def __init__(
        self,
        *,
        token_limit: int,
        window_seconds: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if token_limit < 1 or window_seconds < 1:
            raise ValueError("token_limit and window_seconds must be >= 1")
        self._token_limit = token_limit
        self._window_seconds = window_seconds
        self._clock = clock
        self._events: dict[str, deque[tuple[float, int]]] = {}

    def check(self, key: str) -> BudgetDecision:
        now = self._clock()
        events = self._events.get(key)
        if events is None:
            return BudgetDecision(allowed=True)
        self._expire(events, now)
        if not events:
            self._events.pop(key, None)
            return BudgetDecision(allowed=True)
        used = sum(tokens for _, tokens in events)
        if used < self._token_limit:
            return BudgetDecision(allowed=True)
        oldest, _ = events[0]
        return BudgetDecision(
            allowed=False,
            retry_after_seconds=max(1, int(oldest + self._window_seconds - now + 0.999)),
        )

    def charge(self, key: str, tokens: int) -> None:
        if tokens <= 0:
            return
        now = self._clock()
        events = self._events.setdefault(key, deque())
        self._expire(events, now)
        events.append((now, tokens))

    def _expire(self, events: deque[tuple[float, int]], now: float) -> None:
        while events and now - events[0][0] >= self._window_seconds:
            events.popleft()
