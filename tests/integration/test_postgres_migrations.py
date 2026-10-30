from __future__ import annotations

import asyncio
import os
import subprocess  # nosec B404 - runs this repo's own CLI
import sys
import time
import uuid
from collections.abc import AsyncIterator

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from neuron_agent.persistence.migrations import MIGRATIONS, Migration, run_setup

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_DSN = os.environ.get("APP_TEST_POSTGRES_DSN")
_INDEX = "neuron_checkpoints_owner_idx"
# The version after the last real migration, derived so a new migration never collides.
NEXT = max(m.version for m in MIGRATIONS) + 1
_SCRATCH = Migration(version=NEXT, name="scratch", sql="CREATE TABLE neuron_scratch (a int)")
_COUNTED = Migration(
    version=NEXT,
    name="counted",
    # Not idempotent: a second application would add a second row.
    sql="CREATE TABLE IF NOT EXISTS neuron_counted (a int); INSERT INTO neuron_counted VALUES (1)",
)


@pytest.fixture
async def dsn() -> AsyncIterator[str]:
    """A fresh, empty database per test, so nothing depends on the shared one's state."""
    if not _DSN:
        pytest.skip("APP_TEST_POSTGRES_DSN is not set; see OPERATIONS.md for a local Postgres.")
    name = f"neuron_mig_{uuid.uuid4().hex[:12]}"
    async with await psycopg.AsyncConnection.connect(_DSN, autocommit=True) as admin:
        await admin.execute(f'CREATE DATABASE "{name}"')  # nosec B608 - generated name
        try:
            yield make_conninfo(_DSN, dbname=name)
        finally:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')  # nosec B608


async def _scalar(dsn: str, sql: str) -> object:
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        cursor = await conn.execute(sql)  # type: ignore[call-overload]
        row = await cursor.fetchone()
        return row[0] if row else None


async def test_setup_applies_all_then_none_then_only_later_ones(dsn: str) -> None:
    every = [m.version for m in MIGRATIONS]
    assert await run_setup(dsn) == every
    assert await run_setup(dsn) == []
    assert await _scalar(dsn, "SELECT count(*) FROM neuron_migrations") == len(every)
    assert await _scalar(dsn, f"SELECT to_regclass('{_INDEX}') IS NOT NULL") is True

    # A database at migration N gets only the later ones.
    assert await run_setup(dsn, migrations=[*MIGRATIONS, _SCRATCH]) == [NEXT]
    assert await run_setup(dsn, migrations=[*MIGRATIONS, _SCRATCH]) == []
    assert await _scalar(dsn, "SELECT max(version) FROM neuron_migrations") == NEXT


async def test_concurrent_setups_apply_each_migration_once(dsn: str) -> None:
    both = [*MIGRATIONS, _COUNTED]
    results = await asyncio.gather(run_setup(dsn, migrations=both), run_setup(dsn, migrations=both))
    assert sorted(results, key=len) == [[], [m.version for m in both]]
    assert await _scalar(dsn, "SELECT count(*) FROM neuron_counted") == 1
    assert await _scalar(dsn, "SELECT count(*) FROM neuron_migrations") == len(both)


async def test_concurrent_setup_processes_both_succeed(dsn: str) -> None:
    env = {**os.environ, "APP_ENV": "test", "APP_POSTGRES_MIGRATION_DSN": dsn}
    command = [sys.executable, "-m", "neuron_agent.persistence.cli", "setup"]
    processes = [
        subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # noqa: S603  # nosec B603
        for _ in range(2)
    ]
    outputs = [p.communicate(timeout=120) for p in processes]
    assert [p.returncode for p in processes] == [0, 0], outputs
    assert await _scalar(dsn, "SELECT count(*) FROM neuron_migrations") == len(MIGRATIONS)
    assert dsn not in b"".join(out + err for out, err in outputs).decode()


async def _hold_exclusive_lock(dsn: str) -> psycopg.AsyncConnection[object]:
    blocker = await psycopg.AsyncConnection.connect(dsn)
    await blocker.execute("LOCK TABLE checkpoints IN ACCESS EXCLUSIVE MODE")
    return blocker  # type: ignore[return-value]


