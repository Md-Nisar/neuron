# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Checks that the app role is the least-privilege role ADR 0008 decision 15 describes.

Used by `setup` (after granting, in production) and by the web process at start-up (in
production). Messages are fixed text built from fixed phrases: never a DSN, host or role name
taken from a driver message.
"""

from __future__ import annotations

from typing import Any

import psycopg

from neuron_agent.persistence.startup_checks import (
    ROLE_NOT_APP_USER,
    ROLE_TOO_PRIVILEGED,
    StartupCheckError,
)


class AppRoleError(StartupCheckError):
    """The app role is unusable or too privileged. The text is fixed and safe to print."""

    def __init__(self, message: str, code: str = ROLE_TOO_PRIVILEGED) -> None:
        super().__init__(message, code)


_ROLE_SQL = """
SELECT r.rolsuper AS superuser,
       r.rolbypassrls AS bypassrls,
       pg_has_role(r.rolname, n.nspowner, 'MEMBER') AS owner_member,
       (%(migrator)s::text IS NOT NULL
           AND pg_has_role(r.rolname, %(migrator)s::text::name, 'MEMBER')) AS migrator_member,
       has_schema_privilege(r.rolname, n.oid, 'CREATE') AS can_create
FROM pg_roles AS r, pg_namespace AS n
WHERE r.rolname = %(role)s AND n.nspname = current_schema()
"""


async def role_problems(
    conn: psycopg.AsyncConnection[Any], role: str, *, migrator: str | None = None
) -> list[str]:
    """Fixed phrases naming what is wrong with `role`; empty when it is safe."""
    cursor = await conn.execute(_ROLE_SQL, {"role": role, "migrator": migrator})
    row = await cursor.fetchone()
    if row is None:
        return ["the role does not exist"]
    found = {
        "is a superuser": row["superuser"],
        "bypasses row-level security": row["bypassrls"],
        "is a member of the schema owner": row["owner_member"],
        "is a member of the migration role": row["migrator_member"],
        "can create objects in the schema": row["can_create"],
    }
    return [problem for problem, present in found.items() if present]


async def verify_runtime_role(conn: psycopg.AsyncConnection[Any], app_role: str) -> None:
    """Web start-up check (production): connected as the app role, and it is not privileged."""
    cursor = await conn.execute("SELECT current_user::text AS name")
    row = await cursor.fetchone()
    if row is None or row["name"] != app_role:
        raise AppRoleError("the database user is not APP_POSTGRES_APP_ROLE", ROLE_NOT_APP_USER)
    problems = await role_problems(conn, app_role)
    if problems:
        raise AppRoleError("the runtime database role is too privileged: " + "; ".join(problems))
