"""Check the D3 mart against DG-00.01's acceptance criteria (hardening option A').

  D3_DSN="host=... port=..." python check.py

D3_DSN has no user or dbname; the checker connects to database d3 as the superuser (for ground
truth) and as each persona's login. Needs psycopg 3 and sqlglot 30.33.0 (for the comparator).
Exit code 0 only if every check passes. KNOWN lines are documented residual limits, not passes.

Checks:
  isolation   each persona sees exactly its regions' rows, none outside them, all reference rows,
              and no confidential table unless it is the manager
  fail-closed a login that has not switched into its data role reads nothing, and a data role
              with no region mapping sees no rows in any table
  escape      no SET, RESET ROLE, SET ROLE, write or file read widens what a session sees
  questions   every reference query in questions.jsonl returns its expected result per persona
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

import psycopg
from psycopg import sql as psql

HERE = pathlib.Path(__file__).parent
REF = HERE.parents[1] / "docs/research/data-analytics/reference-code/nl2data-ref"
sys.path.insert(0, str(REF))
from nl2data_ref.answer_checks import results_match  # noqa: E402

DSN = os.environ["D3_DSN"]
PERSONAS = json.loads((HERE / "personas.json").read_text())
# Listed by hand, not derived from the hardening SQL, so a mistake there cannot hide here.
REGIONAL = [
    "sales.customers",
    "sales.sales_reps",
    "sales.orders",
    "sales.order_lines",
    "sales.returns",
    "skills.departments",
    "skills.employees",
    "skills.assessments",
    "skills.certifications",
]
CONFIDENTIAL = ["sales.rep_compensation", "skills.assessor_notes"]  # regional, manager only
REFERENCE = [
    "sales.regions",
    "sales.countries",
    "sales.products",
    "skills.skills",
    "skills.assessment_cycles",
    "skills.role_targets",
]
failures: list[str] = []


def ok(cond: bool, label: str) -> None:
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


def connect(user: str) -> psycopg.Connection:
    return psycopg.connect(f"{DSN} dbname=d3 user={user}")


def readable(persona: dict) -> list[str]:
    extra = CONFIDENTIAL if persona["role"] == "d3_manager" else []
    return REGIONAL + extra + REFERENCE


def run_as(persona: dict, query: str) -> tuple[list[str], list[tuple]]:
    """The executor's order: read-only txn, SET LOCAL ROLE, timeout, one statement, rollback."""
    with connect(persona["login"]) as conn:
        cur = conn.cursor()
        cur.execute("BEGIN READ ONLY")
        cur.execute(psql.SQL("SET LOCAL ROLE {}").format(psql.Identifier(persona["role"])))
        cur.execute("SET LOCAL statement_timeout = '15s'")
        cur.execute(query)
        cols = [d.name for d in cur.description] if cur.description else []
        rows = cur.fetchall() if cur.description else []
        conn.rollback()
    return cols, rows


def fails(persona: dict, statements: list[str]) -> str | None:
    """Run statements in one transaction as the persona's login; return the error, if any."""
    with connect(persona["login"]) as conn:
        try:
            for s in statements:
                conn.execute(s)
        except psycopg.Error as e:
            return type(e).__name__
        finally:
            conn.rollback()
    return None


def foreign_rows(persona: dict, setup: list[str]) -> int:
    """After `setup` (run as the login), rows outside the persona's regions it can count."""
    with connect(persona["login"]) as conn:
        for s in setup:
            conn.execute(s)
        n = conn.execute(
            "SELECT count(*) FROM sales.orders WHERE NOT (region_id = ANY(%s))",
            (persona["regions"],),
        ).fetchone()[0]
        conn.rollback()
    return n


def check_isolation(admin: psycopg.Connection) -> None:
    for name, p in PERSONAS.items():
        for t in REGIONAL + CONFIDENTIAL:
            if t in CONFIDENTIAL and p["role"] != "d3_manager":
                err = fails(p, [f"SET ROLE {p['role']}", f"SELECT 1 FROM {t}"])
                ok(err == "InsufficientPrivilege", f"isolation {name}: {t} refused ({err})")
                continue
            want = admin.execute(
                f"SELECT count(*) FROM {t} WHERE region_id = ANY(%s)", (p["regions"],)
            ).fetchone()[0]
            _, got = run_as(p, f"SELECT count(*) FROM {t}")
            _, out = run_as(
                p,
                f"SELECT count(*) FROM {t} WHERE NOT (region_id = ANY("
                f"ARRAY{p['regions']!r}::text[]))",
            )
            ok(
                got[0][0] == want and want > 0 and out[0][0] == 0,
                f"isolation {name}: {t} sees {got[0][0]} of {want} own rows, {out[0][0]} outside",
            )
        for t in REFERENCE:
            want = admin.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            _, got = run_as(p, f"SELECT count(*) FROM {t}")
            ok(got[0][0] == want > 0, f"isolation {name}: {t} sees all {want} reference rows")


