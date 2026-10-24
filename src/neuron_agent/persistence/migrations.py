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
import hashlib
import hmac
import time
from collections.abc import Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass

import psycopg
import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import sql
from psycopg.rows import dict_row

from neuron_agent.observability.audit import audit
from neuron_agent.persistence.roles import AppRoleError, role_problems

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


# The check value is an HMAC of this fixed label under `APP_IDENTITY_HASH_KEY` (ADR 0008
# decision 16): it identifies the key without revealing it.
_IDENTITY_LABEL = b"neuron.identity-key-check.v1"
_IDENTITY_META_KEY = "identity_key_check"

# What the app role may do on each table (ADR 0008 decision 15). Bookkeeping tables get
# nothing: only the migrator reads them, and `neuron_meta` holds a check value that is an
# offline oracle for a weak identity key, so the app role does not read it either. Leases are
# never updated, only claimed, released and swept.
_DML = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})
_APP_PRIVILEGES: dict[str, frozenset[str]] = {
    "checkpoints": _DML,
    "checkpoint_blobs": _DML,
    "checkpoint_writes": _DML,
    "neuron_run_leases": frozenset({"SELECT", "INSERT", "DELETE"}),
    "neuron_token_ledger": _DML,
    "neuron_rate_buckets": _DML,
    # Settled reservation ids are only inserted (idempotent settle) and swept by retention.
    "neuron_token_settlements": frozenset({"SELECT", "INSERT", "DELETE"}),
    "neuron_meta": frozenset(),
    "neuron_migrations": frozenset(),
    "checkpoint_migrations": frozenset(),
}
# The one function the app role may run: it answers whether a candidate check value matches the
# one in `neuron_meta` without letting the role read that table (migration 12).
_IDENTITY_FUNCTION = "neuron_identity_status"
_CHECKED_PRIVILEGES = (*sorted(_DML), "TRUNCATE", "REFERENCES", "TRIGGER")


class LockWaitTimeout(TimeoutError):
    """Another `setup` held the advisory lock for the whole wait. The text is fixed."""


class IdentityKeyMismatch(Exception):
    """The database holds a different identity key check value. The text is fixed and safe."""


def identity_check_value(identity_hash_key: str) -> str:
    """HMAC-SHA256 of a fixed label under the key: stored in `neuron_meta`, never the key."""
    return hmac.new(identity_hash_key.encode("utf-8"), _IDENTITY_LABEL, hashlib.sha256).hexdigest()


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
        name="neuron_meta",
        # Key/value facts about the deployment; `setup` stores the identity key check value
        # here (ADR 0008 decision 16). No access for the app role (see `table_grant_statements`).
        sql="""
CREATE TABLE IF NOT EXISTS neuron_meta (
    key text PRIMARY KEY,
    value text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
)
""",
    ),
    Migration(
        version=6,
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
        version=7,
        name="token_ledger_minute_idx",
        sql="""
CREATE INDEX CONCURRENTLY IF NOT EXISTS neuron_token_ledger_minute_idx
ON neuron_token_ledger (minute)
""",
        concurrent=True,
        index="neuron_token_ledger_minute_idx",
    ),
    Migration(
        version=8,
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
        version=9,
        name="token_settlements_settled_idx",
        sql="""
CREATE INDEX CONCURRENTLY IF NOT EXISTS neuron_token_settlements_settled_idx
ON neuron_token_settlements (settled_at)
""",
        concurrent=True,
        index="neuron_token_settlements_settled_idx",
    ),
    Migration(
        version=10,
        name="rate_buckets",
        # Shared request rate limiter (`persistence/rate_limiter.py`, ADR 0008 decision 8):
        # one token bucket per key. UNLOGGED on purpose: no WAL for a write per request, and
        # empty after a crash, failover or restore, which grants a burst (ADR 0004). Keys are
        # `principal:<owner key>` or `ip:<HMAC>`, never a raw address.
        sql="""
CREATE UNLOGGED TABLE IF NOT EXISTS neuron_rate_buckets (
    key text PRIMARY KEY,
    tokens double precision NOT NULL CHECK (tokens >= 0),
    refilled_at timestamptz NOT NULL,
    allowed boolean NOT NULL
) WITH (fillfactor = 70, autovacuum_vacuum_scale_factor = 0.02)
""",
    ),
    # Serves the delete of idle buckets (opportunistic and the retention job).
    Migration(
        version=11,
        name="rate_buckets_refilled_idx",
        sql="""
CREATE INDEX CONCURRENTLY IF NOT EXISTS neuron_rate_buckets_refilled_idx
ON neuron_rate_buckets (refilled_at)
""",
        concurrent=True,
        index="neuron_rate_buckets_refilled_idx",
    ),
    Migration(
        version=12,
        name="identity_status_function",
        # Start-up identity key check (ADR 0008 decision 16). The app role has no access to
        # `neuron_meta`, so it asks this SECURITY DEFINER function (owned by the migrator, so it
        # can read the table) whether its candidate check value matches: 'match', 'mismatch' or
        # 'unset'. It never returns the stored value. `search_path` is pinned so no object the
        # caller can create is resolved in its place; the schema is the migrator's current one.
        sql="""
DO $do$
BEGIN
    EXECUTE format($f$
CREATE OR REPLACE FUNCTION %1$I.neuron_identity_status(candidate text) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $body$
SELECT coalesce(
    (SELECT CASE WHEN value = candidate THEN 'match' ELSE 'mismatch' END
     FROM %1$I.neuron_meta WHERE key = 'identity_key_check'),
    'unset')
$body$
$f$, current_schema());
    EXECUTE format(
        'REVOKE ALL ON FUNCTION %I.neuron_identity_status(text) FROM PUBLIC', current_schema());
END
$do$
""",
    ),
)


