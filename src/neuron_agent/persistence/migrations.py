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
)


async def run_setup(
    dsn: str,
    *,
    migrations: Sequence[Migration] = MIGRATIONS,
    lock_timeout_ms: int | None = None,
    lock_wait_seconds: float = LOCK_WAIT_SECONDS,
) -> list[int]:
    """Run LangGraph's `setup()`, then every unapplied migration. Returns the versions applied.

    One direct connection holds a session-level advisory lock for the whole run, so
    concurrent `setup` runs serialise and each migration is applied once. Raises on any
    failure; callers must not print the exception text, which can echo connection details.
    """
    timeout_ms = DEFAULT_LOCK_TIMEOUT_MS if lock_timeout_ms is None else lock_timeout_ms
    conn = await psycopg.AsyncConnection.connect(
        dsn, autocommit=True, row_factory=dict_row, prepare_threshold=None
    )
    try:
        await _acquire_lock(conn, lock_wait_seconds)
        await conn.execute("SELECT set_config('lock_timeout', %s, false)", (f"{timeout_ms}ms",))
        await AsyncPostgresSaver(conn).setup()
        await conn.execute(_CREATE_TABLE_SQL)
        return await _apply(conn, migrations)
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
            raise TimeoutError("another setup held the migration lock for too long")
        await asyncio.sleep(0.2)


async def _apply(
    conn: psycopg.AsyncConnection[dict[str, object]], migrations: Sequence[Migration]
) -> list[int]:
    cursor = await conn.execute("SELECT version FROM neuron_migrations")
    done = {row["version"] for row in await cursor.fetchall()}
    applied: list[int] = []
    for migration in migrations:
        recorded = migration.version in done
        if migration.index and await _index_is_invalid(conn, migration.index):
            # `IF NOT EXISTS` would skip a leftover from a failed concurrent build.
            logger.warning("invalid_index_rebuilt", index=migration.index)
            await conn.execute(
                sql.SQL("DROP INDEX CONCURRENTLY IF EXISTS {}").format(
                    sql.Identifier(migration.index)
                )
            )
            recorded = False
        if recorded:
            continue
        if migration.concurrent:
            await conn.execute(migration.sql)
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
