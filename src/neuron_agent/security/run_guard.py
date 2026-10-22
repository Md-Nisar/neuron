# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Run guards: the thread-busy check and the concurrency caps (ADR 0005, ADR 0008)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol

RunDenialReason = Literal["concurrent_streams", "concurrent_runs", "thread_busy"]


class RunClaimDenied(Exception):  # noqa: N818 - a control-flow signal, not an error
    """A claim was refused; `reason` says which guard refused it."""

    def __init__(self, reason: RunDenialReason) -> None:
        super().__init__(reason)
        self.reason = reason


class RunLease:
    """A run's claim on its thread and (for streams) a concurrency slot. Idempotent release."""

    def __init__(self, release: Callable[[], Awaitable[None]]) -> None:
        self._release: Callable[[], Awaitable[None]] | None = release

    async def release(self) -> None:
        """Free the claim. Shielded: a cancelled caller (a disconnect) must still free it."""
        if self._release is not None:
            release, self._release = self._release, None
            await asyncio.shield(release())


class RunGuard(Protocol):
    """Admits runs against the thread-busy rule and the stream and per-user caps."""

    async def claim(
        self, *, thread_id: str, owner_key: str, streaming: bool, guard_thread: bool
    ) -> RunLease:
        """Claim the thread and a slot, or raise `RunClaimDenied`.

        `guard_thread` is false without persistence, where `thread_id` is only a
        correlation ID and concurrent runs share no state.
        """
        ...

    async def is_thread_active(self, thread_id: str) -> bool: ...

    async def active_threads_of(self, owner_key: str) -> frozenset[str]:
        """The threads `owner_key` has a run on."""
        ...


class InMemoryRunGuard:
    """Process-local run guard; not shared across replicas (ADR 0005 decisions 5 and 6).

    `claim` has no `await` between its checks and its updates, so it is atomic on the loop.
    """

    def __init__(self, *, max_concurrent_streams: int, max_concurrent_runs_per_user: int) -> None:
        self._max_streams = max_concurrent_streams
        self._max_runs_per_user = max_concurrent_runs_per_user
        self._active_threads: set[str] = set()
        self._active_thread_owners: dict[str, str] = {}
        self._active_runs_by_owner: dict[str, int] = {}
        self._open_streams = 0

    async def claim(
        self, *, thread_id: str, owner_key: str, streaming: bool, guard_thread: bool
    ) -> RunLease:
        if streaming and self._open_streams >= self._max_streams:
            raise RunClaimDenied("concurrent_streams")
        active_for_owner = self._active_runs_by_owner.get(owner_key, 0)
        if active_for_owner >= self._max_runs_per_user:
            raise RunClaimDenied("concurrent_runs")
        if guard_thread and thread_id in self._active_threads:
            raise RunClaimDenied("thread_busy")
        if streaming:
            self._open_streams += 1
        self._active_runs_by_owner[owner_key] = active_for_owner + 1
        if guard_thread:
            self._active_threads.add(thread_id)
            self._active_thread_owners[thread_id] = owner_key

        async def release() -> None:
            if streaming:
                self._open_streams -= 1
            if guard_thread:
                self._active_threads.discard(thread_id)
                self._active_thread_owners.pop(thread_id, None)
            remaining = self._active_runs_by_owner[owner_key] - 1
            if remaining:
                self._active_runs_by_owner[owner_key] = remaining
            else:
                self._active_runs_by_owner.pop(owner_key, None)

        return RunLease(release)

    async def is_thread_active(self, thread_id: str) -> bool:
        return thread_id in self._active_threads

    async def active_threads_of(self, owner_key: str) -> frozenset[str]:
        return frozenset(
            thread_id
            for thread_id, active_owner in self._active_thread_owners.items()
            if active_owner == owner_key
        )
