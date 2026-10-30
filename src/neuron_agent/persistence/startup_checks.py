# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Database start-up checks for staging and production (ADR 0008 decisions 15 and 16).

Every failure is a `StartupCheckError` with a stable `code` and fixed text: never a DSN, host,
password, role name from a driver message, or key. The process refuses to start on any of them
(the same behaviour as a too-privileged role), and logs the code once.
"""

from __future__ import annotations

from typing import Any

import psycopg

# Stable codes, documented in OPERATIONS.md (Thread Persistence). Never rename one.
ROLE_NOT_APP_USER = "role_not_app_user"
ROLE_TOO_PRIVILEGED = "role_too_privileged"
TLS_REQUIRED = "tls_required"
IDENTITY_KEY_MISMATCH = "identity_key_mismatch"
IDENTITY_KEY_UNRECORDED = "identity_key_unrecorded"
IDENTITY_CHECK_UNSAFE = "identity_check_unsafe"
STORE_MISSING = "store_missing"
STORE_NO_ACCESS = "store_no_access"
DATABASE_CHECK_FAILED = "database_check_failed"


class StartupCheckError(Exception):
    """A start-up check failed. `code` is stable; the text is fixed and safe to print."""

    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


async def verify_tls(conn: psycopg.AsyncConnection[Any]) -> None:
    """Refuse a connection that is not TLS, as the server sees it (`pg_stat_ssl`).

    A role may read its own backend's row. Behind a transaction pooler this describes the
    pooler's connection to Postgres, not the client's to the pooler.
    """
    cursor = await conn.execute("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
    row = await cursor.fetchone()
    if row is None or row["ssl"] is not True:
        raise StartupCheckError(
            "the database connection does not use TLS; use sslmode=verify-full (or require)",
            TLS_REQUIRED,
        )


async def verify_identity_key(conn: psycopg.AsyncConnection[Any], check_value: str) -> None:
    """Refuse a key that differs from the one `setup` recorded in `neuron_meta`.

    The app role cannot read `neuron_meta`; the SECURITY DEFINER function from migration
    `identity_status_function` answers match, mismatch or unset for the candidate only.
    """
    status: str | None
    try:
        # Whatever the session's search_path resolves must be the migrator's SECURITY DEFINER
        # function, not one the app role created in an earlier schema.
        cursor = await conn.execute(
            "SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_proc p"
            " WHERE p.oid = to_regprocedure('neuron_identity_status(text)')"
            " AND p.prosecdef AND pg_get_userbyid(p.proowner) <> current_user)"
            " THEN neuron_identity_status(%s) ELSE 'unsafe' END AS status",
            (check_value,),
        )
    except psycopg.errors.UndefinedFunction:
        # `setup` has not run migration 12 yet: nothing is recorded.
        status = "unset"
    else:
        row = await cursor.fetchone()
        status = row["status"] if row else None
    if status == "match":
        return
    if status == "unsafe":
        raise StartupCheckError(
            "the identity check function is not the migrator's SECURITY DEFINER function",
            IDENTITY_CHECK_UNSAFE,
        )
    if status == "unset":
        raise StartupCheckError(
            "no identity key check value is recorded; run setup with APP_IDENTITY_HASH_KEY",
            IDENTITY_KEY_UNRECORDED,
        )
    raise StartupCheckError(
        "APP_IDENTITY_HASH_KEY differs from the key this database was set up with",
        IDENTITY_KEY_MISMATCH,
    )


async def verify_store(conn: psycopg.AsyncConnection[Any]) -> None:
    """Refuse start-up with memory on when the `store` table is missing or this role cannot use it.

    Readiness would report the missing table too, but a replica that cannot serve memory should
    not start and replace one that can.
    """
    cursor = await conn.execute(
        "SELECT to_regclass('store') IS NOT NULL AS present,"
        " COALESCE(has_table_privilege(current_user, to_regclass('store'),"
        " 'SELECT,INSERT,UPDATE,DELETE'), false) AS usable"
    )
    row = await cursor.fetchone()
    if row is None or not row["present"]:
        raise StartupCheckError(
            "memory is enabled but the store table does not exist; "
            "run setup with APP_MEMORY_ENABLED=true",
            STORE_MISSING,
        )
    if not row["usable"]:
        raise StartupCheckError(
            "the database role cannot read and write the memory store; run setup to grant it",
            STORE_NO_ACCESS,
        )
