"""Least-privilege database roles (#144, ADR 0008 decisions 15 and 16).

Each test gets a fresh database and two roles created for the test session (roles are
cluster-level, so their names are unique per session and dropped at the end). `setup` runs as
the migrator; everything the service and the prune CLI do then runs as the app role.
"""

from __future__ import annotations

import asyncio
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
from neuron_agent.persistence import cli
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.guards import build_rate_limiter, build_run_guard
from neuron_agent.persistence.migrations import (
    MIGRATIONS,
    IdentityKeyMismatch,
    Migration,
    identity_check_value,
    run_setup,
)
from neuron_agent.persistence.retention import prune_threads
from neuron_agent.persistence.roles import AppRoleError
from neuron_agent.persistence.startup_checks import StartupCheckError
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
    "neuron_token_ledger",
    "neuron_token_settlements",
    "neuron_rate_buckets",
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
    settings = _settings(
        role_db,
        checkpointer="none",
        limits_backend="postgres",
        identity_hash_key=SecretStr(_KEY_A),
    )
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

        # The rate limiter's upsert, its opportunistic delete and the retention delete.
        limiter = build_rate_limiter(settings, persistence)
        assert (await limiter.check("ip:probe")).allowed is True
        await prune_threads(
            persistence, older_than=timedelta(days=30), rate_bucket_idle_seconds=0.0
        )
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
        "neuron_token_ledger": dml,
        "neuron_token_settlements": {"SELECT", "INSERT", "DELETE"},
        "neuron_rate_buckets": dml,
        "neuron_meta": set(),
        "neuron_migrations": set(),
        "checkpoint_migrations": set(),
    }
    # The app role can neither read nor rewrite the identity check value.
    assert "permission denied" in await _denied(role_db.app_dsn, "SELECT value FROM neuron_meta")
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


# --- ordering, production verification and the runtime role check (review of #144) --------

_BOOKKEEPING = ("neuron_migrations", "checkpoint_migrations", "neuron_meta")


async def _app_dml_on_bookkeeping(db: RoleDatabase) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for table in _BOOKKEEPING:
        rows = await _rows(
            db.migrator_dsn,
            "SELECT p FROM unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE']) AS p"
            " WHERE has_table_privilege(%s, %s, p)",
            (db.roles.app, table),
        )
        found[table] = [row[0] for row in rows]
    return found


async def test_a_failed_setup_never_leaves_app_dml_on_the_bookkeeping_tables(
    role_db: RoleDatabase,
) -> None:
    nothing = {table: [] for table in _BOOKKEEPING}
    broken = Migration(
        version=max(m.version for m in MIGRATIONS) + 1, name="broken", sql="SELECT 1/0"
    )
    # A migration fails after every real migration created the tables.
    with pytest.raises(psycopg.errors.DivisionByZero):
        await _setup(role_db, migrations=[*MIGRATIONS, broken], identity_hash_key=_KEY_A)
    assert await _app_dml_on_bookkeeping(role_db) == nothing
    # An identity mismatch fails after every migration is applied.
    await _setup(role_db, identity_hash_key=_KEY_A)
    with pytest.raises(IdentityKeyMismatch):
        await _setup(role_db, identity_hash_key=_KEY_B)
    assert await _app_dml_on_bookkeeping(role_db) == nothing
    # And so does a database where the defaults already exist and a table is added later.
    async with await psycopg.AsyncConnection.connect(role_db.migrator_dsn, autocommit=True) as conn:
        await conn.execute("DROP TABLE neuron_meta")
        await conn.execute("DELETE FROM neuron_migrations WHERE version = 5")
    with pytest.raises(psycopg.errors.DivisionByZero):
        await _setup(role_db, migrations=[*MIGRATIONS, broken])
    assert await _app_dml_on_bookkeeping(role_db) == nothing


async def test_production_setup_verifies_the_role_and_the_privilege_matrix(
    role_db: RoleDatabase,
) -> None:
    with structlog.testing.capture_logs() as logs:
        await _setup(role_db, require_app_role=True, identity_hash_key=_KEY_A)
    assert any(entry["event"] == "app_role_grants_applied" for entry in logs)

    # A GRANT by a role that does not own the table only warns; verification catches it.
    async with await psycopg.AsyncConnection.connect(
        _DSN, dbname=role_db.name, autocommit=True
    ) as su:  # type: ignore[arg-type]
        await su.execute(f"REVOKE ALL ON checkpoint_blobs FROM {role_db.roles.app}")  # nosec B608
        await su.execute("ALTER TABLE checkpoint_blobs OWNER TO postgres")
        await su.execute(f"GRANT ALL ON checkpoint_blobs TO {role_db.roles.migrator}")  # nosec B608
    with structlog.testing.capture_logs() as logs, pytest.raises(AppRoleError) as caught:
        await _setup(role_db, require_app_role=True)
    assert "privileges" in str(caught.value)
    assert not any(entry["event"] == "app_role_grants_applied" for entry in logs)
    assert any(
        entry["event"] == "app_role_grants_mismatch" and entry["tables"] == ["checkpoint_blobs"]
        for entry in logs
    )
    # Outside production it is a warning, and "applied" is still not reported.
    with structlog.testing.capture_logs() as logs:
        await _setup(role_db)
    assert not any(entry["event"] == "app_role_grants_applied" for entry in logs)


