"""Per-owner thread index for the `/v1/me/*` endpoints.

Lists the thread IDs and activity times an owner key has, newest activity first, without
loading any thread's messages. On Postgres this is one aggregate query over root-namespace
checkpoint rows, served by the owner index `make db-setup` creates. The in-memory saver
(development and test only) falls back to a scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from neuron_agent.errors.base import PersistenceError
from neuron_agent.persistence.checkpointer import Persistence

# Threads are found by the `owner` metadata every run writes, and timed over all their
# root checkpoints, so checkpoints written before that metadata existed still count toward
# `created_at`. The lateral join keeps the total when `offset` is past the last thread.
_OWNED_THREADS_SQL = """
WITH owned AS (
    SELECT c.thread_id,
           min((c.checkpoint->>'ts')::timestamptz) AS created_at,
           max((c.checkpoint->>'ts')::timestamptz) AS updated_at
    FROM checkpoints AS c
    WHERE c.checkpoint_ns = ''
      AND c.thread_id IN (
          SELECT thread_id FROM checkpoints
          WHERE checkpoint_ns = '' AND metadata->>'owner' = %(owner)s
      )
    GROUP BY c.thread_id
)
SELECT counted.total, page.thread_id, page.created_at, page.updated_at
FROM (SELECT count(*) AS total FROM owned) AS counted
LEFT JOIN LATERAL (
    SELECT * FROM owned
    ORDER BY updated_at DESC, thread_id
    LIMIT %(limit)s OFFSET %(offset)s
) AS page ON true
"""


@dataclass(frozen=True)
class OwnedThread:
    thread_id: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class OwnedThreadPage:
    total: int
    threads: list[OwnedThread]


async def owned_threads(
    persistence: Persistence, owner_key: str, *, limit: int | None, offset: int = 0
) -> OwnedThreadPage:
    """Return one page of the owner's threads; `limit=None` returns all of them."""
    checkpointer = persistence.checkpointer
    if checkpointer is None:
        return OwnedThreadPage(total=0, threads=[])
    if isinstance(checkpointer, AsyncPostgresSaver) and persistence.pool is not None:
        async with persistence.pool.connection() as conn:
            cursor = await conn.execute(
                _OWNED_THREADS_SQL, {"owner": owner_key, "limit": limit, "offset": offset}
            )
            rows = await cursor.fetchall()
        return OwnedThreadPage(
            total=rows[0]["total"],
            threads=[
                OwnedThread(
                    thread_id=row["thread_id"],
                    created_at=row["created_at"].astimezone(UTC),
                    updated_at=row["updated_at"].astimezone(UTC),
                )
                for row in rows
                if row["thread_id"] is not None
            ],
        )

    owned: set[str] = set()
    times: dict[str, tuple[datetime, datetime]] = {}
    async for item in checkpointer.alist(None):
        configurable = item.config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        if configurable.get("checkpoint_ns", "") != "" or not isinstance(thread_id, str):
            continue
        if item.metadata.get("owner") == owner_key:
            owned.add(thread_id)
        timestamp = _checkpoint_time(item.checkpoint.get("ts"))
        first, last = times.get(thread_id, (timestamp, timestamp))
        times[thread_id] = (min(first, timestamp), max(last, timestamp))
    ordered = sorted(
        (OwnedThread(thread_id, *times[thread_id]) for thread_id in owned),
        key=lambda thread: (-thread.updated_at.timestamp(), thread.thread_id),
    )
    end = None if limit is None else offset + limit
    return OwnedThreadPage(total=len(ordered), threads=ordered[offset:end])


def _checkpoint_time(value: Any) -> datetime:
    """Parse a checkpoint's `ts` as an aware UTC datetime."""
    if not isinstance(value, str):
        raise PersistenceError("checkpoint timestamp is unavailable")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PersistenceError("checkpoint timestamp is invalid") from exc
    return timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=UTC)
