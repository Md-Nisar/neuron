# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Answer ratings, one per (owner, run) (ADR 0010 decision 6, ADR 0011).

A rating is a score and a fixed reason, never text. The first rating of a run stands: a repeat
returns what is stored and records nothing, so a double click or a retry counts once. On Postgres
it lives in `neuron_feedback` (migration 15); without a database, in process memory.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from psycopg_pool import AsyncConnectionPool


@dataclass(frozen=True)
class StoredFeedback:
    thread_id: str
    score: int
    reason: str | None
    created: bool  # False when the run already had a rating, which stands


class FeedbackStore(Protocol):
    async def record(
        self, owner_key: str, thread_id: str, run_id: str, score: int, reason: str | None
    ) -> StoredFeedback: ...

    async def forget_threads(self, thread_ids: Sequence[str]) -> None: ...

    async def forget_owner(self, owner_key: str) -> None: ...


class InMemoryFeedback:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], tuple[str, int, str | None]] = {}

    async def record(
        self, owner_key: str, thread_id: str, run_id: str, score: int, reason: str | None
    ) -> StoredFeedback:
        existing = self._rows.get((owner_key, run_id))
        if existing is not None:
            return StoredFeedback(existing[0], existing[1], existing[2], created=False)
        self._rows[owner_key, run_id] = (thread_id, score, reason)
        return StoredFeedback(thread_id, score, reason, created=True)

    async def forget_threads(self, thread_ids: Sequence[str]) -> None:
        doomed = set(thread_ids)
        self._rows = {k: v for k, v in self._rows.items() if v[0] not in doomed}

    async def forget_owner(self, owner_key: str) -> None:
        self._rows = {k: v for k, v in self._rows.items() if k[0] != owner_key}


class PostgresFeedback:
    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def record(
        self, owner_key: str, thread_id: str, run_id: str, score: int, reason: str | None
    ) -> StoredFeedback:
        async with self._pool.connection() as conn:
            cursor = await conn.execute(
                "INSERT INTO neuron_feedback (owner_key, thread_id, run_id, score, reason) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (owner_key, run_id) DO NOTHING "
                "RETURNING thread_id, score, reason",
                (owner_key, thread_id, run_id, score, reason),
            )
            row = await cursor.fetchone()
            if row is not None:
                return StoredFeedback(row["thread_id"], row["score"], row["reason"], created=True)
            cursor = await conn.execute(
                "SELECT thread_id, score, reason FROM neuron_feedback "
                "WHERE owner_key = %s AND run_id = %s",
                (owner_key, run_id),
            )
            row = await cursor.fetchone()
        if row is None:  # deleted between the two statements: the rating is simply not there
            return StoredFeedback(thread_id, score, reason, created=False)
        return StoredFeedback(row["thread_id"], row["score"], row["reason"], created=False)

    async def forget_threads(self, thread_ids: Sequence[str]) -> None:
        if not thread_ids:
            return
        async with self._pool.connection() as conn:
            await conn.execute(
                "DELETE FROM neuron_feedback WHERE thread_id = ANY(%s)", (list(thread_ids),)
            )

    async def forget_owner(self, owner_key: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("DELETE FROM neuron_feedback WHERE owner_key = %s", (owner_key,))
