# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Thread retention: delete threads inactive for longer than a cutoff (ADR 0005, decision 7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from neuron_agent.observability.audit import audit
from neuron_agent.persistence.checkpointer import Persistence
from neuron_agent.persistence.run_guard import delete_expired_leases

logger = structlog.get_logger(__name__)

# Last activity per thread = newest root-namespace checkpoint timestamp.
_STALE_THREADS_SQL = """
SELECT thread_id
FROM checkpoints
WHERE checkpoint_ns = ''
GROUP BY thread_id
HAVING max((checkpoint->>'ts')::timestamptz) < %s
"""


async def _prune_leases(persistence: Persistence) -> int:
    """Delete expired run leases. A failure (a missing table before migration 2, a missing
    privilege, a lock wait) is logged and never stops the rest of the job."""
    if persistence.pool is None:
        return 0
    try:
        return await delete_expired_leases(persistence.pool)
    except Exception as exc:  # noqa: BLE001 - leases are best effort; expiry already covers them
        logger.warning("run_lease_cleanup_failed", error_type=type(exc).__name__)
        return 0


async def prune_threads(
    persistence: Persistence,
    *,
    older_than: timedelta,
    now: datetime | None = None,
    delete_leases: bool = False,
) -> int:
    """Delete every thread whose last activity is older than `older_than`. Idempotent.

    With `delete_leases` (the limits backend is Postgres), run leases past `expires_at` are
    deleted afterwards (ADR 0008 decision 8); a crashed replica leaves them behind. Returns
    the number of threads deleted.
    """
    checkpointer = persistence.checkpointer
    if checkpointer is None:
        expired_leases = await _prune_leases(persistence) if delete_leases else 0
        logger.info("thread_prune_job_completed", count=0, expired_leases=expired_leases)
        audit(
            "threads_pruned",
            outcome="allowed",
            action="threads:prune",
            resource_type="thread",
            count=0,
        )
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
    expired_leases = await _prune_leases(persistence) if delete_leases else 0
    logger.info(
        "thread_prune_job_completed",
        count=len(stale),
        retention_days=older_than.days,
        expired_leases=expired_leases,
    )
    audit(
        "threads_pruned",
        outcome="allowed",
        action="threads:prune",
        resource_type="thread",
        count=len(stale),
    )
    return len(stale)