async def _admin(db: RoleDatabase, statement: str) -> None:
    async with await psycopg.AsyncConnection.connect(_DSN, dbname=db.name, autocommit=True) as conn:  # type: ignore[arg-type]
        await conn.execute(statement)  # type: ignore[call-overload]


@pytest.mark.parametrize(
    ("grant", "revoke", "phrase"),
    [
        ("ALTER ROLE {app} BYPASSRLS", "ALTER ROLE {app} NOBYPASSRLS", "bypasses row-level"),
        ("GRANT {migrator} TO {app}", "REVOKE {migrator} FROM {app}", "member of the migration"),
        (
            "GRANT CREATE ON SCHEMA public TO {app}",
            "REVOKE CREATE ON SCHEMA public FROM {app}",
            "can create",
        ),
    ],
)
async def test_production_setup_refuses_an_overprivileged_app_role(
    role_db: RoleDatabase, grant: str, revoke: str, phrase: str
) -> None:
    names = {"app": role_db.roles.app, "migrator": role_db.roles.migrator}
    await _admin(role_db, grant.format(**names))
    try:
        with pytest.raises(AppRoleError, match=phrase):
            await _setup(role_db, require_app_role=True)
        await _setup(role_db)  # outside production the attributes are not checked
    finally:
        await _admin(role_db, revoke.format(**names))
    await _setup(role_db, require_app_role=True)


async def test_production_setup_refuses_a_superuser_app_role(role_db: RoleDatabase) -> None:
    with pytest.raises(AppRoleError, match="superuser"):
        await run_setup(role_db.migrator_dsn, app_role="postgres", require_app_role=True)


def _production_persistence(db: RoleDatabase, dsn: str, app_role: str) -> Any:
    persistence = build_persistence(
        Settings.model_construct(
            env="production",
            checkpointer="postgres",
            limits_backend="memory",
            postgres_dsn=SecretStr(dsn),
            postgres_app_role=app_role,
        )
    )
    persistence.require_tls = False  # the CI server has no TLS; see the TLS tests below
    return persistence


async def test_production_start_up_accepts_only_the_least_privilege_app_role(
    role_db: RoleDatabase,
) -> None:
    await _setup(role_db)
    persistence = _production_persistence(role_db, role_db.app_dsn, role_db.roles.app)
    await persistence.open()
    try:
        assert await persistence.is_ready() is True
    finally:
        await persistence.close()

    # Connected as the migrator (the schema owner), or as a user that is not the app role.
    for dsn in (role_db.migrator_dsn, role_db.dsn(role_db.roles.migrator)):
        bad = _production_persistence(role_db, dsn, role_db.roles.app)
        with pytest.raises(AppRoleError, match="not APP_POSTGRES_APP_ROLE") as caught:
            await bad.open()
        assert dsn not in str(caught.value)
        assert not bad.is_open
    # The migrator named as the app role is the schema owner.
    owner = _production_persistence(role_db, role_db.migrator_dsn, role_db.roles.migrator)
    with pytest.raises(AppRoleError, match="schema owner"):
        await owner.open()
    # A superuser.
    assert _DSN
    superuser = _production_persistence(
        role_db, make_conninfo(_DSN, dbname=role_db.name), "postgres"
    )
    with pytest.raises(AppRoleError, match="superuser"):
        await superuser.open()


@pytest.mark.parametrize(
    ("grant", "revoke", "phrase"),
    [
        ("GRANT {migrator} TO {app}", "REVOKE {migrator} FROM {app}", "member of the schema owner"),
        (
            "GRANT CREATE ON SCHEMA public TO {app}",
            "REVOKE CREATE ON SCHEMA public FROM {app}",
            "can create",
        ),
        ("ALTER ROLE {app} BYPASSRLS", "ALTER ROLE {app} NOBYPASSRLS", "bypasses row-level"),
    ],
)
async def test_production_start_up_fails_closed_on_an_overprivileged_role(
    role_db: RoleDatabase, grant: str, revoke: str, phrase: str
) -> None:
    await _setup(role_db)
    names = {"app": role_db.roles.app, "migrator": role_db.roles.migrator}
    await _admin(role_db, grant.format(**names))
    try:
        persistence = _production_persistence(role_db, role_db.app_dsn, role_db.roles.app)
        with pytest.raises(AppRoleError, match=phrase) as caught:
            await persistence.open()
        assert role_db.roles.app_password not in str(caught.value)
        assert caught.value.code == "role_too_privileged"
        assert not persistence.is_open
    finally:
        await _admin(role_db, revoke.format(**names))


