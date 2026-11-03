"""Knowledge storage foundation on Postgres (RAG-01.01, ADR 0014).

Needs a server with pgvector available (the pinned `pgvector/pgvector:pg16` image, as in CI).
Each test gets a fresh database, so the `vector` extension starts uninstalled.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from pydantic import SecretStr
from test_postgres_migrations import dsn  # noqa: F401
from test_postgres_roles import RoleDatabase, _rows, _setup, role_db, roles  # noqa: F401

from neuron_agent.config.settings import Settings
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.migrations import MIGRATIONS, run_setup
from neuron_agent.persistence.startup_checks import (
    KNOWLEDGE_SCHEMA_MISSING,
    KNOWLEDGE_SCHEMA_UNTRUSTED,
    VECTOR_EXTENSION_MISSING,
    StartupCheckError,
)

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_KNOWLEDGE = 17
_EXTENSION = "SELECT count(*) FROM pg_extension WHERE extname = 'vector'"
_SCHEMA = "SELECT to_regnamespace('knowledge') IS NOT NULL"


async def _superuser(db: RoleDatabase, statement: str) -> None:
    """What the operator (or the reference stack's init script) runs before setup."""
    from psycopg.conninfo import make_conninfo
    from test_postgres_roles import _DSN

    assert _DSN
    dsn_ = make_conninfo(_DSN, dbname=db.name)
    async with await psycopg.AsyncConnection.connect(dsn_, autocommit=True) as conn:
        await conn.execute(statement)  # type: ignore[call-overload]


def _settings(db: RoleDatabase, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "checkpointer": "postgres",
        "postgres_dsn": SecretStr(db.app_dsn),
        "knowledge_enabled": True,
    }
    return Settings(**{**values, **overrides})


async def test_setup_creates_the_extension_and_schema_once(dsn: str) -> None:  # noqa: F811
    applied = await run_setup(dsn, knowledge=True)
    assert applied == [m.version for m in MIGRATIONS]
    assert await _rows(dsn, _EXTENSION) == [(1,)]
    assert await _rows(dsn, _SCHEMA) == [(True,)]
    assert await run_setup(dsn, knowledge=True) == []
    assert await _rows(
        dsn, "SELECT count(*) FROM neuron_migrations WHERE version = %s", (_KNOWLEDGE,)
    ) == [(1,)]


async def test_without_knowledge_setup_is_as_in_v1_0_0(dsn: str) -> None:  # noqa: F811
    applied = await run_setup(dsn)
    assert _KNOWLEDGE not in applied
    assert applied == [m.version for m in MIGRATIONS if m.feature is None]
    assert await _rows(dsn, _EXTENSION) == [(0,)]
    assert await _rows(dsn, _SCHEMA) == [(False,)]
    # Turning knowledge on later applies only its migration.
    assert await run_setup(dsn, knowledge=True) == [_KNOWLEDGE]


async def test_the_migrator_cannot_create_the_extension_and_setup_names_it(
    role_db: RoleDatabase,  # noqa: F811
) -> None:
    with pytest.raises(StartupCheckError) as caught:
        await _setup(role_db, knowledge=True)
    assert caught.value.code == VECTOR_EXTENSION_MISSING
    assert await _rows(role_db.migrator_dsn, _SCHEMA) == [(False,)]
    assert await _rows(
        role_db.migrator_dsn,
        "SELECT count(*) FROM neuron_migrations WHERE version = %s",
        (_KNOWLEDGE,),
    ) == [(0,)]

    await _superuser(role_db, "CREATE EXTENSION vector")
    with pytest.raises(StartupCheckError) as caught:
        await _setup(role_db, knowledge=True)
    assert caught.value.code == KNOWLEDGE_SCHEMA_MISSING

    # The operator's one-off superuser step (OPERATIONS.md, "Database roles").
    await _superuser(role_db, f'CREATE SCHEMA knowledge AUTHORIZATION "{role_db.roles.migrator}"')
    assert _KNOWLEDGE in await _setup(role_db, knowledge=True, require_app_role=True)
    app, migrator = role_db.roles.app, role_db.roles.migrator
    # The migrator owns the schema; the app role cannot create objects in it.
    assert await _rows(
        role_db.migrator_dsn,
        "SELECT pg_get_userbyid(nspowner)::text, has_schema_privilege(%s, oid, 'CREATE')"
        " FROM pg_namespace WHERE nspname = 'knowledge'",
        (app,),
    ) == [(migrator, False)]


async def test_start_up_and_readiness_need_the_extension_and_schema(
    role_db: RoleDatabase,  # noqa: F811
) -> None:
    await _setup(role_db)  # knowledge never set up

    # Staging and production: start-up fails and names the extension.
    persistence = build_persistence(_settings(role_db))
    persistence.check_knowledge = True  # what staging and production set
    with pytest.raises(StartupCheckError) as caught:
        await persistence.open()
    assert caught.value.code == VECTOR_EXTENSION_MISSING
    assert "vector extension" in str(caught.value)

    # Development: it starts, but readiness reports the failing check.
    persistence = build_persistence(_settings(role_db))
    await persistence.open()
    try:
        assert await persistence.is_ready() is False
    finally:
        await persistence.close()

    await _superuser(role_db, "CREATE EXTENSION vector")
    persistence = build_persistence(_settings(role_db))
    persistence.check_knowledge = True
    with pytest.raises(StartupCheckError) as caught:
        await persistence.open()
    assert caught.value.code == KNOWLEDGE_SCHEMA_MISSING

    await _superuser(role_db, f'CREATE SCHEMA knowledge AUTHORIZATION "{role_db.roles.migrator}"')
    await _setup(role_db, knowledge=True)
    persistence = build_persistence(_settings(role_db))
    persistence.check_knowledge = True
    await persistence.open()
    try:
        assert await persistence.is_ready() is True
    finally:
        await persistence.close()


async def test_knowledge_off_ignores_the_missing_extension(role_db: RoleDatabase) -> None:  # noqa: F811
    await _setup(role_db)
    persistence = build_persistence(_settings(role_db, knowledge_enabled=False))
    assert persistence.check_knowledge is False
    await persistence.open()
    try:
        assert await persistence.is_ready() is True
    finally:
        await persistence.close()


async def test_setup_and_production_start_up_refuse_an_untrusted_schema(
    role_db: RoleDatabase,  # noqa: F811
) -> None:
    app = role_db.roles.app
    await _superuser(role_db, "CREATE EXTENSION vector")
    # A superuser made the schema without AUTHORIZATION: someone else owns it.
    await _superuser(role_db, "CREATE SCHEMA knowledge")
    with pytest.raises(StartupCheckError) as caught:
        await _setup(role_db, knowledge=True)
    assert caught.value.code == KNOWLEDGE_SCHEMA_UNTRUSTED

    await _superuser(role_db, f'ALTER SCHEMA knowledge OWNER TO "{role_db.roles.migrator}"')
    for grantee in ("PUBLIC", f'"{app}"'):
        await _superuser(role_db, f"GRANT CREATE ON SCHEMA knowledge TO {grantee}")
        with pytest.raises(StartupCheckError) as caught:
            await _setup(role_db, knowledge=True)
        assert caught.value.code == KNOWLEDGE_SCHEMA_UNTRUSTED

        # Production start-up refuses a runtime role that can create in the schema.
        persistence = build_persistence(_settings(role_db))
        persistence.check_knowledge = True
        persistence.app_role = app
        with pytest.raises(StartupCheckError) as caught:
            await persistence.open()
        assert caught.value.code == KNOWLEDGE_SCHEMA_UNTRUSTED
        await _superuser(role_db, f"REVOKE CREATE ON SCHEMA knowledge FROM {grantee}")

    await _setup(role_db, knowledge=True)
    persistence = build_persistence(_settings(role_db))
    persistence.check_knowledge = True
    persistence.app_role = app
    await persistence.open()
    await persistence.close()
