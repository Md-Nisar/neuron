"""Least-privilege database roles (#144, ADR 0008 decisions 15 and 16).

Each test gets a fresh database and two roles created for the test session (roles are
cluster-level, so their names are unique per session and dropped at the end). `setup` runs as
the migrator; everything the service and the prune CLI do then runs as the app role.
"""

from __future__ import annotations

import os
import secrets
import subprocess  # nosec B404 - runs this repo's own CLI
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import psycopg
import pytest
import structlog
from psycopg import sql
from psycopg.conninfo import make_conninfo
from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.guards import build_run_guard
from neuron_agent.persistence.migrations import (
    AppRoleError,
    IdentityKeyMismatch,
    identity_check_value,
    run_setup,
)
from neuron_agent.persistence.retention import prune_threads
from neuron_agent.schemas.agent import AgentRequest
from neuron_agent.security.run_guard import RunClaimDenied
from neuron_agent.services.agent_service import AgentService

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_DSN = os.environ.get("APP_TEST_POSTGRES_DSN")
_KEY_A = "identity-key-A-" + "a" * 32
_KEY_B = "identity-key-B-" + "b" * 32
_EXPECTED_TABLES = {
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
    "neuron_migrations",
    "neuron_meta",
    "neuron_run_leases",
}


@dataclass(frozen=True)
class Roles:
    migrator: str
    app: str
    migrator_password: str
    app_password: str


@dataclass(frozen=True)
class RoleDatabase:
    name: str
    roles: Roles

    def dsn(self, role: str) -> str:
        assert _DSN
        password = (
            self.roles.migrator_password if role == self.roles.migrator else self.roles.app_password
        )
        return make_conninfo(_DSN, dbname=self.name, user=role, password=password)

    @property
    def migrator_dsn(self) -> str:
        return self.dsn(self.roles.migrator)

    @property
    def app_dsn(self) -> str:
        return self.dsn(self.roles.app)


@pytest.fixture(scope="session")
def roles() -> Iterator[Roles]:
    """Two login roles with session-unique names; dropped when the session ends."""
    if not _DSN:
        pytest.skip("APP_TEST_POSTGRES_DSN is not set; see OPERATIONS.md for a local Postgres.")
    suffix = uuid.uuid4().hex[:10]
    made = Roles(
        migrator=f"neuron_t{suffix}_migrator",
        app=f"neuron_t{suffix}_app",
        migrator_password=secrets.token_hex(16),
        app_password=secrets.token_hex(16),
    )
    with psycopg.connect(_DSN, autocommit=True) as admin:
        for role, password in (
            (made.migrator, made.migrator_password),
            (made.app, made.app_password),
        ):
            admin.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(password)
                )
            )
        try:
            yield made
        finally:
            for role in (made.app, made.migrator):
                admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


@pytest.fixture
async def role_db(roles: Roles) -> AsyncIterator[RoleDatabase]:
    """A fresh database whose schema belongs to the migrator (the OPERATIONS.md snippet)."""
    assert _DSN
    name = f"neuron_roles_{uuid.uuid4().hex[:12]}"
    async with await psycopg.AsyncConnection.connect(_DSN, autocommit=True) as admin:
        await admin.execute(f'CREATE DATABASE "{name}"')  # nosec B608 - generated name
        try:
            async with await psycopg.AsyncConnection.connect(
                make_conninfo(_DSN, dbname=name), autocommit=True
            ) as setup_conn:
                await setup_conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
                await setup_conn.execute(
                    sql.SQL("ALTER SCHEMA public OWNER TO {}").format(
                        sql.Identifier(roles.migrator)
                    )
                )
            yield RoleDatabase(name=name, roles=roles)
        finally:
            await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')  # nosec B608


async def _setup(db: RoleDatabase, **kwargs: Any) -> list[int]:
    kwargs.setdefault("app_role", db.roles.app)
    return await run_setup(db.migrator_dsn, **kwargs)


async def _rows(dsn: str, query: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        cursor = await conn.execute(query, params)  # type: ignore[call-overload]
        return await cursor.fetchall()


async def _denied(dsn: str, statement: str) -> str:
    """Run `statement` and return the error text; it must fail with insufficient_privilege."""
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege) as caught:
            await conn.execute(statement)  # type: ignore[call-overload]
    return str(caught.value)


