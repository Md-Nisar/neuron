# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Rolling provider-token budgets: reserve at admission, settle to the real usage (ADR 0008).

`reserve` admits a run only if the window's usage plus the run's reservation fits the budget,
and counts the reservation at once; `settle` replaces it with the usage the run really had.
A reservation is capped at the budget itself, so a budget smaller than one reservation still
admits a run from an empty window.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(eq=False)
class BudgetReservation:
    """Tokens held for one run until `settle`. `handle` is the implementation's own."""

    key: str
    tokens: int
    handle: object = None
    settled: bool = False


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    retry_after_seconds: int = 0
    reservation: BudgetReservation | None = None


class TokenBudget(Protocol):
    async def reserve(self, key: str, tokens: int) -> BudgetDecision:
        """Admit a run against the window's usage plus a reservation of `tokens`.

        The reservation is capped at the budget. This is an admission check, not a cap on the
        run: nothing stops it mid-way, and `settle` charges whatever it really used.
        """
        ...

    async def settle(self, reservation: BudgetReservation, actual_tokens: int) -> None:
        """Replace the reservation with `actual_tokens`. Idempotent; never raises."""
        ...


class _Event:
    __slots__ = ("expired", "time", "tokens")

    def __init__(self, time: float, tokens: int) -> None:
        self.time = time
        self.tokens = tokens
        self.expired = False


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
        self._events: dict[str, deque[_Event]] = {}

    async def reserve(self, key: str, tokens: int) -> BudgetDecision:
        # No `await`: the check and the update are atomic on the event loop.
        held = min(max(tokens, 1), self._token_limit)
        now = self._clock()
        events = self._events.setdefault(key, deque())
        self._expire(events, now)
        used = sum(event.tokens for event in events)
        if used + held > self._token_limit:
            retry_after = 1
            for event in events:
                used -= event.tokens
                if used + held <= self._token_limit:
                    retry_after = max(1, int(event.time + self._window_seconds - now + 0.999))
                    break
            return BudgetDecision(allowed=False, retry_after_seconds=retry_after)
        event = _Event(now, held)
        events.append(event)
        return BudgetDecision(allowed=True, reservation=BudgetReservation(key, held, event))

    async def settle(self, reservation: BudgetReservation, actual_tokens: int) -> None:
        if reservation.settled:
            return
        reservation.settled = True
        actual = max(actual_tokens, 0)
        now = self._clock()
        events = self._events.setdefault(reservation.key, deque())
        self._expire(events, now)
        event = reservation.handle
        if isinstance(event, _Event) and not event.expired:
            event.tokens = actual
        elif actual:  # the reservation aged out of the window; the real usage counts now
            events.append(_Event(now, actual))
        if not events:
            self._events.pop(reservation.key, None)

    def _expire(self, events: deque[_Event], now: float) -> None:
        while events and now - events[0].time >= self._window_seconds:
            events.popleft().expired = True
