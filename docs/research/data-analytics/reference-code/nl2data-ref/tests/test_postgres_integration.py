"""Defence-in-depth on real Postgres 16: the DATABASE must hold even when the guard is
bypassed. Requires PG_TEST_DSN_ADMIN and PG_TEST_DSN_AGENT; skipped otherwise."""
import os
import pathlib

import psycopg
import pytest

from nl2data_ref.executor import Identity, NoResultSet, execute
from nl2data_ref.guard import Scope, validate

ADMIN = os.environ.get("PG_TEST_DSN_ADMIN")
AGENT = os.environ.get("PG_TEST_DSN_AGENT")
pytestmark = pytest.mark.skipif(not (ADMIN and AGENT), reason="no test Postgres")

APAC = Identity("u123", "finance", ("APAC",))
SCOPE = Scope(frozenset({"certified.fct_revenue"}),
              {"certified": {"fct_revenue": {"region": "text", "fiscal_quarter": "text",
                                              "net_revenue": "numeric"}}})


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    ddl = (pathlib.Path(__file__).parents[1] / "sql" / "001_hardened_model_b.sql").read_text()
    with psycopg.connect(ADMIN, autocommit=True) as c:
        c.execute(ddl)


@pytest.fixture
def conn():
    with psycopg.connect(AGENT) as c:
        yield c


def run_raw(conn, sql):
    """Bypass the guard on purpose: what does the database alone allow?"""
    return execute(conn, sql, (), APAC)


def test_rls_scopes_rows(conn):
    v = validate("SELECT region, SUM(net_revenue) AS rev FROM certified.fct_revenue GROUP BY region", SCOPE)
    cols, rows, _ = execute(conn, v.sql, (), APAC)
    assert {r[0] for r in rows} == {"APAC"}


def test_missing_claims_fail_closed():
    with psycopg.connect(AGENT) as c:
        with c.transaction():
            c.execute("SET LOCAL ROLE agent_ro_finance")
            assert c.execute("SELECT count(*) FROM certified.fct_revenue").fetchone()[0] == 0


@pytest.mark.parametrize("sql,needle", [
    ("SELECT 1; DROP TABLE certified.fct_revenue", "multiple commands"),
    ("SELECT set_config('app.regions', 'APAC,EMEA', true)", "permission denied"),
    ("SELECT app.set_claims('u123', ARRAY['EMEA'])", "permission denied"),
    ("SELECT set_config('role', 'agent_login_finance', true)", "permission denied"),
    ("SELECT * FROM pg_read_file('/etc/passwd')", "permission denied"),
    ("SELECT * FROM pg_ls_dir('/')", "permission denied"),
    ("DELETE FROM certified.fct_revenue", "read-only transaction"),
])
def test_database_blocks_guard_bypass(conn, sql, needle):
    with pytest.raises(psycopg.Error) as e:
        run_raw(conn, sql)
    assert needle in str(e.value).lower()


def test_cannot_see_other_region_even_with_where(conn):
    _, rows, _ = run_raw(conn, "SELECT region FROM certified.fct_revenue WHERE region = 'EMEA'")
    assert rows == []


def test_error_messages_name_the_right_object(conn):
    for sql, obj in [("SELECT set_config('app.regions','EMEA',true)", "function set_config"),
                     ("SELECT app.set_claims('u','{EMEA}')", "function set_claims")]:
        with pytest.raises(psycopg.Error) as e:
            run_raw(conn, sql)
        assert obj in str(e.value).lower()


def test_one_statement_per_transaction_invariant(conn):
    """Plain SET can change a custom GUC without privileges. Model B therefore REQUIRES that the
    executor runs exactly one model-authored statement per transaction (never a SET followed
    by a SELECT). This test documents the invariant: a SET alone returns nothing and the next
    call starts a fresh transaction with fresh claims."""
    with pytest.raises(NoResultSet):
        run_raw(conn, "SET LOCAL app.regions = 'APAC,EMEA'")   # no result set -> rolled back
    _, rows, _ = run_raw(conn, "SELECT DISTINCT region FROM certified.fct_revenue")
    assert {r[0] for r in rows} == {"APAC"}
