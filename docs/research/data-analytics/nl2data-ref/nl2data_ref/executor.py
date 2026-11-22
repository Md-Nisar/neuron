"""Identity-aware executor (Postgres, identity model B). Runs ONLY guard-approved SQL.

Order inside one read-only transaction:
  1. SET LOCAL statement_timeout            (bounded runtime)
  2. app.set_claims(user, regions)          (SECURITY DEFINER; the only way to set claims)
  3. SET LOCAL ROLE <domain data role>      (role allow-list; never from model input)
  4. execute the validated SQL with bound parameters (extended protocol: one statement only)
"""
from __future__ import annotations

from dataclasses import dataclass

import psycopg
from psycopg import sql as psql

DOMAIN_ROLES = {"finance": "agent_ro_finance"}


class NoResultSet(RuntimeError):
    """The statement produced no rows/description (e.g. SET, RESET): rejected, txn rolled back."""


@dataclass(frozen=True)
class Identity:
    user_id: str
    domain: str
    regions: tuple[str, ...]
    trace_id: str = "-"


def execute(conn: psycopg.Connection, validated_sql: str, params: tuple, ident: Identity,
            timeout_s: int = 15, max_rows: int = 1000):
    role = DOMAIN_ROLES[ident.domain]                       # KeyError = fail closed
    with conn.transaction():
        cur = conn.cursor()
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute(psql.SQL("SET LOCAL statement_timeout = {}").format(
            psql.Literal(f"{int(timeout_s)}s")))
        cur.execute("SELECT app.set_claims(%s, %s)", (ident.user_id, list(ident.regions)))
        cur.execute(psql.SQL("SET LOCAL ROLE {}").format(psql.Identifier(role)))
        cur.execute(validated_sql, params, prepare=True)    # extended protocol
        if cur.description is None:
            raise NoResultSet("statement returned no result set")
        cols = [d.name for d in cur.description]
        rows = cur.fetchmany(max_rows + 1)
    return cols, rows[:max_rows], len(rows) > max_rows
