# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Read-only SQL over one stored table, on SQLite from the standard library (RAG-11.01).

ADR 0014 amendment "tables": each call gets a new in-memory database holding one table, `data`.
SQLite itself enforces the rules, so no second parser can read the SQL differently:

- an authorizer allows `SELECT`, reads of `data` and the functions in `FUNCTIONS`, and refuses
  everything else (`PRAGMA`, `ATTACH`, recursive CTEs, the schema tables, writes);
- once loaded, the database is query-only; a statement that returns no columns is refused;
  extensions are never enabled; defensive mode and an untrusted schema are on; `sqlite3` runs
  one statement per call;
- a progress handler stops a query after `TIMEOUT_SECONDS`; SQLite's heap is capped at
  `HEAP_LIMIT_BYTES` for the whole process (nothing else in Neuron uses SQLite), temporary
  storage included; `setlimit` caps the SQL text, strings, columns and attached databases;
- results are converted a row at a time and cut at `MAX_ROWS` rows and `MAX_RESULT_CHARS`.

Blocking: callers run it in a thread. Errors carry a fixed code; only `query_failed` has a
detail, SQLite's own message about the SQL (a syntax error, an unknown column).
"""

from __future__ import annotations

import math
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass

from neuron_agent.knowledge.parsing import MAX_TABLE_COLUMNS
from neuron_agent.knowledge.tables import Value

TIMEOUT_SECONDS = 5.0
HEAP_LIMIT_BYTES = 256 * 1024 * 1024
MAX_SQL_CHARS = 10_000
MAX_ROWS = 200
MAX_VALUE_CHARS = 1_000
MAX_RESULT_CHARS = 100_000
_MAX_STRING_BYTES = 200_000  # above a CSV field's 128 KiB
_PROGRESS_STEPS = 10_000  # virtual machine steps between deadline checks
_TYPES = {"integer": "INTEGER", "real": "REAL", "text": "TEXT"}
# Aggregates, window functions, arithmetic, strings and dates. Not `printf`/`format`,
# `randomblob`, `zeroblob`, `load_extension` or anything that reads SQLite's own state.
FUNCTIONS = frozenset(
    {
        *("count", "sum", "total", "avg", "min", "max", "group_concat", "string_agg"),
        *("row_number", "rank", "dense_rank", "ntile", "lag", "lead"),
        *("first_value", "last_value", "nth_value", "percent_rank", "cume_dist"),
        *("abs", "round", "sign", "floor", "ceil", "ceiling", "sqrt", "power", "pow", "mod"),
        *("length", "lower", "upper", "trim", "ltrim", "rtrim", "substr", "substring"),
        *("replace", "instr", "like", "glob", "coalesce", "ifnull", "nullif", "iif", "typeof"),
        *("date", "time", "datetime", "julianday", "strftime", "unixepoch"),
    }
)


class TableQueryError(Exception):
    """`query_refused`, `query_timeout`, `query_too_large` or `query_failed`."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[Value, ...], ...]
    truncated: bool  # more than `MAX_ROWS` rows, or past `MAX_RESULT_CHARS`


def run_query(
    columns: Sequence[tuple[str, str]], rows: Sequence[Sequence[Value]], sql: str
) -> QueryResult:
    """Run `sql` against `data`, a table of `columns` (name, type) holding `rows`."""
    if len(sql) > MAX_SQL_CHARS:
        raise TableQueryError("query_too_large")
    conn = sqlite3.connect(":memory:", autocommit=True)
    deadline = time.monotonic() + TIMEOUT_SECONDS
    try:
        try:
            _load(conn, columns, rows)
        except (sqlite3.Error, KeyError):  # stored data SQLite will not take: never the model's
            raise TableQueryError("query_failed", "the table could not be loaded") from None
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), _PROGRESS_STEPS)
        conn.set_authorizer(_authorize)
        cursor = conn.execute(sql)
        if cursor.description is None:  # not a query (REINDEX with no index needs no grant)
            raise TableQueryError("query_refused")
        names = tuple(str(d[0]) for d in cursor.description)
        out: list[tuple[Value, ...]] = []
        budget, truncated = MAX_RESULT_CHARS, False
        # Row by row, each cut as it arrives: Python's copies are outside SQLite's heap cap.
        for row in cursor:
            cells = tuple(map(_cell, row))
            budget -= sum(len(str(c)) for c in cells)
            if len(out) == MAX_ROWS or budget < 0:
                truncated = True
                break
            out.append(cells)
    except sqlite3.ProgrammingError:  # more than one statement
        raise TableQueryError("query_refused") from None
    except sqlite3.DatabaseError as exc:
        raise _error(exc, deadline) from None
    except MemoryError:
        raise TableQueryError("query_too_large") from None
    finally:
        conn.close()
    return QueryResult(names, tuple(out), truncated)


def _load(
    conn: sqlite3.Connection, columns: Sequence[tuple[str, str]], rows: Sequence[Sequence[Value]]
) -> None:
    conn.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True)
    conn.setconfig(sqlite3.SQLITE_DBCONFIG_TRUSTED_SCHEMA, False)
    conn.execute(f"PRAGMA hard_heap_limit = {HEAP_LIMIT_BYTES}")
    conn.execute("PRAGMA temp_store = MEMORY")  # sorts stay under the heap cap, not on disk
    conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, MAX_SQL_CHARS)
    conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, _MAX_STRING_BYTES)
    conn.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
    conn.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, MAX_TABLE_COLUMNS)
    # Names come from the file: quoted as identifiers, never interpolated bare.
    definition = ", ".join(f"{_quote(name)} {_TYPES[kind]}" for name, kind in columns)
    conn.execute(f"CREATE TABLE data ({definition})")  # nosec B608 - quoted identifiers
    marks = ", ".join("?" * len(columns))
    insert = f"INSERT INTO data VALUES ({marks})"  # noqa: S608  # nosec B608 - placeholders
    conn.executemany(insert, rows)
    conn.execute("PRAGMA query_only = ON")


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _authorize(action: int, arg1: str | None, arg2: str | None, db: str | None, _: object) -> int:
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ and arg1 == "data" and db in (None, "main"):
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_FUNCTION and arg2 is not None and arg2.lower() in FUNCTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _error(exc: sqlite3.DatabaseError, deadline: float) -> TableQueryError:
    message = str(exc)
    if "authoriz" in message or "prohibited" in message:
        return TableQueryError("query_refused")
    if message == "interrupted" and time.monotonic() > deadline:
        return TableQueryError("query_timeout")
    if any(s in message for s in ("too big", "too long", "too many columns", "out of memory")):
        return TableQueryError("query_too_large")
    return TableQueryError("query_failed", message[:200])


def _cell(value: Value | bytes) -> Value:
    if isinstance(value, bytes):  # only from a blob literal: shown, not decoded
        value = "x'" + value[: MAX_VALUE_CHARS // 2].hex() + "'"
    if isinstance(value, float) and not math.isfinite(value):  # JSON has no inf or nan
        return str(value)
    if isinstance(value, str) and len(value) > MAX_VALUE_CHARS:
        return value[:MAX_VALUE_CHARS] + "…"
    return value
