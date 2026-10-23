# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Postgres token budget: one ledger shared by every replica (ADR 0008 decision 8, #147).

The ledger `neuron_token_ledger` holds `(owner_key, minute, tokens)`, a logged table.

- **Window.** A charge lands in the database-clock minute it was made in and counts until
  `APP_USER_TOKEN_BUDGET_WINDOW_SECONDS` plus the rest of that minute have passed, so usage is
  never forgotten early and is held at most 60 s longer than the window (one-minute
  granularity). `Retry-After` is the time until enough minutes leave the window to fit the run.
- **Reserve.** Admission is one short `READ COMMITTED` transaction. A transaction-level
  advisory lock (`pg_advisory_xact_lock`, never a session lock) serialises one owner's
  admissions: it sums the window, refuses if the sum plus the reservation exceeds the budget,
  and otherwise adds the reservation with one `INSERT ... ON CONFLICT DO UPDATE SET tokens =
  <table>.tokens + EXCLUDED.tokens`. Concurrent admissions on any replica therefore cannot
  admit more than the budget holds.
- **Settle.** After the run (success, failure, timeout, cancellation, disconnect) the
  difference between the real usage and the reservation is written atomically: an upsert when
  the run used more, a clamped decrement of the reservation's minute when it used less. It is
  shielded from cancellation and never raises. Each reservation has an id, and the write
  records it in `neuron_token_settlements` in the same transaction, so a retry after an
  ambiguous `COMMIT` (committed, reply lost) finds the id and changes nothing: a settlement
  is applied exactly once and a retry can never under-charge.
- **Pool use.** At most `max_concurrent_reserves_per_owner` reserves of one owner hold or
  wait for a pool connection at once (a bounded in-process gate, waiting up to 5 s before
  failing closed), so one principal's burst, parked on the owner lock, cannot drain the pool.
- **Failure.** Every timestamp is the database's (`clock_timestamp()`). Admission fails closed:
  any database error is a `PersistenceError` (`503 persistence_error`) before the model is
  called. A settlement that cannot be written is counted
  (`neuron.token_budget.settle_failures`), kept in this process, and retried at that owner's
  next admission, which fails closed until it is written. A reservation stays counted until
  settled, so a lost settlement over-charges and never under-charges, except for usage beyond
  the reservation, and a crash loses the retry (the reservation still counts). A reserve
  cancelled after its commit also leaves its reservation counted until the window passes.
- **What it bounds.** The budget is enforced at admission against reservations and settled
  afterwards; nothing stops a run mid-way, so a run can exceed its reservation by its real
  cost (iterations, history, tool output) and the excess is charged at settlement.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
import structlog
from psycopg_pool import AsyncConnectionPool

from neuron_agent.errors.base import PersistenceError
from neuron_agent.observability import metrics
from neuron_agent.security.usage_budget import BudgetDecision, BudgetReservation

logger = structlog.get_logger(__name__)

DEFAULT_LOCK_TIMEOUT_MS = 2_000
DEFAULT_STATEMENT_TIMEOUT_MS = 5_000
# A minute's bucket is counted until its end plus the window has passed.
BUCKET_SECONDS = 60
# Never delete ledger rows younger than this, whatever window the prune job is configured with.
PRUNE_FLOOR_SECONDS = 3600
# How long a reserve may wait for its owner's gate before it fails closed.
GATE_WAIT_SECONDS = 5.0

