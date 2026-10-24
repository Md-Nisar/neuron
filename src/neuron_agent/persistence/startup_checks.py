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
        cursor = await conn.execute("SELECT neuron_identity_status(%s) AS status", (check_value,))
    except psycopg.errors.UndefinedFunction:
        # `setup` has not run migration 12 yet: nothing is recorded.
        status = "unset"
    else:
        row = await cursor.fetchone()
        status = row["status"] if row else None
    if status == "match":
        return
    if status == "unset":
        raise StartupCheckError(
            "no identity key check value is recorded; run setup with APP_IDENTITY_HASH_KEY",
            IDENTITY_KEY_UNRECORDED,
        )
    raise StartupCheckError(
        "APP_IDENTITY_HASH_KEY differs from the key this database was set up with",
        IDENTITY_KEY_MISMATCH,
    )
