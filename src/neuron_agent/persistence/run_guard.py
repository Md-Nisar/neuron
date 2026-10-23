# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Postgres run guard: `thread_busy` and per-user concurrent runs across replicas.

ADR 0008 decision 8. Each run holds a row in `neuron_run_leases` for its duration.

- A claim is one short `READ COMMITTED` transaction. A transaction-level advisory lock
  (`pg_advisory_xact_lock`, released at commit, never a session lock) serialises the claims
  of one owner, so the count-then-insert below cannot admit k + 1 runs.
- The unique constraint on `thread_id` refuses a second run on a thread, whichever replica
  it lands on; the violation becomes `thread_busy`, never a 500.
- Every timestamp comes from the database (`now()`), so replica clock skew is irrelevant.
  `expires_at = now() + APP_RUN_TIMEOUT_SECONDS + 15 s`: the run is cancelled at its timeout,
  15 s before its lease can expire. There is no heartbeat and no fencing.
- Release deletes the row. It is best effort: a failure is logged and never raised, and
  expiry covers it. After a replica crash its leases block for at most the run timeout plus
  15 s; the next claim for the owner or thread deletes them, and so does the retention job.
- Every guard transaction sets `lock_timeout` and `statement_timeout`. Any database failure
  (unreachable, lock wait, statement timeout, pool checkout timeout) is a `PersistenceError`,
  which the API maps to `503 persistence_error`: the guard fails closed and no model call runs.

The stream cap (`APP_MAX_CONCURRENT_STREAMS`) stays per process, by design.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import psycopg
import structlog
from psycopg import errors
from psycopg_pool import AsyncConnectionPool

from neuron_agent.errors.base import PersistenceError
from neuron_agent.observability import metrics
from neuron_agent.security.run_guard import RunClaimDenied, RunLease

logger = structlog.get_logger(__name__)

# A lease outlives the run timeout by this long, so a run is always cancelled first.
LEASE_GRACE_SECONDS = 15
DEFAULT_LOCK_TIMEOUT_MS = 2_000
DEFAULT_STATEMENT_TIMEOUT_MS = 5_000
# How often each replica refreshes the expired-lease gauge.
EXPIRED_SAMPLE_INTERVAL_SECONDS = 30.0

_ISOLATION = "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"
# Local to the transaction (`true`), so a pooled connection never keeps them.
_TIMEOUTS = "SELECT set_config('lock_timeout', %s, true), set_config('statement_timeout', %s, true)"
_OWNER_LOCK = "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"
_DELETE_EXPIRED = (
    "DELETE FROM neuron_run_leases WHERE expires_at <= now() AND (owner_key = %s OR thread_id = %s)"
)
_COUNT_RUNS = (
    "SELECT count(*) AS n FROM neuron_run_leases"
    " WHERE owner_key = %s AND kind = 'run' AND expires_at > now()"
)
_INSERT = (
    "INSERT INTO neuron_run_leases (owner_key, thread_id, kind, expires_at)"
    " VALUES (%s, %s, %s, now() + make_interval(secs => %s)) RETURNING lease_id"
)
_RELEASE = "DELETE FROM neuron_run_leases WHERE lease_id = %s"
_THREAD_ACTIVE = (
    "SELECT 1 FROM neuron_run_leases WHERE thread_id = %s AND expires_at > now() LIMIT 1"
)
_THREADS_OF = (
    "SELECT thread_id FROM neuron_run_leases"
    " WHERE owner_key = %s AND thread_id IS NOT NULL AND expires_at > now()"
)
_COUNT_EXPIRED = "SELECT count(*) AS n FROM neuron_run_leases WHERE expires_at <= now()"
_DELETE_ALL_EXPIRED = "DELETE FROM neuron_run_leases WHERE expires_at <= now()"