async def test_identity_key_audit_events_carry_no_key_or_value(role_db: RoleDatabase) -> None:
    with structlog.testing.capture_logs() as logs:
        await _setup(role_db, identity_hash_key=_KEY_A)
        await _setup(role_db, identity_hash_key=_KEY_B, rotate_identity_key=True)
    audits = [e for e in logs if e.get("audit") is True or e["event"].startswith("identity_key")]
    events = [e["event"] for e in audits if e["event"].startswith("identity_key_check_")]
    assert "identity_key_check_written" in events and "identity_key_check_rotated" in events
    text = repr(audits)
    for secret in (_KEY_A, _KEY_B, identity_check_value(_KEY_A), identity_check_value(_KEY_B)):
        assert secret not in text
    audit_rows = [e for e in logs if e.get("audit") is True]
    assert {e["event"] for e in audit_rows} == {
        "identity_key_check_written",
        "identity_key_check_rotated",
    }


# --- start-up checks: TLS and identity key (#139) ------------------------------------------


def _hardened(dsn: str, *, tls: bool = False, key: str | None = None) -> Any:
    """Staging-shaped persistence (TLS and key checks; the role check is production-only)."""
    persistence = build_persistence(
        Settings.model_construct(
            env="staging",
            checkpointer="postgres",
            limits_backend="memory",
            postgres_dsn=SecretStr(dsn),
            identity_hash_key=SecretStr(key) if key else None,
        )
    )
    persistence.require_tls = tls  # the CI server has no TLS; the TLS tests set it themselves
    return persistence


async def test_identity_function_answers_match_mismatch_or_unset_and_hides_the_value(
    role_db: RoleDatabase,
) -> None:
    ask = "SELECT neuron_identity_status(%s)"
    mine = identity_check_value(_KEY_A)
    await _setup(role_db)
    assert await _rows(role_db.app_dsn, ask, (mine,)) == [("unset",)]
    await _setup(role_db, identity_hash_key=_KEY_A)
    assert await _rows(role_db.app_dsn, ask, (mine,)) == [("match",)]
    assert await _rows(role_db.app_dsn, ask, (identity_check_value(_KEY_B),)) == [("mismatch",)]
    # The role still cannot read the table, and the function is not open to PUBLIC.
    assert "permission denied" in await _denied(role_db.app_dsn, "SELECT * FROM neuron_meta")
    assert await _rows(
        role_db.migrator_dsn,
        "SELECT count(*), bool_or(a.grantee = 0) FROM pg_proc p, aclexplode(p.proacl) a"
        " WHERE p.proname = 'neuron_identity_status'",
    ) == [(2, False)]
    assert await _rows(
        role_db.migrator_dsn,
        "SELECT proconfig FROM pg_proc WHERE proname = 'neuron_identity_status'",
    ) == [(["search_path=pg_catalog, pg_temp"],)]


async def test_startup_identity_check_accepts_the_recorded_key_only(role_db: RoleDatabase) -> None:
    await _setup(role_db)
    unset = _hardened(role_db.app_dsn, key=_KEY_A)
    with pytest.raises(StartupCheckError) as caught:
        await unset.open()
    assert caught.value.code == "identity_key_unrecorded"
    await _setup(role_db, identity_hash_key=_KEY_A)
    good = _hardened(role_db.app_dsn, key=_KEY_A)
    await good.open()
    try:
        assert await good.is_ready() is True
    finally:
        await good.close()
    with structlog.testing.capture_logs() as logs:
        bad = _hardened(role_db.app_dsn, key=_KEY_B)
        with pytest.raises(StartupCheckError) as caught:
            await bad.open()
    assert caught.value.code == "identity_key_mismatch"
    assert not bad.is_open
    failures = [e for e in logs if e["event"] == "database_startup_check_failed"]
    assert [e["error_code"] for e in failures] == ["identity_key_mismatch"]
    text = repr(logs) + str(caught.value)
    for secret in (_KEY_A, _KEY_B, identity_check_value(_KEY_A), identity_check_value(_KEY_B)):
        assert secret not in text
    assert role_db.roles.app_password not in text and role_db.app_dsn not in text


