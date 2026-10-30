"""Per-user memory on Postgres (#245, ADR 0009 decision 7): schema, grants, readiness, processes."""

from __future__ import annotations

import os
import subprocess  # nosec B404 - runs this interpreter on a fixed snippet
import sys
import textwrap
from typing import Any

import psycopg
import pytest
from pydantic import SecretStr
from test_postgres_roles import RoleDatabase, _denied, _rows, _setup, role_db, roles  # noqa: F401

from neuron_agent.config.settings import Settings
from neuron_agent.memory.store import MemoryStore
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.migrations import run_setup

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_ALICE = "a" * 64
_BOB = "b" * 64


async def _run(dsn: str, statement: str) -> None:
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        await conn.execute(statement)  # type: ignore[call-overload]


def _settings(db: RoleDatabase, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "checkpointer": "postgres",
        "postgres_dsn": SecretStr(db.app_dsn),
        "memory_enabled": True,
    }
    return Settings(**{**values, **overrides})


async def test_the_store_tables_exist_only_when_memory_is_set_up(database: str) -> None:
    assert await _rows(database, "SELECT to_regclass('store')") == [(None,)]
    await run_setup(database, memory_store=True)
    assert await _rows(database, "SELECT to_regclass('store')::text") == [("store",)]


async def test_the_app_role_gets_dml_on_the_store_and_nothing_else(role_db: RoleDatabase) -> None:  # noqa: F811
    await _setup(role_db, memory_store=True)
    app = role_db.app_dsn

    await _run(app, "INSERT INTO store (prefix, key, value) VALUES ('memories.x', 'k', '{}')")
    assert await _rows(app, "SELECT key FROM store WHERE prefix = 'memories.x'") == [("k",)]
    await _run(app, "UPDATE store SET value = '{\"a\": 1}' WHERE key = 'k'")
    await _run(app, "DELETE FROM store WHERE key = 'k'")
    for statement in (
        "TRUNCATE store",
        "DROP TABLE store",
        "ALTER TABLE store ADD COLUMN extra text",
        "SELECT * FROM store_migrations",
        "CREATE TABLE intruder (id int)",
    ):
        await _denied(app, statement)


async def test_memory_survives_across_processes_and_users_stay_apart(
    role_db: RoleDatabase,  # noqa: F811
) -> None:
    await _setup(role_db, memory_store=True)
    snippet = textwrap.dedent(
        """
        import asyncio, os
        from pydantic import SecretStr
        from neuron_agent.config.settings import Settings
        from neuron_agent.memory.store import MemoryStore
        from neuron_agent.persistence.checkpointer import build_persistence

        async def main():
            settings = Settings(env="test", checkpointer="postgres", memory_enabled=True,
                                postgres_dsn=SecretStr(os.environ["MEMORY_TEST_DSN"]))
            persistence = build_persistence(settings)
            await persistence.open()
            try:
                memory = MemoryStore(
                    persistence.store, id_key=b"k" * 32, max_items=5, max_chars=100
                )
                owner = os.environ["MEMORY_TEST_OWNER"]
                await memory.remember(owner, "written by another process")
            finally:
                await persistence.close()

        asyncio.run(main())
        """
    )
    env = {**os.environ, "MEMORY_TEST_DSN": role_db.app_dsn, "MEMORY_TEST_OWNER": _ALICE}
    subprocess.run(  # noqa: S603 - fixed interpreter and snippet  # nosec B603
        [sys.executable, "-c", snippet], env=env, check=True, timeout=60
    )

    persistence = build_persistence(_settings(role_db))
    await persistence.open()
    try:
        assert persistence.store is not None
        memory = MemoryStore(persistence.store, id_key=b"k" * 32, max_items=5, max_chars=100)
        assert [m.text for m in await memory.list(_ALICE)] == ["written by another process"]
        assert await memory.list(_BOB) == []
        # Idempotent across processes too: the same words are the same row.
        again = await memory.remember(_ALICE, "Written by ANOTHER process")
        assert [m.id for m in await memory.list(_ALICE)] == [again.id]
        assert await memory.erase(_ALICE) == 1
    finally:
        await persistence.close()


async def test_readiness_needs_the_store_table_when_memory_is_on(role_db: RoleDatabase) -> None:  # noqa: F811
    await _setup(role_db)  # memory not set up
    persistence = build_persistence(_settings(role_db))
    await persistence.open()
    try:
        assert await persistence.is_ready() is False
    finally:
        await persistence.close()

    await _setup(role_db, memory_store=True)
    persistence = build_persistence(_settings(role_db))
    await persistence.open()
    try:
        assert await persistence.is_ready() is True
    finally:
        await persistence.close()


async def test_readiness_ignores_the_store_when_memory_is_off(role_db: RoleDatabase) -> None:  # noqa: F811
    await _setup(role_db)
    persistence = build_persistence(_settings(role_db, memory_enabled=False))
    await persistence.open()
    try:
        assert persistence.store is None
        assert await persistence.is_ready() is True
    finally:
        await persistence.close()


async def test_cli_setup_flag_follows_the_setting(
    role_db: RoleDatabase,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from neuron_agent.persistence import cli

    migrated: list[bool] = []
    real = cli.migrations.run_setup

    async def spy(*args: Any, **kwargs: Any) -> list[int]:
        migrated.append(kwargs["memory_store"])
        return await real(*args, **kwargs)

    monkeypatch.setattr(cli.migrations, "run_setup", spy)
    settings = Settings(
        env="test", postgres_migration_dsn=SecretStr(role_db.migrator_dsn), memory_enabled=True
    )
    import anyio

    await anyio.to_thread.run_sync(lambda: cli._setup(settings, rotate_identity_key=False))
    assert migrated == [True]
    assert await _rows(role_db.migrator_dsn, "SELECT to_regclass('store')::text") == [("store",)]


async def test_hardened_start_up_refuses_a_database_without_the_memory_store(
    role_db: RoleDatabase,  # noqa: F811
) -> None:
    from neuron_agent.persistence.startup_checks import STORE_MISSING, StartupCheckError

    await _setup(role_db)  # memory not set up
    persistence = build_persistence(_settings(role_db))
    persistence.check_store = True  # what staging and production set
    with pytest.raises(StartupCheckError) as caught:
        await persistence.open()
    assert caught.value.code == STORE_MISSING

    await _setup(role_db, memory_store=True)
    persistence = build_persistence(_settings(role_db))
    persistence.check_store = True
    await persistence.open()  # the app role has DML on the table: allowed
    await persistence.close()


async def test_hardened_start_up_refuses_a_role_without_access_to_the_store(
    role_db: RoleDatabase,  # noqa: F811
) -> None:
    from neuron_agent.persistence.startup_checks import STORE_NO_ACCESS, StartupCheckError

    await _setup(role_db, memory_store=True)
    async with await psycopg.AsyncConnection.connect(role_db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(f'REVOKE ALL ON store FROM "{role_db.roles.app}"')  # nosec B608
    persistence = build_persistence(_settings(role_db))
    persistence.check_store = True
    with pytest.raises(StartupCheckError) as caught:
        await persistence.open()
    assert caught.value.code == STORE_NO_ACCESS