async def _unapply_owner_index(dsn: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        await conn.execute(f"DROP INDEX {_INDEX}")  # nosec B608 - constant
        await conn.execute("DELETE FROM neuron_migrations WHERE version = 1")


_PROBE = Migration(
    version=NEXT, name="probe", sql="ALTER TABLE checkpoints ADD COLUMN neuron_probe integer"
)
_CLI_WITH_SHORT_TIMEOUT = (
    "from neuron_agent.persistence import cli, migrations as m;"
    "m.DEFAULT_LOCK_TIMEOUT_MS = 500;"
    "m.MIGRATIONS = (*m.MIGRATIONS, m.Migration(version=max(x.version for x in m.MIGRATIONS) + 1,"
    " name='probe', sql='ALTER TABLE checkpoints ADD COLUMN neuron_probe integer'));"
    "cli.main(['setup'])"
)


async def test_blocked_migration_fails_after_lock_timeout(dsn: str) -> None:
    await run_setup(dsn)
    with_probe = [*MIGRATIONS, _PROBE]
    blocker = await _hold_exclusive_lock(dsn)
    try:
        started = time.monotonic()
        with pytest.raises(psycopg.errors.LockNotAvailable):
            await run_setup(dsn, migrations=with_probe, lock_timeout_ms=500)
        assert 0.4 <= time.monotonic() - started < 10

        # The CLI exits non-zero (so a pre-deploy command cancels the deploy).
        env = {**os.environ, "APP_ENV": "test", "APP_POSTGRES_MIGRATION_DSN": dsn}
        proc = subprocess.run(  # noqa: S603  # nosec B603
            [sys.executable, "-c", _CLI_WITH_SHORT_TIMEOUT],
            env=env,
            capture_output=True,
            timeout=60,
            check=False,
        )
        assert proc.returncode == 1
        assert b"LockNotAvailable" in proc.stderr
    finally:
        await blocker.rollback()
        await blocker.close()
    assert await run_setup(dsn, migrations=with_probe) == [NEXT]  # the failed runs recorded nothing


async def test_concurrent_index_waits_for_an_open_transaction(dsn: str) -> None:
    """`CREATE INDEX CONCURRENTLY` waits on older transactions; it has its own, longer bound."""
    await run_setup(dsn)
    await _unapply_owner_index(dsn)
    reader = await psycopg.AsyncConnection.connect(dsn)
    # A read committed transaction drops its snapshot between statements and blocks nothing;
    # a repeatable read one keeps it, which is what the build has to wait out.
    await reader.set_isolation_level(psycopg.IsolationLevel.REPEATABLE_READ)
    await reader.execute("SELECT count(*) FROM checkpoints")  # idle in transaction from here
    try:
        # Bounded by the concurrent timeout: fails, and leaves an INVALID index behind.
        with pytest.raises(psycopg.errors.LockNotAvailable):
            await run_setup(dsn, lock_timeout_ms=500, concurrent_lock_timeout_ms=500)

        async def release() -> None:
            await asyncio.sleep(1.5)
            await reader.rollback()

        releasing = asyncio.create_task(release())
        started = time.monotonic()
        # The transactional timeout (0.5 s) does not apply; the build waits for the reader.
        assert await run_setup(dsn, lock_timeout_ms=500, concurrent_lock_timeout_ms=30_000) == [1]
        assert time.monotonic() - started >= 1.0
        await releasing
    finally:
        await reader.close()
    valid = (
        "SELECT indisvalid FROM pg_index"
        " WHERE indexrelid = 'neuron_checkpoints_owner_idx'::regclass"
    )
    assert await _scalar(dsn, valid) is True


async def test_invalid_owner_index_is_detected_and_rebuilt(dsn: str) -> None:
    await run_setup(dsn)
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        # What a failed CREATE INDEX CONCURRENTLY leaves behind.
        await conn.execute(
            "UPDATE pg_index SET indisvalid = false"
            " WHERE indexrelid = 'neuron_checkpoints_owner_idx'::regclass"
        )
    check = (
        "SELECT indisvalid FROM pg_index"
        " WHERE indexrelid = 'neuron_checkpoints_owner_idx'::regclass"
    )
    assert await _scalar(dsn, check) is False

    await run_setup(dsn)  # `IF NOT EXISTS` alone would skip it
    assert await _scalar(dsn, check) is True
