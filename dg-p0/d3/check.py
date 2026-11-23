"""Check the D3 mart against DG-00.01's acceptance criteria.

  D3_DSN="host=... port=..." python check.py

D3_DSN has no user or dbname; the checker connects to database d3 as the superuser (for ground
truth) and as each persona's login. Needs psycopg 3. Exit code 0 only if every check passes.

Checks:
  isolation  each persona sees exactly the rows of its claimed regions, none outside them, and
             an analyst cannot read compensation at all
  fail-closed with no claims set, every table returns no rows for every login
  escape     a login cannot set claims through set_config, switch into the other data role, or
             re-set claims after switching into its data role; nothing can write
  questions  every reference query in questions.jsonl returns its expected result per persona
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
REGIONAL = ["customers", "sales_reps", "orders", "order_lines", "returns", "rep_compensation"]
REFERENCE = ["regions", "countries", "products"]
failures: list[str] = []


def ok(cond: bool, label: str) -> None:
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


def connect(user: str) -> psycopg.Connection:
    return psycopg.connect(f"{DSN} dbname=d3 user={user}")


def run_as(persona: dict, query: str, claims: bool = True) -> tuple[list[str], list[tuple]]:
    """The executor's order: read-only txn, claims, SET LOCAL ROLE, one statement, rollback."""
    with connect(persona["login"]) as conn:
        cur = conn.cursor()
        cur.execute("BEGIN READ ONLY")
        if claims:
            cur.execute("SELECT app.set_claims(%s, %s)", (persona["user"], persona["regions"]))
        cur.execute(psql.SQL("SET LOCAL ROLE {}").format(psql.Identifier(persona["role"])))
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


def check_isolation(admin: psycopg.Connection) -> None:
    for name, p in PERSONAS.items():
        for t in REGIONAL:
            if t == "rep_compensation" and p["role"] != "d3_manager":
                err = fails(p, [f"SET ROLE {p['role']}", f"SELECT 1 FROM sales.{t}"])
                ok(err == "InsufficientPrivilege", f"isolation {name}: {t} refused ({err})")
                continue
            want = admin.execute(
                f"SELECT count(*) FROM sales.{t} WHERE region_id = ANY(%s)", (p["regions"],)
            ).fetchone()[0]
            _, got = run_as(p, f"SELECT count(*) FROM sales.{t}")
            _, outside = run_as(
                p, f"SELECT count(*) FROM sales.{t} WHERE NOT (region_id = ANY(app.regions()))"
            )
            ok(got[0][0] == want and want > 0 and outside[0][0] == 0,
               f"isolation {name}: {t} sees {got[0][0]} of {want} own rows, {outside[0][0]} outside")
        for t in REFERENCE:
            want = admin.execute(f"SELECT count(*) FROM sales.{t}").fetchone()[0]
            _, got = run_as(p, f"SELECT count(*) FROM sales.{t}")
            ok(got[0][0] == want, f"isolation {name}: {t} sees all {want} reference rows")


def check_fail_closed() -> None:
    for name, p in PERSONAS.items():
        for t in REGIONAL + REFERENCE:
            if t == "rep_compensation" and p["role"] != "d3_manager":
                continue
            _, got = run_as(p, f"SELECT count(*) FROM sales.{t}", claims=False)
            ok(got[0][0] == 0, f"fail-closed {name}: {t} returns {got[0][0]} rows without claims")


def check_escape() -> None:
    analyst, manager = PERSONAS["emea_analyst"], PERSONAS["global_manager"]
    claims = "SELECT app.set_claims('x', ARRAY['EMEA','APAC','AMER'])"
    cases = [
        ("set_config directly", analyst, ["SELECT set_config('app.regions', 'APAC', true)"]),
        ("analyst into manager role", analyst, ["SET ROLE d3_manager"]),
        ("manager into analyst role", manager, ["SET ROLE d3_analyst"]),
        ("re-set claims as data role", analyst, ["SET ROLE d3_analyst", claims]),
        ("write as login", analyst, ["DELETE FROM sales.orders"]),
        ("write as data role (rw txn)", manager,
         ["SET default_transaction_read_only = off", "BEGIN READ WRITE", "SET ROLE d3_manager",
          "UPDATE sales.orders SET status = 'cancelled'"]),
        ("create table", manager, ["SET ROLE d3_manager", "CREATE TABLE sales.x (i int)"]),
        ("read server file", manager, ["SELECT pg_read_file('/etc/passwd')"]),
    ]
    for label, p, stmts in cases:
        err = fails(p, stmts)
        ok(err is not None, f"escape refused: {label} ({err})")
    # Revoking set_config does not stop the SET command: any role may write a custom `app.*`
    # setting. With the guard bypassed, a second statement can rewrite the claims. Must not widen.
    with connect(analyst["login"]) as conn:
        conn.execute("BEGIN READ ONLY")
        conn.execute("SELECT app.set_claims(%s, %s)", (analyst["user"], analyst["regions"]))
        conn.execute("SET LOCAL ROLE d3_analyst")
        conn.execute("SET LOCAL app.regions = 'EMEA,APAC,AMER'")
        seen = conn.execute("SELECT count(*) FROM sales.orders WHERE region_id <> 'EMEA'").fetchone()
        conn.rollback()
    ok(seen[0] == 0, f"escape: SET app.regions as data role does not widen ({seen[0]} foreign orders)")


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
            match, why = results_match(cols, rows, exp["columns"], exp["rows"],
                                       order_matters=q.get("order_matters", False))
            ok(match, f"question {q['id']} {name}: {why}")


def main() -> int:
    with psycopg.connect(f"{DSN} dbname=d3 user=postgres") as admin:
        check_isolation(admin)
    check_fail_closed()
    check_escape()
    check_questions()
    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
