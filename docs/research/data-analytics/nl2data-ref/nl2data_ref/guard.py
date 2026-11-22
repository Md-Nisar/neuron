"""Allowlist-based SQL guard for agent-generated SQL.

Design rules (fail closed):
  * exactly one statement; root must be a read query (SELECT / set operation)
  * no DML, DDL, commands, SELECT ... INTO, locking clauses, recursive CTEs
  * every function must be on a per-dialect ALLOWLIST (deny-lists fail open)
  * every table must be in the caller's readable set; system schemas never
  * every column must resolve against the caller's schema snapshot
  * LIMIT is injected or clamped; table count is capped
  * the SQL that runs is re-emitted from the AST (comments and tricks dropped)

The database role remains the security boundary; this guard is defence in depth.
Tested with sqlglot 30.33.0 (pin the exact version you test).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.qualify import qualify

FORBIDDEN_NODES = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop,
    exp.Alter, exp.Command, exp.Into, exp.Lock, exp.Copy,
)

# Functions an analytics question legitimately needs. Extend deliberately, per dialect,
# and only after review: every addition is a potential side channel.
BASE_ALLOWED_FUNCS = frozenset({
    # aggregates
    "SUM", "COUNT", "AVG", "MIN", "MAX", "STDDEV", "STDDEV_POP", "STDDEV_SAMP",
    "VARIANCE", "VAR_POP", "VAR_SAMP", "APPROX_DISTINCT", "PERCENTILE_CONT",
    "PERCENTILE_DISC", "MEDIAN", "ARRAY_AGG", "STRING_AGG", "GROUP_CONCAT",
    # conditionals / nulls / casts
    "CASE", "IF", "COALESCE", "NULLIF", "GREATEST", "LEAST", "CAST", "TRY_CAST",
    # math
    "ABS", "ROUND", "CEIL", "FLOOR", "POWER", "SQRT", "LN", "LOG", "EXP", "MOD", "SIGN", "DIV",
    "SAFE_DIVIDE",
    # strings
    "LOWER", "UPPER", "TRIM", "LTRIM", "RTRIM", "LENGTH", "SUBSTRING", "CONCAT",
    "REPLACE", "LEFT", "RIGHT", "STARTS_WITH", "SPLIT_PART",
    # dates
    "CURRENT_DATE", "CURRENT_TIMESTAMP", "EXTRACT", "DATE_TRUNC", "TIMESTAMP_TRUNC",
    "DATE_ADD", "DATE_SUB", "DATE_DIFF", "DATEDIFF", "TS_OR_DS_ADD", "TS_OR_DS_TO_DATE",
    "TO_DATE", "STR_TO_DATE", "DATE", "TIME_TO_STR", "LAST_DAY",
    # window
    "ROW_NUMBER", "RANK", "DENSE_RANK", "NTILE", "LAG", "LEAD", "FIRST_VALUE",
    "LAST_VALUE", "PERCENT_RANK", "CUME_DIST",
})

SYSTEM_SCHEMAS = frozenset({"pg_catalog", "information_schema", "pg_toast",
                            "sys", "mysql", "performance_schema", "snowflake",
                            "account_usage"})


@dataclass(frozen=True)
class Scope:
    """What the calling principal may read. Built from the catalog, filtered by RBAC."""
    readable_tables: frozenset[str]              # fully qualified, lower-case: "schema.table"
    schema: dict                                 # sqlglot schema mapping for qualify()
    extra_allowed_funcs: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Policy:
    dialect: str = "postgres"
    max_rows: int = 1000
    max_tables: int = 8
    allow_recursive_cte: bool = False


@dataclass
class Verdict:
    ok: bool
    sql: str | None = None
    code: str | None = None
    detail: str | None = None
    warnings: list[str] = field(default_factory=list)

    @staticmethod
    def reject(code: str, detail: str) -> "Verdict":
        return Verdict(ok=False, code=code, detail=detail)


def _func_name(node: exp.Func) -> str:
    return (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).upper()


def _fqn(t: exp.Table) -> str:
    return ".".join(p for p in (t.catalog, t.db, t.name) if p).lower()


def validate(sql: str, scope: Scope, policy: Policy = Policy()) -> Verdict:
    try:
        stmts = [s for s in sqlglot.parse(sql, read=policy.dialect) if s is not None]
    except ParseError as e:
        return Verdict.reject("PARSE", str(e).splitlines()[0])
    if len(stmts) != 1:
        return Verdict.reject("MULTI_STATEMENT", f"{len(stmts)} statements; exactly one allowed")
    tree = stmts[0]
    if not isinstance(tree, exp.Query):
        return Verdict.reject("NOT_READ_QUERY", type(tree).__name__)

    allowed = BASE_ALLOWED_FUNCS | scope.extra_allowed_funcs
    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            return Verdict.reject("FORBIDDEN_NODE", type(node).__name__)
        if isinstance(node, exp.With) and node.args.get("recursive") and not policy.allow_recursive_cte:
            return Verdict.reject("RECURSIVE_CTE", "recursive CTEs are not allowed")
        if isinstance(node, exp.Func):
            name = _func_name(node)
            if name not in allowed:
                return Verdict.reject("FUNCTION_NOT_ALLOWED", name.lower())

    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    tables = [t for t in tree.find_all(exp.Table) if t.name.lower() not in ctes]
    if len(tables) > policy.max_tables:
        return Verdict.reject("TOO_MANY_TABLES", f"{len(tables)} > {policy.max_tables}")
    for t in tables:
        fqn = _fqn(t)
        if not t.name:  # table-valued function or other non-table source
            return Verdict.reject("TABLE_FUNCTION", t.sql(dialect=policy.dialect)[:60])
        if (t.db or "").lower() in SYSTEM_SCHEMAS:
            return Verdict.reject("SYSTEM_SCHEMA", fqn)
        if fqn not in scope.readable_tables:
            return Verdict.reject("UNKNOWN_OR_FORBIDDEN_TABLE", fqn)

    try:
        tree = qualify(tree, schema=scope.schema, dialect=policy.dialect,
                       validate_qualify_columns=True)
    except OptimizeError as e:
        return Verdict.reject("UNKNOWN_IDENTIFIER", str(e)[:200])

    limit = tree.args.get("limit")
    if limit is None:
        tree = tree.limit(policy.max_rows)
    else:
        lit = limit.expression if isinstance(limit, exp.Limit) else None
        if not isinstance(lit, exp.Literal) or not lit.is_int or int(lit.this) > policy.max_rows:
            tree = tree.limit(policy.max_rows)   # sqlglot replaces the existing LIMIT

    # comments=False: sqlglot preserves comments by default; strip them so nothing the
    # model wrote outside the AST reaches the database or the audit log.
    return Verdict(ok=True, sql=tree.sql(dialect=policy.dialect, comments=False))
