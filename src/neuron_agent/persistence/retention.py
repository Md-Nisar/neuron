"""Thread retention: delete threads inactive for longer than a cutoff (ADR 0005, decision 7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from neuron_agent.persistence.checkpointer import Persistence

logger = structlog.get_logger(__name__)

# Last activity per thread = newest root-namespace checkpoint timestamp.
_STALE_THREADS_SQL = """
SELECT thread_id
FROM checkpoints
WHERE checkpoint_ns = ''
GROUP BY thread_id
HAVING max((checkpoint->>'ts')::timestamptz) < %s
"""


async def prune_threads(
    persistence: Persistence, *, older_than: timedelta, now: datetime | None = None
) -> int:
    """Delete every thread whose last activity is older than `older_than`. Idempotent.

    Returns the number of threads deleted.
    """
    checkpointer = persistence.checkpointer
    if checkpointer is None:
        return 0
    cutoff = (now or datetime.now(UTC)) - older_than
    if isinstance(checkpointer, AsyncPostgresSaver) and persistence.pool is not None:
        async with persistence.pool.connection() as conn:
            cursor = await conn.execute(_STALE_THREADS_SQL, (cutoff,))
            stale = [row["thread_id"] for row in await cursor.fetchall()]
    else:
        last_activity: dict[str, datetime] = {}
        async for checkpoint in checkpointer.alist(None):
            if checkpoint.config["configurable"].get("checkpoint_ns", ""):
                continue
            thread_id = checkpoint.config["configurable"]["thread_id"]
            ts = datetime.fromisoformat(checkpoint.checkpoint["ts"])
            last_activity[thread_id] = max(ts, last_activity.get(thread_id, ts))
        stale = [thread_id for thread_id, ts in last_activity.items() if ts < cutoff]
    for thread_id in stale:
        await checkpointer.adelete_thread(thread_id)
    logger.info("threads_pruned", count=len(stale), retention_days=older_than.days)
    return len(stale)
