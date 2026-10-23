# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""neuron's own schema migrations, recorded in `neuron_migrations` (ADR 0008 decision 7).

LangGraph's `AsyncPostgresSaver.setup()` owns the checkpoint tables. Everything neuron adds
on top is an ordered `Migration` here, applied after LangGraph's `setup()` by `run_setup`.

Compatibility rule (expand/contract): a release's migrations must leave the previous release
working. Add tables, nullable columns and concurrent indexes; remove or rename only in a
later release, as a migration with `contract_release` naming the release whose image stopped
using the old shape. There are no down-migrations: rollback is redeploying the previous image.
`tests/unit/test_migrations_policy.py` enforces the rule.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass

import psycopg
import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import sql
from psycopg.rows import dict_row

logger = structlog.get_logger(__name__)

# DDL waits at most this long for a lock, so a migration behind live traffic fails the
# deploy instead of queueing every request behind it.
DEFAULT_LOCK_TIMEOUT_MS = 5000
# `CREATE INDEX CONCURRENTLY` also waits for every older transaction to finish, and
# `lock_timeout` covers those waits, so the 5 s above would fail the deploy (and leave an
# INVALID index) whenever a session sits idle in a transaction. Concurrent migrations run
# under this longer bound instead: 10 minutes, long enough for a slow transaction to end,
# short enough that a stuck one still fails the deploy rather than hanging it.
CONCURRENT_LOCK_TIMEOUT_MS = 600_000
# How long a second `setup` waits for the first to finish before giving up.
LOCK_WAIT_SECONDS = 300.0
# Session-level advisory lock on the direct (never pooled) migration connection: "neuron".
_ADVISORY_LOCK_KEY = 0x6E6575726F6E

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS neuron_migrations (
    version integer PRIMARY KEY,
    name text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


class LockWaitTimeout(TimeoutError):
    """Another `setup` held the advisory lock for the whole wait. The text is fixed."""


@dataclass(frozen=True)
class Migration:
    """One schema change.

    `concurrent` migrations hold a single `CREATE INDEX CONCURRENTLY` statement and run
    outside a transaction; others run in one transaction together with their record.
    `index` names an index the migration builds, so an `INVALID` leftover can be rebuilt.
    `contract_release` marks a contract step (see the module docstring).
    """

    version: int
    name: str
    sql: str
    concurrent: bool = False
    index: str | None = None
    contract_release: str | None = None


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version=1,
        name="owner_index",
        # Serves the per-owner thread listing (`persistence/thread_index.py`) on the table
        # LangGraph owns.
        sql="""
CREATE INDEX CONCURRENTLY IF NOT EXISTS neuron_checkpoints_owner_idx
ON checkpoints ((metadata->>'owner'), thread_id)
WHERE checkpoint_ns = ''
""",
        concurrent=True,
        index="neuron_checkpoints_owner_idx",
    ),
    Migration(
        version=2,
        name="run_leases",
        # Shared run guard (`persistence/run_guard.py`, ADR 0008 decision 8). The unique
        # constraint on `thread_id` is what makes a second run on a thread fail; a NULL
        # `thread_id` (no persistence) never conflicts. `kind` separates runs, which count
        # against the per-owner cap, from a thread held for deletion, which does not.
        sql="""
CREATE TABLE IF NOT EXISTS neuron_run_leases (
    lease_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_key text NOT NULL,
    thread_id text UNIQUE,
    kind text NOT NULL DEFAULT 'run' CHECK (kind IN ('run', 'delete')),
    expires_at timestamptz NOT NULL
)
""",
    ),
    # Serve the per-owner count and listing, and the expiry sweep, on the table above.
    Migration(
        version=3,
        name="run_leases_owner_idx",
        sql="""
CREATE INDEX CONCURRENTLY IF NOT EXISTS neuron_run_leases_owner_idx
ON neuron_run_leases (owner_key)
""",
        concurrent=True,
        index="neuron_run_leases_owner_idx",
    ),
    Migration(
        version=4,
        name="run_leases_expires_idx",
        sql="""
CREATE INDEX CONCURRENTLY IF NOT EXISTS neuron_run_leases_expires_idx
ON neuron_run_leases (expires_at)
""",
        concurrent=True,
        index="neuron_run_leases_expires_idx",
    ),
    Migration(
        version=5,
        name="token_ledger",
        # Shared token budget (`persistence/token_budget.py`, ADR 0008 decision 8): tokens
        # charged per owner per database-clock minute. Logged (not UNLOGGED): a budget must
        # survive a crash. The primary key is what the atomic upsert conflicts on.
        sql="""
CREATE TABLE IF NOT EXISTS neuron_token_ledger (
    owner_key text NOT NULL,
    minute timestamptz NOT NULL,
    tokens bigint NOT NULL DEFAULT 0 CHECK (tokens >= 0),
    PRIMARY KEY (owner_key, minute)
)
""",
    ),
    # Serves the retention job's delete of minutes outside the window.
    Migration(
        version=6,
        name="token_ledger_minute_idx",
        sql="""
CREATE INDEX CONCURRENTLY IF NOT EXISTS neuron_token_ledger_minute_idx
ON neuron_token_ledger (minute)
""",
        concurrent=True,
        index="neuron_token_ledger_minute_idx",
    ),
    Migration(
        version=7,
        name="token_settlements",
        # One row per settled reservation, written in the same transaction as the ledger
        # change, so a settlement replayed after an ambiguous COMMIT changes nothing.
        sql="""
CREATE TABLE IF NOT EXISTS neuron_token_settlements (
    reservation_id uuid PRIMARY KEY,
    settled_at timestamptz NOT NULL DEFAULT clock_timestamp()
)
""",
    ),
    # Serves the retention job's delete of old settlement rows.
    Migration(
        version=8,
        name="token_settlements_settled_idx",
        sql="""
CREATE INDEX CONCURRENTLY IF NOT EXISTS neuron_token_settlements_settled_idx
ON neuron_token_settlements (settled_at)
""",
        concurrent=True,
        index="neuron_token_settlements_settled_idx",
    ),
)