def _settings(db: RoleDatabase, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "env": "test",
        "checkpointer": "postgres",
        "postgres_dsn": SecretStr(db.app_dsn),
    }
    return Settings(**{**values, **overrides})


# --- the grants ---------------------------------------------------------------------------


@pytest.mark.usefixtures("echo_agent")
async def test_app_role_runs_every_service_and_prune_query(role_db: RoleDatabase) -> None:
    await _setup(role_db, identity_hash_key=_KEY_A)

    # Checkpointer reads and writes, thread listing, history, deletion, bulk erase.
    service = AgentService(_settings(role_db))
    await service.startup()
    try:
        first = (await service.invoke(AgentRequest(message="one", user_id="alice"))).thread_id
        await service.invoke(AgentRequest(message="two", thread_id=first, user_id="alice"))
        old = (await service.invoke(AgentRequest(message="old", user_id="bob"))).thread_id
        doomed = (await service.invoke(AgentRequest(message="doomed", user_id="bob"))).thread_id
        assert (await service.list_user_threads("alice", limit=10, offset=0)).total == 1
        assert (await service.get_history(first, "alice", limit=10, offset=0)).total == 4
        await service.delete_thread(doomed, "bob")
        # Retention: stale-thread query plus checkpointer `adelete_thread`.
        assert await prune_threads(service._persistence, older_than=timedelta(0)) >= 2
        assert (await service.list_user_threads("bob", limit=10, offset=0)).total == 0
        assert old
        erased = await service.erase_user_data("alice")
        assert (erased.erased_count, erased.skipped_busy_count) == (0, 0)
    finally:
        await service.shutdown()

    # Lease claim, release, thread hold and the retention sweep, through the real guard.
    settings = _settings(role_db, checkpointer="none", limits_backend="postgres")
    persistence = build_persistence(settings)
    await persistence.open()
    try:
        guard = build_run_guard(settings, persistence)
        lease = await guard.claim(
            thread_id="t1", owner_key="owner", streaming=False, guard_thread=True
        )
        assert await guard.is_thread_active("t1") is True
        assert await guard.active_threads_of("owner") == frozenset({"t1"})
        with pytest.raises(RunClaimDenied):
            await guard.claim(thread_id="t1", owner_key="owner", streaming=False, guard_thread=True)
        await lease.release()
        held = await guard.hold_thread(thread_id="t1", owner_key="owner")
        await held.release()
        assert await guard.count_expired() == 0
        async with persistence.pool.connection() as conn:  # type: ignore[union-attr]
            await conn.execute(
                "INSERT INTO neuron_run_leases (owner_key, thread_id, expires_at)"
                " VALUES ('o', 'stale', now() - interval '1 minute')"
            )
        assert await guard.count_expired() == 1
        await prune_threads(persistence, older_than=timedelta(days=30), delete_leases=True)
        assert await guard.count_expired() == 0
    finally:
        await persistence.close()