_ISOLATION = "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"
_TIMEOUTS = "SELECT set_config('lock_timeout', %s, true), set_config('statement_timeout', %s, true)"
_OWNER_LOCK = "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))"
_WINDOW = (
    "SELECT tokens, extract(epoch FROM minute + make_interval(secs => %(span)s)"
    " - clock_timestamp()) AS seconds_left"
    " FROM neuron_token_ledger"
    " WHERE owner_key = %(owner)s AND minute > clock_timestamp() - make_interval(secs => %(span)s)"
    " ORDER BY minute"
)
_CHARGE = (
    "INSERT INTO neuron_token_ledger AS l (owner_key, minute, tokens)"
    " VALUES (%s, date_trunc('minute', clock_timestamp()), %s)"
    " ON CONFLICT (owner_key, minute) DO UPDATE SET tokens = l.tokens + EXCLUDED.tokens"
    " RETURNING minute"
)
_SETTLED = (
    "INSERT INTO neuron_token_settlements (reservation_id) VALUES (%s)"
    " ON CONFLICT (reservation_id) DO NOTHING RETURNING 1"
)
_RELEASE = (
    "UPDATE neuron_token_ledger SET tokens = GREATEST(tokens - %s, 0)"
    " WHERE owner_key = %s AND minute = %s"
)
_DELETE_OUTSIDE_WINDOW = (
    "DELETE FROM neuron_token_ledger WHERE minute <= clock_timestamp() - make_interval(secs => %s)"
)
_DELETE_SETTLEMENTS = (
    "DELETE FROM neuron_token_settlements"
    " WHERE settled_at <= clock_timestamp() - make_interval(secs => %s)"
)


@dataclass(frozen=True)
class _Handle:
    minute: datetime | None
    reservation_id: uuid.UUID


class _Gate:
    def __init__(self, size: int) -> None:
        self.semaphore = asyncio.Semaphore(size)
        self.users = 0