class PostgresRunGuard:
    """Run leases in Postgres; see the module docstring."""

    def __init__(
        self,
        pool: AsyncConnectionPool[Any],
        *,
        max_concurrent_streams: int,
        max_concurrent_runs_per_user: int,
        run_timeout_seconds: int,
        lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
        statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    ) -> None:
        self._pool = pool
        self._max_streams = max_concurrent_streams
        self._max_runs_per_user = max_concurrent_runs_per_user
        self._lease_seconds = float(run_timeout_seconds + LEASE_GRACE_SECONDS)
        self._timeouts = (f"{lock_timeout_ms}ms", f"{statement_timeout_ms}ms")
        self._open_streams = 0
        self._expired_leases = 0
        self._sampler: asyncio.Task[None] | None = None

    # --- lifecycle ---------------------------------------------------------------------

    def start(self) -> None:
        """Start refreshing the expired-lease gauge (needs a running loop and an open pool)."""
        if self._sampler is None:
            metrics.observe_expired_leases(lambda: self._expired_leases)
            self._sampler = asyncio.create_task(self._sample_expired())

    async def close(self) -> None:
        sampler, self._sampler = self._sampler, None
        if sampler is not None:
            sampler.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sampler

    async def _sample_expired(self) -> None:
        while True:
            try:
                self._expired_leases = await self.count_expired()
            except PersistenceError:
                logger.warning("run_lease_gauge_unavailable")
            await asyncio.sleep(EXPIRED_SAMPLE_INTERVAL_SECONDS)

    # --- claims ------------------------------------------------------------------------

    async def claim(
        self, *, thread_id: str, owner_key: str, streaming: bool, guard_thread: bool
    ) -> RunLease:
        if streaming:
            if self._open_streams >= self._max_streams:
                raise RunClaimDenied("concurrent_streams")
            self._open_streams += 1  # reserved before the first await; undone on failure
        try:
            lease_id = await self._insert_run(thread_id if guard_thread else None, owner_key)
        except BaseException:
            if streaming:
                self._open_streams -= 1
            raise
        return self._lease(lease_id, streaming=streaming)

    async def hold_thread(self, *, thread_id: str, owner_key: str) -> RunLease:
        """Hold `thread_id` for a deletion: no run starts on it, and no cap is consumed."""
        async with self._transaction() as conn:
            await conn.execute(_DELETE_EXPIRED, (owner_key, thread_id))
            lease_id = await self._insert(conn, owner_key, thread_id, "delete")
        return self._lease(lease_id, streaming=False)

    async def _insert_run(self, thread_id: str | None, owner_key: str) -> object:
        async with self._transaction() as conn:
            await conn.execute(_OWNER_LOCK, (f"neuron.run_lease:{owner_key}",))
            await conn.execute(_DELETE_EXPIRED, (owner_key, thread_id))
            cursor = await conn.execute(_COUNT_RUNS, (owner_key,))
            row = await cursor.fetchone()
            if row is not None and row["n"] >= self._max_runs_per_user:
                raise RunClaimDenied("concurrent_runs")
            return await self._insert(conn, owner_key, thread_id, "run")

    async def _insert(
        self, conn: psycopg.AsyncConnection[Any], owner_key: str, thread_id: str | None, kind: str
    ) -> object:
        try:
            cursor = await conn.execute(_INSERT, (owner_key, thread_id, kind, self._lease_seconds))
        except errors.UniqueViolation:
            raise RunClaimDenied("thread_busy") from None
        row = await cursor.fetchone()
        assert row is not None  # nosec B101
        return row["lease_id"]

    def _lease(self, lease_id: object, *, streaming: bool) -> RunLease:
        async def release() -> None:
            if streaming:
                self._open_streams -= 1
            try:
                async with self._transaction() as conn:
                    await conn.execute(_RELEASE, (lease_id,))
            except Exception as exc:  # noqa: BLE001 - never raise into the request path
                logger.warning("run_lease_release_failed", error_type=type(exc).__name__)

        return RunLease(release)

    # --- queries -----------------------------------------------------------------------

    async def is_thread_active(self, thread_id: str) -> bool:
        async with self._transaction() as conn:
            cursor = await conn.execute(_THREAD_ACTIVE, (thread_id,))
            return await cursor.fetchone() is not None

    async def active_threads_of(self, owner_key: str) -> frozenset[str]:
        async with self._transaction() as conn:
            cursor = await conn.execute(_THREADS_OF, (owner_key,))
            return frozenset(row["thread_id"] for row in await cursor.fetchall())

    async def count_expired(self) -> int:
        """Leases past `expires_at` that nothing has deleted yet (the gauge's value)."""
        async with self._transaction() as conn:
            cursor = await conn.execute(_COUNT_EXPIRED)
            row = await cursor.fetchone()
            return int(row["n"]) if row else 0

    # --- transactions ------------------------------------------------------------------

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
        """A guard transaction. A database failure of any kind fails closed."""
        try:
            async with self._pool.connection() as conn:
                async with conn.transaction():
                    await conn.execute(_ISOLATION)
                    await conn.execute(_TIMEOUTS, self._timeouts)
                    yield conn
        except psycopg.Error as exc:
            logger.warning("run_guard_unavailable", error_type=type(exc).__name__)
            raise PersistenceError("run guard unavailable") from exc


async def delete_expired_leases(pool: AsyncConnectionPool[Any]) -> int:
    """Delete every lease past `expires_at` (the retention job). Returns how many."""
    async with pool.connection() as conn:
        cursor = await conn.execute(_DELETE_ALL_EXPIRED)
        return int(cursor.rowcount)
