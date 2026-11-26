import pytest

from nl2data_ref.guard import Policy, Scope, validate

SCHEMA = {"certified": {
    "fct_revenue": {"region": "text", "fiscal_quarter": "text", "net_revenue": "numeric",
                    "order_date": "date", "customer_id": "int"},
    "dim_customer": {"customer_id": "int", "name": "text", "segment": "text"}}}
SCOPE = Scope(readable_tables=frozenset({"certified.fct_revenue", "certified.dim_customer"}),
              schema=SCHEMA)

MUST_PASS = [
    "SELECT region, SUM(net_revenue) FROM certified.fct_revenue GROUP BY region",
    "WITH q AS (SELECT region, net_revenue FROM certified.fct_revenue) SELECT region, AVG(net_revenue) FROM q GROUP BY region",
    "SELECT region FROM certified.fct_revenue UNION SELECT segment FROM certified.dim_customer",
    "SELECT c.segment, COUNT(DISTINCT r.customer_id) FROM certified.fct_revenue r JOIN certified.dim_customer c ON r.customer_id = c.customer_id GROUP BY 1",
    "SELECT DATE_TRUNC('month', order_date) AS m, SUM(net_revenue) FROM certified.fct_revenue GROUP BY 1 ORDER BY 1",
    "SELECT region, RANK() OVER (ORDER BY SUM(net_revenue) DESC) FROM certified.fct_revenue GROUP BY region",
    "SELECT CASE WHEN net_revenue > 0 THEN 'pos' ELSE 'neg' END, COALESCE(region, 'n/a') FROM certified.fct_revenue",
    "SELECT EXTRACT(year FROM order_date), ROUND(AVG(net_revenue), 2) FROM certified.fct_revenue GROUP BY 1",
]

# (sql, expected rejection code)
MUST_REJECT = [
    ("SELECT 1; COMMIT; DROP SCHEMA public CASCADE;", "MULTI_STATEMENT"),          # Datadog 2025
    ("SELECT * FROM pg_read_file('/etc/passwd')", "FUNCTION_NOT_ALLOWED"),          # CVE-2026-85620 pattern
    ("SELECT pg_read_file('/etc/passwd')", "FUNCTION_NOT_ALLOWED"),
    ("SELECT pg_stat_file('/etc/passwd')", "FUNCTION_NOT_ALLOWED"),                 # passed old deny-list
    ("SELECT lo_get(1234)", "FUNCTION_NOT_ALLOWED"),                                # passed old deny-list
    ("SELECT set_config('app.user_id','admin',true)", "FUNCTION_NOT_ALLOWED"),
    ("SELECT pg_catalog.set_config('role','admin',true)", "FUNCTION_NOT_ALLOWED"),
    ('SELECT "set_config"(\'app.user_id\',\'admin\',true)', "FUNCTION_NOT_ALLOWED"),
    ("SELECT current_setting('app.user_id')", "FUNCTION_NOT_ALLOWED"),
    ("SELECT pg_sleep(10)", "FUNCTION_NOT_ALLOWED"),
    ("SELECT dblink('host=x', 'select 1')", "FUNCTION_NOT_ALLOWED"),
    ("SELECT query_to_xml('select * from secrets', true, true, '')", "FUNCTION_NOT_ALLOWED"),
    ("SELECT * FROM certified.fct_revenue, LATERAL pg_ls_dir('/') d", "FUNCTION_NOT_ALLOWED"),
    ("SELECT region FROM certified.fct_revenue FOR UPDATE", "FORBIDDEN_NODE"),       # passed old guard
    ("SELECT region INTO tmp FROM certified.fct_revenue", "FORBIDDEN_NODE"),
    ("SELECT usename, passwd FROM pg_catalog.pg_shadow", "SYSTEM_SCHEMA"),
    ("SELECT * FROM information_schema.tables", "SYSTEM_SCHEMA"),
    ("SELECT * FROM finance.salaries", "UNKNOWN_OR_FORBIDDEN_TABLE"),
    ("SELECT bogus FROM certified.fct_revenue", "UNKNOWN_IDENTIFIER"),
    ("SELECT count(*) FROM generate_series(1, 1000000000000)", "FUNCTION_NOT_ALLOWED"),
    ("WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM r) SELECT n FROM r", "RECURSIVE_CTE"),
    ("COPY certified.fct_revenue TO '/tmp/x'", "NOT_READ_QUERY"),
    ("VALUES (1)", "NOT_READ_QUERY"),
    ("DELETE FROM certified.fct_revenue", "NOT_READ_QUERY"),
    ("UPDATE certified.fct_revenue SET region = 'x'", "NOT_READ_QUERY"),
    ("EXPLAIN ANALYZE SELECT 1", "NOT_READ_QUERY"),
    ("SELECT region FROM certified.fct_revenue WHERE region IN (SELECT pg_read_binary_file('/x')::text)", "FUNCTION_NOT_ALLOWED"),
]


@pytest.mark.parametrize("sql", MUST_PASS)
def test_legitimate_queries_pass(sql):
    v = validate(sql, SCOPE)
    assert v.ok, (v.code, v.detail)
    assert "LIMIT" in v.sql.upper()


@pytest.mark.parametrize("sql,code", MUST_REJECT)
def test_attacks_rejected(sql, code):
    v = validate(sql, SCOPE)
    assert not v.ok
    assert v.code == code, (v.code, v.detail)


def test_limit_clamped():
    v = validate("SELECT region FROM certified.fct_revenue LIMIT 100000000", SCOPE)
    assert v.ok and "LIMIT 1000" in v.sql and "100000000" not in v.sql


def test_small_limit_kept():
    v = validate("SELECT region FROM certified.fct_revenue LIMIT 10", SCOPE)
    assert v.ok and "LIMIT 10" in v.sql


def test_comments_are_not_reemitted():
    v = validate("SELECT region FROM certified.fct_revenue /*; DROP TABLE x */", SCOPE)
    assert v.ok and "DROP" not in v.sql


def test_too_many_tables():
    sql = "SELECT 1 FROM " + ", ".join(f"certified.fct_revenue t{i}" for i in range(9))
    v = validate(sql, SCOPE, Policy(max_tables=8))
    assert not v.ok and v.code == "TOO_MANY_TABLES"


def test_boolean_operators_and_exists_are_not_functions():
    # F4: with sqlglot 30, AND/OR/EXISTS are Func subclasses and were rejected as functions.
    v = validate("SELECT region FROM certified.fct_revenue WHERE net_revenue > 1 AND region = 'EU' "
                 "OR NOT region = 'US' AND EXISTS (SELECT 1 FROM certified.dim_customer)", SCOPE)
    assert v.ok, v.detail
    # Real functions outside the allowlist are still rejected.
    v = validate("SELECT pg_sleep(1) FROM certified.fct_revenue WHERE net_revenue > 1 AND region = 'EU'", SCOPE)
    assert not v.ok and v.code == "FUNCTION_NOT_ALLOWED"