async def run_setup(
    dsn: str,
    *,
    migrations: Sequence[Migration] | None = None,
    lock_timeout_ms: int | None = None,
    concurrent_lock_timeout_ms: int | None = None,
    lock_wait_seconds: float = LOCK_WAIT_SECONDS,
) -> list[int]:
    """Run LangGraph's `setup()`, then every unapplied migration. Returns the versions applied.

    One direct connection holds a session-level advisory lock for the whole run, so
    concurrent `setup` runs serialise and each migration is applied once. Raises on any
    failure; callers must not print the exception text, which can echo connection details.
    """
    timeout_ms = DEFAULT_LOCK_TIMEOUT_MS if lock_timeout_ms is None else lock_timeout_ms
    concurrent_ms = (
        CONCURRENT_LOCK_TIMEOUT_MS
        if concurrent_lock_timeout_ms is None
        else concurrent_lock_timeout_ms
    )
    conn = await psycopg.AsyncConnection.connect(
        dsn, autocommit=True, row_factory=dict_row, prepare_threshold=None
    )
    try:
        await _acquire_lock(conn, lock_wait_seconds)
        await _set_lock_timeout(conn, timeout_ms)
        await AsyncPostgresSaver(conn).setup()
        await conn.execute(_CREATE_TABLE_SQL)
        return await _apply(
            conn, MIGRATIONS if migrations is None else migrations, timeout_ms, concurrent_ms
        )
    finally:
        await conn.close()  # also releases the session advisory lock


async def _acquire_lock(conn: psycopg.AsyncConnection[dict[str, object]], wait: float) -> None:
    deadline = time.monotonic() + wait
    while True:
        cursor = await conn.execute("SELECT pg_try_advisory_lock(%s) AS ok", (_ADVISORY_LOCK_KEY,))
        row = await cursor.fetchone()
        if row is not None and row["ok"]:
            return
        if time.monotonic() >= deadline:
            raise LockWaitTimeout("another setup held the migration lock for too long")
        await asyncio.sleep(0.2)


async def _set_lock_timeout(conn: psycopg.AsyncConnection[dict[str, object]], ms: int) -> None:
    await conn.execute("SELECT set_config('lock_timeout', %s, false)", (f"{ms}ms",))


async def _apply(
    conn: psycopg.AsyncConnection[dict[str, object]],
    migrations: Sequence[Migration],
    timeout_ms: int,
    concurrent_ms: int,
) -> list[int]:
    cursor = await conn.execute("SELECT version FROM neuron_migrations")
    done = {row["version"] for row in await cursor.fetchall()}
    applied: list[int] = []
    for migration in migrations:
        recorded = migration.version in done
        if migration.index and await _index_is_invalid(conn, migration.index):
            # `IF NOT EXISTS` would skip a leftover from a failed concurrent build.
            logger.warning("invalid_index_rebuilt", index=migration.index)
            # DROP INDEX CONCURRENTLY waits on older transactions too.
            await _set_lock_timeout(conn, concurrent_ms)
            try:
                await conn.execute(
                    sql.SQL("DROP INDEX CONCURRENTLY IF EXISTS {}").format(
                        sql.Identifier(migration.index)
                    )
                )
            finally:
                await _set_lock_timeout(conn, timeout_ms)
            recorded = False
        if recorded:
            continue
        if migration.concurrent:
            await _set_lock_timeout(conn, concurrent_ms)
            try:
                await conn.execute(migration.sql)
            finally:
                await _set_lock_timeout(conn, timeout_ms)
            await _record(conn, migration)
        else:
            async with conn.transaction():
                await conn.execute(migration.sql)
                await _record(conn, migration)
        applied.append(migration.version)
        logger.info("migration_applied", version=migration.version, name=migration.name)
    return applied


async def _index_is_invalid(conn: psycopg.AsyncConnection[dict[str, object]], name: str) -> bool:
    cursor = await conn.execute(
        "SELECT NOT i.indisvalid AS invalid FROM pg_index i WHERE i.indexrelid = to_regclass(%s)",
        (name,),
    )
    row = await cursor.fetchone()
    return bool(row and row["invalid"])


async def _record(conn: psycopg.AsyncConnection[dict[str, object]], migration: Migration) -> None:
    await conn.execute(
        "INSERT INTO neuron_migrations (version, name) VALUES (%s, %s) "
        "ON CONFLICT (version) DO NOTHING",
        (migration.version, migration.name),
    )
