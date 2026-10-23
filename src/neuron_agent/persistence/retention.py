# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Thread retention: delete threads inactive for longer than a cutoff (ADR 0005, decision 7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from neuron_agent.observability.audit import audit
from neuron_agent.persistence.checkpointer import Persistence
from neuron_agent.persistence.rate_limiter import delete_idle_buckets
from neuron_agent.persistence.run_guard import delete_expired_leases
from neuron_agent.persistence.token_budget import delete_ledger_outside_window

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


async def _prune_ledger(persistence: Persistence, window_seconds: int) -> int:
    """Delete token-ledger minutes outside the budget window; a failure is logged only, since
    admission never counts those minutes anyway."""
    if persistence.pool is None:
        return 0
    try:
        return await delete_ledger_outside_window(persistence.pool, window_seconds)
    except Exception as exc:  # noqa: BLE001 - the ledger is bounded by the window regardless
        logger.warning("token_ledger_cleanup_failed", error_type=type(exc).__name__)
        return 0


async def _prune_buckets(persistence: Persistence, idle_seconds: float) -> int:
    """Delete fully refilled rate-limit buckets; a failure is logged only, since an idle bucket
    is indistinguishable from a missing one."""
    if persistence.pool is None:
        return 0
    try:
        return await delete_idle_buckets(persistence.pool, idle_seconds)
    except Exception as exc:  # noqa: BLE001 - the limiter also deletes idle rows as it writes
        logger.warning("rate_bucket_cleanup_failed", error_type=type(exc).__name__)
        return 0


async def _buckets(persistence: Persistence, idle_seconds: float | None) -> int:
    return 0 if idle_seconds is None else await _prune_buckets(persistence, idle_seconds)


async def _ledger(persistence: Persistence, window_seconds: int | None) -> int:
    return 0 if window_seconds is None else await _prune_ledger(persistence, window_seconds)


async def prune_threads(
    persistence: Persistence,
    *,
    older_than: timedelta,
    now: datetime | None = None,
    delete_leases: bool = False,
    ledger_window_seconds: int | None = None,
    rate_bucket_idle_seconds: float | None = None,
) -> int:
    """Delete every thread whose last activity is older than `older_than`. Idempotent.

    With `delete_leases` (the limits backend is Postgres), run leases past `expires_at` are
    deleted afterwards (ADR 0008 decision 8); a crashed replica leaves them behind. With
    `ledger_window_seconds` (the Postgres budget's window), so are the token-ledger minutes
    outside that window; with `rate_bucket_idle_seconds` (the limiter's `capacity / refill
    rate`), so are the rate-limit buckets idle longer than that. Returns the number of threads
    deleted.
    """
    checkpointer = persistence.checkpointer
    if checkpointer is None:
        expired_leases = await _prune_leases(persistence) if delete_leases else 0
        ledger_minutes = await _ledger(persistence, ledger_window_seconds)
        idle_buckets = await _buckets(persistence, rate_bucket_idle_seconds)
        logger.info(
            "thread_prune_job_completed",
            count=0,
            expired_leases=expired_leases,
            expired_ledger_minutes=ledger_minutes,
            idle_rate_buckets=idle_buckets,
        )
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
    ledger_minutes = await _ledger(persistence, ledger_window_seconds)
    idle_buckets = await _buckets(persistence, rate_bucket_idle_seconds)
    logger.info(
        "thread_prune_job_completed",
        count=len(stale),
        retention_days=older_than.days,
        expired_leases=expired_leases,
        expired_ledger_minutes=ledger_minutes,
        idle_rate_buckets=idle_buckets,
    )
    audit(
        "threads_pruned",
        outcome="allowed",
        action="threads:prune",
        resource_type="thread",
        count=len(stale),
    )
    return len(stale)