async def test_startup_identity_check_without_the_function_is_unrecorded(
    role_db: RoleDatabase,
) -> None:
    await _setup(role_db, identity_hash_key=_KEY_A)
    await _admin(role_db, "DROP FUNCTION neuron_identity_status(text)")
    persistence = _hardened(role_db.app_dsn, key=_KEY_A)
    with pytest.raises(StartupCheckError) as caught:
        await persistence.open()
    assert caught.value.code == "identity_key_unrecorded"


async def test_startup_tls_check(role_db: RoleDatabase) -> None:
    await _setup(role_db)
    plain = _hardened(make_conninfo(role_db.app_dsn, sslmode="disable"), tls=True)
    with structlog.testing.capture_logs() as logs:
        with pytest.raises(StartupCheckError) as caught:
            await plain.open()
    assert caught.value.code == "tls_required"
    assert [e["error_code"] for e in logs if e["event"] == "database_startup_check_failed"] == [
        "tls_required"
    ]
    assert not plain.is_open
    assert role_db.roles.app_password not in str(caught.value) + repr(logs)
    # The app role reads its own row in pg_stat_ssl. With TLS on the server (not the CI service
    # container) a `require` connection passes; without it the connection cannot be made.
    secure = _hardened(make_conninfo(role_db.app_dsn, sslmode="require"), tls=True)
    tls_on = (await _rows(role_db.app_dsn, "SELECT current_setting('ssl')"))[0][0] == "on"
    if os.environ.get("APP_TEST_POSTGRES_REQUIRE_TLS") == "1":
        assert tls_on, "CI runs Postgres with TLS; the success path must not be skipped"
    if tls_on:
        await secure.open()
        try:
            assert await secure.is_ready() is True
        finally:
            await secure.close()
    else:
        with pytest.raises(StartupCheckError) as unreachable:
            await secure.open()
        assert unreachable.value.code == "database_check_failed"


async def test_production_start_up_runs_the_identity_check_with_the_role_check(
    role_db: RoleDatabase,
) -> None:
    await _setup(role_db, identity_hash_key=_KEY_A)
    settings = Settings.model_construct(
        env="production",
        checkpointer="postgres",
        limits_backend="memory",
        postgres_dsn=SecretStr(role_db.app_dsn),
        postgres_app_role=role_db.roles.app,
        identity_hash_key=SecretStr(_KEY_A),
    )
    good = build_persistence(settings)
    good.require_tls = False
    await good.open()
    await good.close()
    wrong_key = build_persistence(
        settings.model_copy(update={"identity_hash_key": SecretStr(_KEY_B)})
    )
    wrong_key.require_tls = False
    with pytest.raises(StartupCheckError) as caught:
        await wrong_key.open()
    assert caught.value.code == "identity_key_mismatch"


async def test_prune_cli_applies_the_same_checks_and_exits_non_zero(
    role_db: RoleDatabase, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    await _setup(role_db, identity_hash_key=_KEY_A)
    settings = Settings.model_construct(
        env="staging",
        checkpointer="postgres",
        limits_backend="memory",
        postgres_dsn=SecretStr(make_conninfo(role_db.app_dsn, sslmode="disable")),
        identity_hash_key=SecretStr(_KEY_A),
        log_level="WARNING",
        thread_retention_days=30,
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "configure_logging", lambda **_: None)
    with pytest.raises(SystemExit) as exit_info:
        await asyncio.to_thread(cli.main, ["prune"])
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert "tls_required" in err
    assert role_db.roles.app_password not in err and _KEY_A not in err


@pytest.mark.parametrize(
    "tamper",
    [
        "ALTER FUNCTION neuron_identity_status(text) SECURITY INVOKER",
        "ALTER FUNCTION neuron_identity_status(text) OWNER TO {app}",
    ],
)
async def test_startup_identity_check_refuses_a_function_that_is_not_the_migrators(
    role_db: RoleDatabase, tamper: str
) -> None:
    await _setup(role_db, identity_hash_key=_KEY_A)
    await _admin(role_db, tamper.format(app=role_db.roles.app))
    persistence = _hardened(role_db.app_dsn, key=_KEY_A)
    with pytest.raises(StartupCheckError) as caught:
        await persistence.open()
    assert caught.value.code == "identity_check_unsafe"


@pytest.mark.parametrize(
    "tamper",
    [
        "GRANT EXECUTE ON FUNCTION neuron_identity_status(text) TO PUBLIC",
        "ALTER FUNCTION neuron_identity_status(text) RESET search_path",
        "ALTER FUNCTION neuron_identity_status(text) SECURITY INVOKER",
    ],
)
async def test_setup_refuses_a_loosened_identity_function(
    role_db: RoleDatabase, tamper: str
) -> None:
    await _setup(role_db, identity_hash_key=_KEY_A)
    await _admin(role_db, tamper)
    with pytest.raises(AppRoleError):
        await _setup(role_db, identity_hash_key=_KEY_A, require_app_role=True)
