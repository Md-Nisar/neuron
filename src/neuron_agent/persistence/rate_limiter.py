# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Postgres request rate limiter: one token bucket per key, shared by every replica (#148).

ADR 0008 decision 8, ADR 0004. The table `neuron_rate_buckets` is `UNLOGGED` and holds
`(key, tokens, refilled_at, allowed)`.

- **One write per request.** `check` is one `INSERT ... ON CONFLICT DO UPDATE ... RETURNING`
  in a short transaction: a new key starts with a full bucket less this request; an existing
  one is refilled for the time since `refilled_at`, and spends one token if it holds one. Row
  locking makes concurrent requests on any replica spend distinct tokens, so a burst split
  across replicas is limited to the burst in total. A refusal also writes (it records the
  refill), so a refused flood still costs a write; the in-memory IP pre-limit sheds that.
- **Database clock.** The time is the database's `clock_timestamp()`; replica clocks are never
  read. A statement that waited on a row lock carries an older time than the row; it adds no
  tokens and moves nothing back, so a stale time can only withhold tokens, never grant extra.
- **Keys.** Opaque strings (`principal:<owner key>`, `ip:<HMAC of the client address>`); the
  limiter never sees a raw address. The table is personal data (pseudonymous).
- **Idle rows.** A bucket idle for `capacity / refill rate` seconds has refilled completely, so
  deleting it changes nothing. Every `CLEANUP_EVERY` checks a bounded batch of such rows is
  deleted, and the retention job deletes the rest, which keeps the table small under many keys.
- **UNLOGGED.** The table is empty after a crash, an unclean shutdown, a failover or a
  point-in-time restore; every key then starts with a full bucket (a burst is granted).
- **Failure.** Any database error (unreachable, lock wait, statement timeout, pool checkout
  timeout) is a `PersistenceError` (`503 persistence_error`): the request is refused, never
  waved through.
