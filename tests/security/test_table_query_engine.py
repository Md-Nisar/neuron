"""The `query_table` engine refuses everything but reading its one table (RAG-11.01).

ADR 0014 amendment "tables": SQLite's authorizer, limits and progress handler enforce the rules
when the query is prepared or run, so each case here is refused by SQLite itself.
"""

from __future__ import annotations

import sqlite3
import time

import pytest

from neuron_agent.knowledge import table_engine
from neuron_agent.knowledge.table_engine import (
    MAX_RESULT_CHARS,
    MAX_ROWS,
    MAX_SQL_CHARS,
    MAX_VALUE_CHARS,
    TableQueryError,
    run_query,
)

COLUMNS = [("region", "text"), ("units", "integer"), ("price", "real")]
ROWS = [("North", 3, 2.5), ("West", 5, 1.0), ("North", 4, None)]


def _code(sql: str) -> str:
    with pytest.raises(TableQueryError) as caught:
        run_query(COLUMNS, ROWS, sql)
    return caught.value.code


def test_a_select_returns_its_columns_and_rows() -> None:
    result = run_query(
        COLUMNS,
        ROWS,
        "WITH t AS (SELECT * FROM data) SELECT region, SUM(units) AS n, ROUND(AVG(price), 2)"
        " FROM t WHERE region LIKE 'n%' OR units > 4 GROUP BY region ORDER BY n DESC",
    )
    assert result.columns == ("region", "n", "ROUND(AVG(price), 2)")
    assert result.rows == (("North", 7, 2.5), ("West", 5, 1.0))
    assert not result.truncated


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO data VALUES ('x', 1, 1.0)",
        "UPDATE data SET units = 0",
        "DELETE FROM data",
        "DROP TABLE data",
        "CREATE TABLE t (a)",
        "CREATE TEMP TABLE t (a)",
        "CREATE VIEW v AS SELECT 1",
        "ALTER TABLE data ADD COLUMN b",
        "PRAGMA table_info(data)",
        "PRAGMA hard_heap_limit = 0",
        "ATTACH DATABASE '/tmp/neuron-probe.db' AS probe",
        "ATTACH DATABASE 'file:x?mode=memory' AS probe",
        "DETACH DATABASE main",
        "VACUUM INTO '/tmp/neuron-probe.db'",
        "VACUUM",
        "BEGIN",
        "SAVEPOINT a",
        "ANALYZE",
        "REINDEX",
        "SELECT * FROM sqlite_master",
        "SELECT * FROM sqlite_schema",
        "SELECT * FROM sqlite_temp_master",
        "SELECT * FROM pragma_table_info('data')",
        "SELECT load_extension('/tmp/x.so')",
        "SELECT randomblob(1000000000)",
        "SELECT zeroblob(1000000000)",
        "SELECT printf('%.*c', 1000000000, 'x')",
        "SELECT sqlite_version()",
        "SELECT hex(region) FROM data",
        "WITH RECURSIVE c(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM c) SELECT max(n) FROM c",
        "SELECT 1; DROP TABLE data",
        "SELECT 1; SELECT 2",
    ],
)
def test_anything_but_reading_the_table_is_refused(sql: str) -> None:
    assert _code(sql) == "query_refused"
    # The table is untouched.
    assert run_query(COLUMNS, ROWS, "SELECT count(*) FROM data").rows == ((3,),)


def test_a_long_query_stops_with_a_fixed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(table_engine, "TIMEOUT_SECONDS", 0.2)
    joins = ", ".join(f"data t{i}" for i in range(20))
    started = time.monotonic()
    assert _code(f"SELECT count(*) FROM {joins}") == "query_timeout"  # noqa: S608
    assert time.monotonic() - started < 2


def test_sql_and_strings_past_the_caps_are_too_large() -> None:
    assert _code("SELECT 1" + " " * MAX_SQL_CHARS) == "query_too_large"
    grow = "'" + "a" * 1_000 + "'"
    for _ in range(4):  # ten thousand times longer: past the string cap
        grow = f"replace({grow}, 'a', 'aaaaaaaaaa')"
    assert _code(f"SELECT length({grow})") == "query_too_large"


def test_the_heap_is_capped_for_the_process() -> None:
    run_query(COLUMNS, ROWS, "SELECT 1")
    conn = sqlite3.connect(":memory:")
    try:
        assert conn.execute("PRAGMA hard_heap_limit").fetchone() == (256 * 1024 * 1024,)
    finally:
        conn.close()


def test_results_are_capped_in_rows_and_value_length() -> None:
    rows = [("x" * (MAX_VALUE_CHARS + 50) if i == 0 else "x", i, 0.0) for i in range(MAX_ROWS + 5)]
    result = run_query(COLUMNS, rows, "SELECT region FROM data")
    assert len(result.rows) == MAX_ROWS
    assert result.truncated
    assert result.rows[0][0] == "x" * MAX_VALUE_CHARS + "…"


def test_wide_results_of_long_strings_stop_at_the_result_budget() -> None:
    big = "replace('" + "a" * 2_000 + "', 'a', 'aaaaaaaaaa')"  # 20,000 characters
    sql = f"WITH t AS (SELECT {big} AS s) SELECT {', '.join(['s'] * 50)} FROM t, data"  # noqa: S608
    result = run_query(COLUMNS, [("x", i, 0.0) for i in range(300)], sql)
    assert result.truncated
    assert sum(len(str(c)) for row in result.rows for c in row) <= MAX_RESULT_CHARS
    assert _code("SELECT " + ", ".join(["1"] * 101)) == "query_too_large"


def test_a_table_sqlite_will_not_load_fails_with_a_fixed_error() -> None:
    with pytest.raises(TableQueryError) as caught:
        run_query([("a", "text"), ("A", "text")], [("x", "y")], "SELECT 1")
    assert (caught.value.code, caught.value.detail) == (
        "query_failed",
        "the table could not be loaded",
    )


def test_non_finite_numbers_come_back_as_text() -> None:
    assert run_query(COLUMNS, ROWS, "SELECT 1e999, -1e999").rows == (("inf", "-inf"),)


def test_a_hostile_column_name_is_only_a_name() -> None:
    name = 'x" TEXT); DROP TABLE data; --'
    result = run_query(
        [(name, "text")], [("a",)], 'SELECT "x"" TEXT); DROP TABLE data; --" FROM data'
    )
    assert result.rows == (("a",),)


@pytest.mark.parametrize("function", ["readfile('/etc/passwd')", "writefile('/tmp/x', 'y')"])
def test_file_functions_do_not_exist(function: str) -> None:
    with pytest.raises(TableQueryError) as caught:
        run_query(COLUMNS, ROWS, f"SELECT {function}")
    assert caught.value.code == "query_failed"
    assert (caught.value.detail or "").startswith("no such function")


def test_a_mistake_in_the_sql_says_what_sqlite_said() -> None:
    with pytest.raises(TableQueryError) as caught:
        run_query(COLUMNS, ROWS, "SELECT nope FROM data")
    assert (caught.value.code, caught.value.detail) == ("query_failed", "no such column: nope")
