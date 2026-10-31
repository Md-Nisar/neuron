# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Per-user conversation titles (ADR 0011).

A title is content derived from the user's first message, filed under the HMAC owner key. It is
never logged, traced or counted: callers log the thread ID at most. On Postgres it lives in
`neuron_thread_meta` (migration 13); without a database (development and tests) it lives in
process memory, like the in-memory checkpointer it sits beside.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from psycopg_pool import AsyncConnectionPool

from neuron_agent.schemas.agent import TITLE_MAX_CHARS

_BATCH_SIZE = 500


def derive_title(message: str) -> str | None:
    """The first line of thought of a conversation: whitespace collapsed, cut to 80 characters."""
    return " ".join(message.split())[:TITLE_MAX_CHARS].rstrip() or None


class ThreadTitles(Protocol):
    async def set_if_absent(self, owner_key: str, thread_id: str, title: str) -> None: ...

    async def rename(self, owner_key: str, thread_id: str, title: str) -> None: ...

    async def titles(self, owner_key: str, thread_ids: Sequence[str]) -> dict[str, str]: ...

    async def forget_threads(self, thread_ids: Sequence[str]) -> None: ...

    async def forget_owner(self, owner_key: str) -> None: ...


class InMemoryThreadTitles:
    def __init__(self) -> None:
        self._titles: dict[tuple[str, str], str] = {}

    async def set_if_absent(self, owner_key: str, thread_id: str, title: str) -> None:
        self._titles.setdefault((owner_key, thread_id), title)

    async def rename(self, owner_key: str, thread_id: str, title: str) -> None:
        self._titles[owner_key, thread_id] = title

    async def titles(self, owner_key: str, thread_ids: Sequence[str]) -> dict[str, str]:
        return {t: self._titles[owner_key, t] for t in thread_ids if (owner_key, t) in self._titles}

    async def forget_threads(self, thread_ids: Sequence[str]) -> None:
        doomed = set(thread_ids)
        self._titles = {k: v for k, v in self._titles.items() if k[1] not in doomed}

    async def forget_owner(self, owner_key: str) -> None:
        self._titles = {k: v for k, v in self._titles.items() if k[0] != owner_key}


class PostgresThreadTitles:
    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def set_if_absent(self, owner_key: str, thread_id: str, title: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO neuron_thread_meta (owner_key, thread_id, title) "
                "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (owner_key, thread_id, title),
            )

    async def rename(self, owner_key: str, thread_id: str, title: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute(
                "INSERT INTO neuron_thread_meta (owner_key, thread_id, title) "
                "VALUES (%s, %s, %s) ON CONFLICT (owner_key, thread_id) "
                "DO UPDATE SET title = EXCLUDED.title, updated_at = now()",
                (owner_key, thread_id, title),
            )

    async def titles(self, owner_key: str, thread_ids: Sequence[str]) -> dict[str, str]:
        if not thread_ids:
            return {}
        async with self._pool.connection() as conn:
            cursor = await conn.execute(
                "SELECT thread_id, title FROM neuron_thread_meta "
                "WHERE owner_key = %s AND thread_id = ANY(%s)",
                (owner_key, list(thread_ids)),
            )
            return {row["thread_id"]: row["title"] for row in await cursor.fetchall()}

    async def forget_threads(self, thread_ids: Sequence[str]) -> None:
        if not thread_ids:
            return
        async with self._pool.connection() as conn:
            for i in range(0, len(thread_ids), _BATCH_SIZE):
                chunk = list(thread_ids[i : i + _BATCH_SIZE])
                await conn.execute(
                    "DELETE FROM neuron_thread_meta WHERE thread_id = ANY(%s)", (chunk,)
                )

    async def forget_owner(self, owner_key: str) -> None:
        async with self._pool.connection() as conn:
            await conn.execute("DELETE FROM neuron_thread_meta WHERE owner_key = %s", (owner_key,))