"""

from __future__ import annotations

import asyncio
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import psycopg
import structlog
from psycopg_pool import AsyncConnectionPool

from neuron_agent.errors.base import PersistenceError
from neuron_agent.security.rate_limiter import RateLimitDecision

logger = structlog.get_logger(__name__)

# Short: the only contention is one hot key's row, and a waiting check holds a pool connection.
DEFAULT_LOCK_TIMEOUT_MS = 500
DEFAULT_STATEMENT_TIMEOUT_MS = 5_000
# How long a check waits for one of the process's limiter slots before it fails closed.
SLOT_WAIT_SECONDS = 0.5
# A row dated this far ahead of the database clock is clock damage (restore, manual edit).
CLOCK_DAMAGE_SECONDS = 5
# One check in this many also deletes a batch of idle rows (best effort).
CLEANUP_EVERY = 64
CLEANUP_BATCH = 200
PRUNE_BATCH = 1000
# The retention job never deletes a bucket idle for less than this, whatever its settings say.
PRUNE_FLOOR_SECONDS = 3600

_ISOLATION = "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"
_TIMEOUTS = "SELECT set_config('lock_timeout', %s, true), set_config('statement_timeout', %s, true)"
_BUCKET = """
INSERT INTO neuron_rate_buckets AS b (key, tokens, refilled_at, allowed)
VALUES (%(key)s, %(capacity)s::float8 - 1, clock_timestamp(), true)
ON CONFLICT (key) DO UPDATE SET (tokens, allowed, refilled_at) = (
    SELECT CASE WHEN f.fill >= 1 THEN f.fill - 1 ELSE f.fill END,
           f.fill >= 1,
           CASE WHEN b.refilled_at > EXCLUDED.refilled_at + interval '5 seconds'
                THEN EXCLUDED.refilled_at
                ELSE greatest(b.refilled_at, EXCLUDED.refilled_at) END
    FROM (
        SELECT least(
            %(capacity)s::float8,
            b.tokens + greatest(0, extract(epoch FROM EXCLUDED.refilled_at - b.refilled_at))
            * %(rate)s::float8
        ) AS fill
    ) AS f
)
RETURNING allowed, tokens
"""
_DELETE_IDLE = (
    "DELETE FROM neuron_rate_buckets WHERE key IN ("
    " SELECT key FROM neuron_rate_buckets"
    " WHERE refilled_at <= clock_timestamp() - make_interval(secs => %s)"
    " LIMIT %s FOR UPDATE SKIP LOCKED)"
)


# One slot budget per pool, shared by every limiter built on it (the API keeps one limiter per
# key namespace): separate semaphores would each take half the pool and together all of it.
_POOL_SLOTS: weakref.WeakKeyDictionary[Any, asyncio.Semaphore] = weakref.WeakKeyDictionary()


def _slots_for(pool: Any) -> asyncio.Semaphore:
    slots = _POOL_SLOTS.get(pool)
    if slots is None:
        max_size = getattr(pool, "max_size", None)
        slots = asyncio.Semaphore(max(1, max_size // 2) if isinstance(max_size, int) else 4)
        _POOL_SLOTS[pool] = slots
    return slots


class PostgresRateLimiter:
    """Token buckets in Postgres; see the module docstring."""

    def __init__(
        self,
        pool: AsyncConnectionPool[Any],
        *,
        capacity: int,
        requests_per_window: int,
        window_seconds: int,
        lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
        statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
        cleanup_every: int = CLEANUP_EVERY,
        cleanup_batch: int = CLEANUP_BATCH,
    ) -> None:
        if capacity < 1 or requests_per_window < 1 or window_seconds < 1:
            raise ValueError("capacity, requests_per_window and window_seconds must be >= 1")
        if cleanup_every < 1 or cleanup_batch < 1:
            raise ValueError("cleanup_every and cleanup_batch must be >= 1")
        self._pool = pool
        self._rate = requests_per_window / window_seconds
        self._params = {"capacity": float(capacity), "rate": self._rate}
        self._idle_seconds = capacity * window_seconds / requests_per_window
        self._timeouts = (f"{lock_timeout_ms}ms", f"{statement_timeout_ms}ms")
        self._cleanup_every = cleanup_every
        self._cleanup_batch = cleanup_batch
        self._checks = 0
        # Slots well below the pool, so a hot key's queue on one row lock cannot drain the
        # pool the checkpointer and the other guards share.
        self._slots = _slots_for(pool)

    async def check(self, key: str) -> RateLimitDecision:
        async with self._transaction() as conn:
            cursor = await conn.execute(_BUCKET, {**self._params, "key": key})
            row = await cursor.fetchone()
        if row is None:  # an upsert always returns its row
            raise PersistenceError("rate limiter unavailable")
        self._checks += 1
        if self._checks % self._cleanup_every == 0:
            await self._cleanup()
        if row["allowed"]:
            return RateLimitDecision(allowed=True, retry_after_seconds=0.0)
        missing = 1.0 - float(row["tokens"])
        return RateLimitDecision(allowed=False, retry_after_seconds=missing / self._rate)

    async def _cleanup(self) -> None:
        """Delete a batch of fully refilled buckets; a failure is logged and never raised."""
        try:
            async with self._transaction() as conn:
                await conn.execute(_DELETE_IDLE, (self._idle_seconds, self._cleanup_batch))
        except PersistenceError:
            pass  # already logged; the retention job deletes them too

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
        """A limiter transaction. A database failure of any kind fails closed."""
        try:
            try:
                async with asyncio.timeout(SLOT_WAIT_SECONDS):
                    await self._slots.acquire()
            except TimeoutError:
                raise PersistenceError("rate limiter unavailable") from None
            try:
                async with self._pool.connection() as conn:
                    async with conn.transaction():
                        await conn.execute(_ISOLATION)
                        await conn.execute(_TIMEOUTS, self._timeouts)
                        yield conn
            finally:
                self._slots.release()
        except PersistenceError:
            raise
        except Exception as exc:  # noqa: BLE001 - psycopg, OS and timeout failures all fail closed
            logger.warning("rate_limiter_db_unavailable", error_type=type(exc).__name__)
            raise PersistenceError("rate limiter unavailable") from exc


async def delete_idle_buckets(
    pool: AsyncConnectionPool[Any],
    idle_seconds: float,
    *,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
) -> int:
    """Delete every bucket idle longer than the refill time (the retention job).

    `idle_seconds` is the replicas' own `capacity / refill rate`; a floor of
    `PRUNE_FLOOR_SECONDS` keeps a job with different settings from deleting a bucket that
    is not yet full.
    """
    idle = max(idle_seconds, PRUNE_FLOOR_SECONDS)
    deleted = 0
    while True:  # batches, each in its own short transaction
        async with pool.connection() as conn:
            async with conn.transaction():
                await conn.execute(_TIMEOUTS, (f"{lock_timeout_ms}ms", f"{statement_timeout_ms}ms"))
                cursor = await conn.execute(_DELETE_IDLE, (idle, PRUNE_BATCH))
                batch = int(cursor.rowcount)
        deleted += batch
        if batch == 0:
            return deleted