def check_fail_closed(admin: psycopg.Connection) -> None:
    for name, p in PERSONAS.items():
        for t in readable(p):
            err = fails(p, [f"SELECT 1 FROM {t}"])
            ok(err == "InsufficientPrivilege", f"fail-closed {name}: login alone reads {t} ({err})")
    for role in sorted({p["role"] for p in PERSONAS.values()}):
        persona = next(p for p in PERSONAS.values() if p["role"] == role)
        with admin.transaction(force_rollback=True):
            admin.execute("DELETE FROM app.role_regions WHERE role_name = %s", (role,))
            admin.execute(psql.SQL("SET LOCAL ROLE {}").format(psql.Identifier(role)))
            for t in readable(persona):
                n = admin.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                ok(n == 0, f"fail-closed {role} unmapped: {t} returns {n} rows")


def check_escape() -> None:
    emea, apac, mgr = PERSONAS["emea_analyst"], PERSONAS["apac_analyst"], PERSONAS["global_manager"]
    refused = [
        ("set_config", emea, ["SELECT set_config('app.regions', 'APAC', true)"]),
        ("emea analyst into apac role", emea, ["SET ROLE d3_analyst_apac"]),
        ("apac analyst into emea role", apac, ["SET ROLE d3_analyst_emea"]),
        ("analyst into manager role", emea, ["SET ROLE d3_manager"]),
        ("manager into analyst role", mgr, ["SET ROLE d3_analyst_emea"]),
        (
            "RESET ROLE then read",
            emea,
            ["SET ROLE d3_analyst_emea", "RESET ROLE", "SELECT 1 FROM sales.orders"],
        ),
        ("write as login", emea, ["DELETE FROM sales.orders"]),
        (
            "write as data role (rw txn)",
            mgr,
            [
                "SET default_transaction_read_only = off",
                "BEGIN READ WRITE",
                "SET ROLE d3_manager",
                "UPDATE sales.orders SET status = 'cancelled'",
            ],
        ),
        (
            "rewrite role mapping (rw txn)",
            emea,
            [
                "SET default_transaction_read_only = off",
                "BEGIN READ WRITE",
                "SET ROLE d3_analyst_emea",
                "INSERT INTO app.role_regions VALUES ('d3_analyst_emea', 'APAC')",
            ],
        ),
        ("create table", mgr, ["SET ROLE d3_manager", "CREATE TABLE sales.x (i int)"]),
        ("read server file", mgr, ["SELECT pg_read_file('/etc/passwd')"]),
    ]
    for label, p, stmts in refused:
        err = fails(p, stmts)
        ok(err is not None, f"escape refused: {label} ({err})")
    # F1: a forged setting must not widen visibility.
    n = foreign_rows(
        emea,
        [
            "BEGIN READ ONLY",
            "SET LOCAL app.regions = 'EMEA,APAC,AMER'",
            "SET LOCAL ROLE d3_analyst_emea",
        ],
    )
    ok(n == 0, f"escape: SET app.regions does not widen ({n} foreign orders)")
    # F1b: leaving and re-entering the data role must not widen visibility.
    n = foreign_rows(
        emea,
        [
            "BEGIN READ ONLY",
            "SET LOCAL ROLE d3_analyst_emea",
            "RESET ROLE",
            "SET LOCAL app.regions = 'EMEA,APAC,AMER'",
            "SET LOCAL ROLE d3_analyst_emea",
        ],
    )
    ok(n == 0, f"escape: RESET ROLE and re-entry does not widen ({n} foreign orders)")
    # F1c: residual. The executor must set the timeout and run one statement; the database cannot.
    err = fails(emea, ["SET ROLE d3_analyst_emea", "SET statement_timeout = 0"])
    print(f"KNOWN escape: a session can lift statement_timeout ({err or 'allowed'}); see F1c")


def check_questions() -> None:
    path = HERE / "questions.jsonl"
    if not path.exists():
        print("SKIP questions: questions.jsonl not written yet")
        return
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        q = json.loads(line)
        if q["category"] != "answerable":
            continue
        for name, exp in q["expected"].items():
            p = PERSONAS[name]
            if exp.get("error"):
                err = fails(p, [f"SET ROLE {p['role']}", q["reference_sql"]])
                ok(err == exp["error"], f"question {q['id']} {name}: refused with {err}")
                continue
            cols, rows = run_as(p, q["reference_sql"])
            match, why = results_match(
                cols, rows, exp["columns"], exp["rows"], order_matters=q.get("order_matters", False)
            )
            ok(match, f"question {q['id']} {name}: {why}")


def main() -> int:
    with psycopg.connect(f"{DSN} dbname=d3 user=postgres") as admin:
        check_isolation(admin)
        check_fail_closed(admin)
    check_escape()
    check_questions()
    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
