"""DG-00.06: nl2data-ref's guard-bypassed database tests, repeated against the D3 mart.

  D3_DSN="host=... port=..." pytest test_mart_bypass.py

Source: docs/research/data-analytics/reference-code/nl2data-ref/tests/test_postgres_integration.py.
That file tests its own "model B" schema (one agent login, claims in a setting). The mart is
hardened differently (A', D5): one login per data role, the region scope keyed on the data role
through app.role_regions, set_config revoked from PUBLIC, no claims function. Each test below is
the same attack with the guard bypassed, mapped to the mart; the mapping is in each docstring.
Every statement goes through the A' executor's order (BEGIN READ ONLY, SET LOCAL ROLE, timeout).
"""

import json
import os
import pathlib

import psycopg
import pytest
from psycopg import sql as psql

DSN = os.environ["D3_DSN"]
PERSONAS = json.loads((pathlib.Path(__file__).parents[1] / "d3/personas.json").read_text())
APAC = PERSONAS["apac_analyst"]
EMEA = PERSONAS["emea_analyst"]


def run_raw(persona: dict, sql: str):
    """Bypass the guard on purpose: what does the database alone allow?"""
    with psycopg.connect(f"{DSN} dbname=d3 user={persona['login']}") as conn:
        cur = conn.cursor()
        try:
            cur.execute("BEGIN READ ONLY")
            cur.execute(psql.SQL("SET LOCAL ROLE {}").format(psql.Identifier(persona["role"])))
            cur.execute("SET LOCAL statement_timeout = '15s'")
            cur.execute(sql)
            return cur.fetchall() if cur.description else None
        finally:
            conn.rollback()


def test_rls_scopes_rows():
    """test_rls_scopes_rows: a region breakdown returns the caller's region only."""
    rows = run_raw(APAC, "SELECT region_id, count(*) FROM sales.orders GROUP BY region_id")
    assert {r[0] for r in rows} == {"APAC"}


def test_missing_claims_fail_closed():
    """test_missing_claims_fail_closed: under A' the 'claims' are the data role. A login that has
    not switched into its data role reads nothing, and a data role with no region mapping (as
    the login itself has none) sees no rows."""
    with psycopg.connect(f"{DSN} dbname=d3 user={APAC['login']}") as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT count(*) FROM sales.orders")


@pytest.mark.parametrize(
    "sql,needle",
    [
        ("SELECT 1; DROP TABLE sales.orders", "read-only transaction"),
        ("SELECT set_config('app.regions', 'APAC,EMEA', true)", "permission denied"),
        ("SELECT app.set_claims('u123', ARRAY['EMEA'])", "does not exist"),
        ("SELECT set_config('role', 'd3_manager', true)", "permission denied"),
        ("SELECT * FROM pg_read_file('/etc/passwd')", "permission denied"),
        ("SELECT * FROM pg_ls_dir('/')", "permission denied"),
        ("DELETE FROM sales.orders", "read-only transaction"),
    ],
)
def test_database_blocks_guard_bypass(sql, needle):
    """test_database_blocks_guard_bypass, same seven statements. Two expectations differ, both
    stronger or equivalent on the mart: the multi-statement case fails on the DROP itself
    (read-only) rather than on the protocol, because psycopg sends a parameterless call as one
    simple query; and app.set_claims does not exist under A' (there are no claims to set)."""
    with pytest.raises(psycopg.Error) as e:
        run_raw(APAC, sql)
    assert needle in str(e.value).lower()


def test_cannot_see_other_region_even_with_where():
    """test_cannot_see_other_region_even_with_where."""
    assert run_raw(APAC, "SELECT region_id FROM sales.orders WHERE region_id = 'EMEA'") == []


def test_error_messages_name_the_right_object():
    """test_error_messages_name_the_right_object: set_config is named; the claims function does
    not exist on the mart, so its error names it as missing."""
    for sql, obj in [
        ("SELECT set_config('app.regions','EMEA',true)", "function set_config"),
        ("SELECT app.set_claims('u','{EMEA}')", "app.set_claims"),
    ]:
        with pytest.raises(psycopg.Error) as e:
            run_raw(APAC, sql)
        assert obj in str(e.value).lower()


def test_one_statement_per_transaction_invariant():
    """test_one_statement_per_transaction_invariant: a SET alone returns nothing, and the next
    call starts a fresh transaction. Under A' no setting carries scope, so a forged one does not
    widen the next read either."""
    assert run_raw(APAC, "SET LOCAL app.regions = 'APAC,EMEA'") is None
    rows = run_raw(APAC, "SELECT DISTINCT region_id FROM sales.orders")
    assert {r[0] for r in rows} == {"APAC"}


def test_role_switch_refused():
    """Added for A': moving into another data role is the A' equivalent of rewriting claims."""
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        run_raw(EMEA, "SET ROLE d3_analyst_apac")