async def test_prune_cli_runs_as_the_app_role(role_db: RoleDatabase) -> None:
    await _setup(role_db)
    async with await psycopg.AsyncConnection.connect(role_db.app_dsn, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO neuron_run_leases (owner_key, thread_id, expires_at)"
            " VALUES ('o', 'stale', now() - interval '1 minute')"
        )
    env = {
        **os.environ,
        "APP_ENV": "test",
        "APP_CHECKPOINTER": "postgres",
        "APP_LIMITS_BACKEND": "postgres",
        "APP_POSTGRES_DSN": role_db.app_dsn,
    }
    proc = subprocess.run(  # noqa: S603  # nosec B603
        [sys.executable, "-m", "neuron_agent.persistence.cli", "prune"],
        env=env,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert b"run_lease_cleanup_failed" not in proc.stdout + proc.stderr
    assert await _rows(role_db.migrator_dsn, "SELECT count(*) FROM neuron_run_leases") == [(0,)]


async def test_app_role_cannot_create_drop_truncate_or_alter(role_db: RoleDatabase) -> None:
    await _setup(role_db)
    tables = {
        row[0]
        for row in await _rows(
            role_db.migrator_dsn,
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'",
        )
    }
    assert _EXPECTED_TABLES <= tables
    for table in sorted(tables):
        ident = sql.Identifier(table).as_string()
        # CREATE: no CREATE on the schema, even for a name that already exists.
        assert "permission denied" in await _denied(
            role_db.app_dsn, f"CREATE TABLE IF NOT EXISTS {ident} (a int)"
        )
        # DROP and ALTER need ownership ("must be owner of table"); TRUNCATE is a privilege.
        await _denied(role_db.app_dsn, f"DROP TABLE {ident}")
        await _denied(role_db.app_dsn, f"ALTER TABLE {ident} ADD COLUMN neuron_probe int")
        assert "permission denied" in await _denied(role_db.app_dsn, f"TRUNCATE {ident}")
    assert "permission denied" in await _denied(role_db.app_dsn, "CREATE TABLE neuron_new (a int)")
    assert "permission denied" in await _denied(role_db.app_dsn, "CREATE SCHEMA neuron_new")
    # Nothing was dropped or changed, and the migrator still owns everything.
    owners = await _rows(
        role_db.migrator_dsn,
        "SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 'public'",
    )
    assert owners == [(role_db.roles.migrator,)]
    flags = await _rows(
        role_db.migrator_dsn,
        "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = %s",
        (role_db.roles.app,),
    )
    assert flags == [(False, False, False)]


async def test_grants_are_exactly_the_documented_dml(role_db: RoleDatabase) -> None:
    await _setup(role_db, identity_hash_key=_KEY_A)
    privileges = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
    granted: dict[str, set[str]] = {}
    for table in _EXPECTED_TABLES:
        granted[table] = {
            p
            for p in privileges
            if (
                await _rows(
                    role_db.migrator_dsn,
                    "SELECT has_table_privilege(%s, %s, %s)",
                    (role_db.roles.app, table, p),
                )
            )[0][0]
        }
    dml = {"SELECT", "INSERT", "UPDATE", "DELETE"}
    assert granted == {
        "checkpoints": dml,
        "checkpoint_blobs": dml,
        "checkpoint_writes": dml,
        "neuron_run_leases": {"SELECT", "INSERT", "DELETE"},
        "neuron_meta": {"SELECT"},
        "neuron_migrations": set(),
        "checkpoint_migrations": set(),
    }
    # The app role cannot rewrite the identity check value.
    assert "permission denied" in await _denied(
        role_db.app_dsn, "UPDATE neuron_meta SET value = ''"
    )
    assert "permission denied" in await _denied(role_db.app_dsn, "DELETE FROM neuron_meta")
    assert "permission denied" in await _denied(
        role_db.app_dsn,
        "INSERT INTO neuron_run_leases (owner_key, thread_id, expires_at)"
        " VALUES ('o', 'x', now()) ON CONFLICT (thread_id) DO UPDATE SET owner_key = 'y'",
    )


async def test_default_privileges_cover_tables_created_later(role_db: RoleDatabase) -> None:
    await _setup(role_db)
    async with await psycopg.AsyncConnection.connect(
        role_db.migrator_dsn, autocommit=True
    ) as migrator:
        await migrator.execute("CREATE TABLE later_table (id serial PRIMARY KEY, a int)")
    async with await psycopg.AsyncConnection.connect(role_db.app_dsn, autocommit=True) as app:
        await app.execute("INSERT INTO later_table (a) VALUES (1)")
        cursor = await app.execute("SELECT a FROM later_table")
        assert await cursor.fetchall() == [(1,)]
        await app.execute("UPDATE later_table SET a = 2")
        await app.execute("DELETE FROM later_table")
    assert "permission denied" in await _denied(role_db.app_dsn, "TRUNCATE later_table")


async def test_setup_grants_are_idempotent(role_db: RoleDatabase) -> None:
    query = "SELECT relname, relacl::text FROM pg_class WHERE relnamespace = 'public'::regnamespace"
    await _setup(role_db, identity_hash_key=_KEY_A)
    before = sorted(await _rows(role_db.migrator_dsn, query))
    assert await _setup(role_db, identity_hash_key=_KEY_A) == []
    assert sorted(await _rows(role_db.migrator_dsn, query)) == before


# --- the single-role profile and missing roles --------------------------------------------


async def test_single_role_setup_skips_the_grants_with_a_log_line(role_db: RoleDatabase) -> None:
    with structlog.testing.capture_logs() as logs:
        await run_setup(role_db.migrator_dsn, app_role=role_db.roles.migrator)
    skipped = [entry for entry in logs if entry["event"] == "app_role_grants_skipped"]
    assert len(skipped) == 1
    assert "single-role" in skipped[0]["reason"]
    # The one role owns the tables, so the service still works as that role.
    async with await psycopg.AsyncConnection.connect(role_db.migrator_dsn) as conn:
        await conn.execute("SELECT count(*) FROM checkpoints")


async def test_missing_app_role_is_skipped_unless_required(role_db: RoleDatabase) -> None:
    with structlog.testing.capture_logs() as logs:
        await run_setup(role_db.migrator_dsn, app_role="neuron_no_such_role_xyz")
    assert any(entry["event"] == "app_role_grants_skipped" for entry in logs)
    with pytest.raises(AppRoleError):
        await run_setup(
            role_db.migrator_dsn, app_role="neuron_no_such_role_xyz", require_app_role=True
        )
    with pytest.raises(AppRoleError):
        await run_setup(
            role_db.migrator_dsn, app_role=role_db.roles.migrator, require_app_role=True
        )


# --- the identity key check value ---------------------------------------------------------


async def test_identity_check_value_is_written_once_and_rotation_is_explicit(
    role_db: RoleDatabase,
) -> None:
    select = "SELECT value FROM neuron_meta WHERE key = 'identity_key_check'"
    await _setup(role_db, identity_hash_key=_KEY_A)
    assert await _rows(role_db.migrator_dsn, select) == [(identity_check_value(_KEY_A),)]
    stored = identity_check_value(_KEY_A)
    assert stored != _KEY_A and _KEY_A not in stored

    await _setup(role_db, identity_hash_key=_KEY_A)  # same key: verified, nothing written
    with pytest.raises(IdentityKeyMismatch) as caught:
        await _setup(role_db, identity_hash_key=_KEY_B)
    for secret in (_KEY_A, _KEY_B, stored, identity_check_value(_KEY_B)):
        assert secret not in str(caught.value)
    assert "--rotate-identity-key" in str(caught.value)
    assert await _rows(role_db.migrator_dsn, select) == [(stored,)]

    await _setup(role_db, identity_hash_key=_KEY_B, rotate_identity_key=True)
    assert await _rows(role_db.migrator_dsn, select) == [(identity_check_value(_KEY_B),)]
    await _setup(role_db, identity_hash_key=_KEY_B)  # the new key is now the recorded one


async def test_setup_cli_enforces_the_identity_key_without_echoing_it(
    role_db: RoleDatabase,
) -> None:
    def cli(key: str, *flags: str) -> subprocess.CompletedProcess[bytes]:
        env = {
            **os.environ,
            "APP_ENV": "test",
            "APP_POSTGRES_MIGRATION_DSN": role_db.migrator_dsn,
            "APP_POSTGRES_APP_ROLE": role_db.roles.app,
            "APP_IDENTITY_HASH_KEY": key,
        }
        return subprocess.run(  # noqa: S603  # nosec B603
            [sys.executable, "-m", "neuron_agent.persistence.cli", "setup", *flags],
            env=env,
            capture_output=True,
            timeout=120,
            check=False,
        )

    assert cli(_KEY_A).returncode == 0
    refused = cli(_KEY_B)
    assert refused.returncode == 1
    output = (refused.stdout + refused.stderr).decode()
    assert "--rotate-identity-key" in output
    for secret in (_KEY_A, _KEY_B, identity_check_value(_KEY_A), identity_check_value(_KEY_B)):
        assert secret not in output
    assert role_db.roles.migrator_password not in output
    rotated = cli(_KEY_B, "--rotate-identity-key")
    assert rotated.returncode == 0, rotated.stderr
    assert await _rows(role_db.migrator_dsn, "SELECT value FROM neuron_meta") == [
        (identity_check_value(_KEY_B),)
    ]