class PostgresTokenBudget:
    """The shared token ledger; see the module docstring."""

    def __init__(
        self,
        pool: AsyncConnectionPool[Any],
        *,
        token_limit: int,
        window_seconds: int,
        lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
        statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
        max_concurrent_reserves_per_owner: int = 4,
    ) -> None:
        if token_limit < 1 or window_seconds < 1:
            raise ValueError("token_limit and window_seconds must be >= 1")
        self._pool = pool
        self._token_limit = token_limit
        self._span = float(window_seconds + BUCKET_SECONDS)
        self._timeouts = (f"{lock_timeout_ms}ms", f"{statement_timeout_ms}ms")
        # Settlements the ledger refused, by owner, retried at that owner's next admission.
        self._unsettled: dict[str, list[tuple[BudgetReservation, int]]] = {}
        self._retry_locks: dict[str, _Gate] = {}
        self._gates: dict[str, _Gate] = {}  # only owners with a reserve in flight
        self._per_owner = max(1, max_concurrent_reserves_per_owner)

    async def reserve(self, key: str, tokens: int) -> BudgetDecision:
        held = min(max(tokens, 1), self._token_limit)
        if self._unsettled.get(key):
            await self._retry_unsettled(key)
        async with self._gate(key), self._transaction() as conn:
            await conn.execute(_OWNER_LOCK, (f"neuron.token_budget:{key}",))
            cursor = await conn.execute(_WINDOW, {"span": self._span, "owner": key})
            rows = await cursor.fetchall()
            used = sum(int(row["tokens"]) for row in rows)
            if used + held > self._token_limit:
                retry_after = 1
                for row in rows:
                    used -= int(row["tokens"])
                    if used + held <= self._token_limit:
                        retry_after = max(1, math.ceil(float(row["seconds_left"])))
                        break
                return BudgetDecision(allowed=False, retry_after_seconds=retry_after)
            cursor = await conn.execute(_CHARGE, (key, held))
            row = await cursor.fetchone()
        handle = _Handle(row["minute"] if row else None, uuid.uuid4())
        return BudgetDecision(allowed=True, reservation=BudgetReservation(key, held, handle))

    async def settle(self, reservation: BudgetReservation, actual_tokens: int) -> None:
        if reservation.settled:
            return
        reservation.settled = True
        await asyncio.shield(self._settle(reservation, max(actual_tokens, 0)))

    async def _settle(self, reservation: BudgetReservation, actual: int) -> None:
        try:
            await self._write(reservation, actual)
        except Exception as exc:  # noqa: BLE001 - the answer is delivered whatever happens here
            metrics.record_budget_settle_failure()
            logger.warning("token_budget_settle_failed", error_type=type(exc).__name__)
            self._unsettled.setdefault(reservation.key, []).append((reservation, actual))

    async def _write(self, reservation: BudgetReservation, actual: int) -> None:
        extra = actual - reservation.tokens
        handle = reservation.handle
        if extra == 0 or not isinstance(handle, _Handle):
            return
        async with self._transaction() as conn:
            # The id and the change commit together; a replay finds the id and does nothing.
            cursor = await conn.execute(_SETTLED, (handle.reservation_id,))
            if await cursor.fetchone() is None:
                return
            if extra > 0:
                await conn.execute(_CHARGE, (reservation.key, extra))
            elif handle.minute is not None:
                await conn.execute(_RELEASE, (-extra, reservation.key, handle.minute))

    async def _retry_unsettled(self, key: str) -> None:
        """Write the owner's refused settlements, or fail closed (raises `PersistenceError`)."""
        lock = self._retry_locks.setdefault(key, _Gate(1))  # one owner never blocks another
        lock.users += 1  # the lock is dropped only when its last user is done with it
        try:
            async with lock.semaphore:
                pending = self._unsettled.get(key, [])
                while pending:
                    entry = pending[0]
                    await self._write(*entry)
                    pending.remove(entry)  # that exact entry, not whatever is first now
                if not pending:  # a settlement that failed meanwhile is appended, never lost
                    self._unsettled.pop(key, None)
        finally:
            lock.users -= 1
            if lock.users == 0:
                self._retry_locks.pop(key, None)

    @asynccontextmanager
    async def _gate(self, key: str) -> AsyncIterator[None]:
        """Limit one owner's reserves in flight; fails closed after `GATE_WAIT_SECONDS`."""
        gate = self._gates.setdefault(key, _Gate(self._per_owner))
        gate.users += 1
        try:
            try:
                async with asyncio.timeout(GATE_WAIT_SECONDS):
                    await gate.semaphore.acquire()
            except TimeoutError:
                raise PersistenceError("token budget unavailable") from None
            try:
                yield
            finally:
                gate.semaphore.release()
        finally:
            gate.users -= 1
            if gate.users == 0:
                self._gates.pop(key, None)

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
        """A budget transaction. A database failure of any kind fails closed."""
        try:
            async with self._pool.connection() as conn:
                async with conn.transaction():
                    await conn.execute(_ISOLATION)
                    await conn.execute(_TIMEOUTS, self._timeouts)
                    yield conn
        except PersistenceError:
            raise
        except Exception as exc:  # noqa: BLE001 - psycopg, OS and timeout failures all fail closed
            logger.warning("token_budget_unavailable", error_type=type(exc).__name__)
            raise PersistenceError("token budget unavailable") from exc


async def delete_ledger_outside_window(
    pool: AsyncConnectionPool[Any],
    window_seconds: int,
    *,
    lock_timeout_ms: int = DEFAULT_LOCK_TIMEOUT_MS,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
) -> int:
    """Delete ledger minutes no admission counts any more (the retention job).

    The window must be the replicas' own; a floor of `PRUNE_FLOOR_SECONDS` keeps a job with a
    shorter configured window from deleting usage an admission still counts.
    """
    span = float(max(window_seconds, PRUNE_FLOOR_SECONDS) + BUCKET_SECONDS)
    async with pool.connection() as conn:
        async with conn.transaction():
            await conn.execute(_TIMEOUTS, (f"{lock_timeout_ms}ms", f"{statement_timeout_ms}ms"))
            cursor = await conn.execute(_DELETE_OUTSIDE_WINDOW, (span,))
            await conn.execute(_DELETE_SETTLEMENTS, (span,))
            return int(cursor.rowcount)