async def run_setup(
    dsn: str,
    *,
    migrations: Sequence[Migration] | None = None,
    lock_timeout_ms: int | None = None,
    concurrent_lock_timeout_ms: int | None = None,
    lock_wait_seconds: float = LOCK_WAIT_SECONDS,
    app_role: str | None = None,
    require_app_role: bool = False,
    identity_hash_key: str | None = None,
    rotate_identity_key: bool = False,
) -> list[int]:
    """Run LangGraph's `setup()`, then every unapplied migration. Returns the versions applied.

    One direct connection holds a session-level advisory lock for the whole run, so
    concurrent `setup` runs serialise and each migration is applied once. Raises on any
    failure; callers must not print the exception text, which can echo connection details.

    The connection's user is the migrator and owns what it creates. With `app_role`, the
    run also grants that role DML only (ADR 0008 decision 15), on every run, so tables a
    LangGraph upgrade adds are covered. A missing role, or the migrator itself (the
    single-role free-tier profile, decision 17), skips the grants with a log line, or raises
    `AppRoleError` with `require_app_role`. With `identity_hash_key`, the key's check value
    is stored the first time; a different stored value raises `IdentityKeyMismatch` unless
    `rotate_identity_key` is set.
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
        target = await _resolve_app_role(conn, app_role, require_app_role)
        await AsyncPostgresSaver(conn).setup()
        await conn.execute(_CREATE_TABLE_SQL)
        # Tables made so far had no default privileges (first run) or are tightened here.
        # Later tables are tightened in the transaction that creates them.
        after_ddl = (lambda c: _grant(c, target)) if target is not None else None
        if after_ddl is not None:
            await after_ddl(conn)
        applied = await _apply(
            conn,
            MIGRATIONS if migrations is None else migrations,
            timeout_ms,
            concurrent_ms,
            after_ddl,
        )
        if identity_hash_key:
            await _check_identity(conn, identity_hash_key, rotate_identity_key)
        else:
            logger.info("identity_key_check_skipped", reason="no key configured")
        if target is not None:
            await _verify_role(conn, target, required=require_app_role)
            if await _verify_grants(conn, target, required=require_app_role):
                logger.info("app_role_grants_applied", app_role=target.name)
        return applied
    finally:
        await conn.close()  # also releases the session advisory lock


@dataclass(frozen=True)
class _AppRole:
    name: str
    migrator: str
    schema: str


async def _resolve_app_role(
    conn: psycopg.AsyncConnection[dict[str, object]], app_role: str | None, required: bool
) -> _AppRole | None:
    """The role to grant to, or None to skip (logged) when there is none or it is the migrator."""
    if app_role is None:
        logger.info("app_role_grants_skipped", reason="no app role configured")
        return None
    cursor = await conn.execute(
        "SELECT current_user::text AS migrator, current_schema()::text AS schema,"
        " EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s) AS found",
        (app_role,),
    )
    row = await cursor.fetchone()
    assert row is not None  # nosec B101
    if row["migrator"] == app_role:
        reason = "the app role is the migration role (single-role profile, staging only)"
    elif not row["found"]:
        reason = "the app role does not exist"
    else:
        return _AppRole(name=app_role, migrator=str(row["migrator"]), schema=str(row["schema"]))
    if required:
        raise AppRoleError(f"cannot grant to the app role: {reason}")
    logger.warning("app_role_grants_skipped", reason=reason)
    return None


def default_privilege_statements(migrator: str, schema: str, app: str) -> list[sql.Composed]:
    """Default privileges: tables and sequences the migrator creates later reach the app role."""
    target = {
        "migrator": sql.Identifier(migrator),
        "schema": sql.Identifier(schema),
        "app": sql.Identifier(app),
    }
    return [
        sql.SQL(statement).format(**target)
        for statement in (
            "GRANT USAGE ON SCHEMA {schema} TO {app}",
            "ALTER DEFAULT PRIVILEGES FOR ROLE {migrator} IN SCHEMA {schema}"
            " GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app}",
            "ALTER DEFAULT PRIVILEGES FOR ROLE {migrator} IN SCHEMA {schema}"
            " GRANT USAGE, SELECT ON SEQUENCES TO {app}",
        )
    ]


def table_grant_statements(
    schema: str, app: str, present: Collection[str] | None = None
) -> list[sql.Composed]:
    """Per-table grants, DML only: no CREATE, DROP, TRUNCATE, REFERENCES, TRIGGER or ownership.

    Idempotent and expand-only (the lint in `tests/unit/test_migrations_policy.py` runs on
    these statements too). They also take back what the default privileges gave the
    bookkeeping tables. `present` limits them to tables (and the identity function) that
    exist (None: all of them).
    """

    def names(*tables: str) -> sql.Composed | None:
        wanted = [t for t in tables if present is None or t in present]
        return sql.SQL(", ").join(sql.Identifier(schema, t) for t in wanted) if wanted else None

    role = sql.Identifier(app)
    dml = names("checkpoints", "checkpoint_blobs", "checkpoint_writes")
    leases = names("neuron_run_leases", "neuron_token_settlements")
    ledger = names("neuron_token_ledger", "neuron_rate_buckets")
    bookkeeping = names("neuron_migrations", "checkpoint_migrations", "neuron_meta")
    statements: list[sql.Composed] = []
    if present is None or _IDENTITY_FUNCTION in present:
        statements.append(
            sql.SQL("GRANT EXECUTE ON FUNCTION {}(text) TO {}").format(
                sql.Identifier(schema, _IDENTITY_FUNCTION), role
            )
        )
    if dml is not None:
        statements.append(
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON {} TO {}").format(dml, role)
        )
    if leases is not None:
        statements.append(sql.SQL("GRANT SELECT, INSERT, DELETE ON {} TO {}").format(leases, role))
        statements.append(sql.SQL("REVOKE UPDATE ON {} FROM {}").format(leases, role))
    if ledger is not None:
        statements.append(
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON {} TO {}").format(ledger, role)
        )
    if bookkeeping is not None:
        statements.append(sql.SQL("REVOKE ALL ON {} FROM {}").format(bookkeeping, role))
    return statements


async def _grant(conn: psycopg.AsyncConnection[dict[str, object]], role: _AppRole) -> None:
    """Default privileges and the table grants for the tables that exist, in one transaction,
    so a crash cannot leave DML granted without the REVOKEs that follow it."""
    async with conn.transaction():
        cursor = await conn.execute(
            "SELECT tablename::text AS name FROM pg_tables WHERE schemaname = %s", (role.schema,)
        )
        present = {str(row["name"]) for row in await cursor.fetchall()}
        if await _identity_function_exists(conn, role.schema):
            present.add(_IDENTITY_FUNCTION)
        statements = [
            *default_privilege_statements(role.migrator, role.schema, role.name),
            *table_grant_statements(role.schema, role.name, present),
        ]
        for statement in statements:
            await conn.execute(statement)


async def _identity_function_exists(
    conn: psycopg.AsyncConnection[dict[str, object]], schema: str
) -> bool:
    cursor = await conn.execute(
        "SELECT to_regprocedure(format('%%I.%%I(text)', %s::text, %s::text)) IS NOT NULL AS found",
        (schema, _IDENTITY_FUNCTION),
    )
    row = await cursor.fetchone()
    return bool(row and row["found"])


async def _verify_grants(
    conn: psycopg.AsyncConnection[dict[str, object]], role: _AppRole, *, required: bool
) -> bool:
    """Check the privilege matrix with `has_table_privilege`: a GRANT by a role that does not
    own the table only warns, so success of the statement proves nothing."""
    wrong: list[str] = []
    for table, expected in _APP_PRIVILEGES.items():
        cursor = await conn.execute(
            "SELECT p AS priv FROM unnest(%(privs)s::text[]) AS p"
            " WHERE to_regclass(format('%%I.%%I', %(schema)s::text, %(table)s::text)) IS NOT NULL"
            " AND has_table_privilege(%(role)s, format('%%I.%%I', %(schema)s::text,"
            " %(table)s::text), p)",
            {
                "privs": list(_CHECKED_PRIVILEGES),
                "schema": role.schema,
                "table": table,
                "role": role.name,
            },
        )
        granted = {str(row["priv"]) for row in await cursor.fetchall()}
        exists = await conn.execute(
            "SELECT to_regclass(format('%%I.%%I', %(schema)s::text, %(table)s::text)) IS NOT NULL"
            " AS found",
            {"schema": role.schema, "table": table},
        )
        found = await exists.fetchone()
        if found and found["found"] and granted != expected:
            wrong.append(table)
    if await _identity_function_exists(conn, role.schema):
        cursor = await conn.execute(
            "SELECT has_function_privilege(%s, to_regprocedure(format('%%I.%%I(text)',"
            " %s::text, %s::text)), 'EXECUTE') AS ok",
            (role.name, role.schema, _IDENTITY_FUNCTION),
        )
        executable = await cursor.fetchone()
        if not (executable and executable["ok"]):
            wrong.append(_IDENTITY_FUNCTION)
    if wrong:
        logger.warning("app_role_grants_mismatch", tables=wrong)
        if required:
            raise AppRoleError("the app role's table privileges are not what setup grants")
        return False
    return True


async def _verify_role(
    conn: psycopg.AsyncConnection[dict[str, object]], role: _AppRole, *, required: bool
) -> None:
    """After granting in production: the app role must not be able to undo the split."""
    if not required:
        return
    problems = await role_problems(conn, role.name, migrator=role.migrator)
    if problems:
        raise AppRoleError("the app role is too privileged: " + "; ".join(problems))


async def _check_identity(
    conn: psycopg.AsyncConnection[dict[str, object]], identity_hash_key: str, rotate: bool
) -> None:
    """Store the key's check value once; refuse a different one unless rotating."""
    value = identity_check_value(identity_hash_key)
    async with conn.transaction():
        cursor = await conn.execute(
            "INSERT INTO neuron_meta (key, value) VALUES (%s, %s)"
            " ON CONFLICT (key) DO NOTHING RETURNING value",
            (_IDENTITY_META_KEY, value),
        )
        if await cursor.fetchone() is not None:
            logger.info("identity_key_check_written")
            audit(
                "identity_key_check_written",
                outcome="allowed",
                action="identity_key:record",
                resource_type="identity_key",
            )
            return
        cursor = await conn.execute(
            "SELECT value FROM neuron_meta WHERE key = %s", (_IDENTITY_META_KEY,)
        )
        row = await cursor.fetchone()
        stored = str(row["value"]) if row else ""
        if hmac.compare_digest(stored, value):
            logger.info("identity_key_check_verified")
            return
        if not rotate:
            raise IdentityKeyMismatch(
                "APP_IDENTITY_HASH_KEY differs from the key this database was set up with;"
                " rotating it orphans existing threads (OPERATIONS.md), so pass"
                " --rotate-identity-key to replace the stored check value"
            )
        await conn.execute(
            "UPDATE neuron_meta SET value = %s, updated_at = now() WHERE key = %s",
            (value, _IDENTITY_META_KEY),
        )
        logger.warning("identity_key_check_rotated")
        audit(
            "identity_key_check_rotated",
            outcome="allowed",
            action="identity_key:rotate",
            resource_type="identity_key",
        )


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
    after_ddl: Callable[[psycopg.AsyncConnection[dict[str, object]]], Awaitable[None]]
    | None = None,
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
                if after_ddl is not None:
                    # Same transaction: a table the migration made is tightened or not made.
                    await after_ddl(conn)
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
