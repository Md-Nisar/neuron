"""D28, owner rule: a question about a named value outside the caller's regions is refused, not answered 0.

For every answerable question, each string literal the reference SQL compares with = or IN on a
text column of a table that has region_id is placed in its regions (as postgres, all rows). If
those regions exist and none is the persona's (d3/personas.json), the persona's expectation becomes
a refusal. This covers values row-level security hides (customers, staff, departments) and
reference values every persona can read but that belong to another region (countries, regions).
Tables without region_id (products, skills, cycles) are shared and never trigger the rule. The
refusal uses the scorer's existing no-access form ({"error": ...}), so the scorer is unchanged.
The old expectation is kept under "was". Only units whose old answer was empty or 0 change;
anything else is printed for review and left alone.

  python d3/scope_rule.py questions.jsonl fresh.jsonl          # report only
  python d3/scope_rule.py --write questions.jsonl fresh.jsonl  # rewrite the files in place
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

import psycopg
import sqlglot
from psycopg import sql as psql
from sqlglot import exp

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from check import PERSONAS  # noqa: E402

DSN = os.environ["D3_DSN"]
ERROR = "OutOfScopeValue"
TEXT = ("text", "character varying", "character")


def literals(sql: str) -> list[tuple[str, str, str]]:
    """(schema.table, column, value) for each column = 'text' or column IN ('text', ...)."""
    tree = sqlglot.parse_one(sql, read="postgres")
    alias = {}
    for t in tree.find_all(exp.Table):
        alias[t.alias_or_name] = f"{t.db}.{t.name}"
    tables = sorted(set(alias.values()))
    out = []
    for node in tree.find_all(exp.EQ, exp.In):
        col = node.this if isinstance(node.this, exp.Column) else node.expression
        if not isinstance(col, exp.Column):
            continue
        vals = node.expressions if isinstance(node, exp.In) else [node.expression]
        for v in vals:
            if isinstance(v, exp.Literal) and v.is_string:
                owners = [alias[col.table]] if col.table else tables
                out += [(t, col.name, v.this) for t in owners]
    return out


def is_text(admin: psycopg.Connection, table: str, column: str) -> bool:
    schema, name = table.split(".")
    row = admin.execute(
        "SELECT data_type FROM information_schema.columns WHERE table_schema = %s "
        "AND table_name = %s AND column_name = %s",
        (schema, name, column),
    ).fetchone()
    return bool(row) and row[0] in TEXT


def regions(admin: psycopg.Connection, table: str, column: str, value: str) -> set[str]:
    """The regions of the rows holding the value; empty when the table has no region_id."""
    schema, name = table.split(".")
    has = admin.execute(
        "SELECT 1 FROM information_schema.columns WHERE table_schema = %s AND table_name = %s "
        "AND column_name = 'region_id'",
        (schema, name),
    ).fetchone()
    if not has:
        return set()
    q = psql.SQL("SELECT DISTINCT region_id FROM {}.{} WHERE {} = %s").format(
        psql.Identifier(schema), psql.Identifier(name), psql.Identifier(column)
    )
    return {r[0] for r in admin.execute(q, (value,))}


def empty_or_zero(e: dict) -> bool:
    return all(
        c in (0, None) or (isinstance(c, (int, float)) and c == 0) for r in e["rows"] for c in r
    )


def apply(path: pathlib.Path, admin: psycopg.Connection, write: bool) -> list[str]:
    qs = [json.loads(line) for line in path.read_text().splitlines()]
    log = []
    for q in qs:
        if q["category"] != "answerable":
            continue
        lits = [x for x in literals(q["reference_sql"]) if is_text(admin, x[0], x[1])]
        for p in PERSONAS:
            e = q["expected"][p]
            if "error" in e:
                continue
            hidden = []
            for t, c, v in lits:
                where = regions(admin, t, c, v)
                if where and not where & set(PERSONAS[p]["regions"]):
                    hidden.append(f"{t}.{c} = '{v}' ({', '.join(sorted(where))})")
            if not hidden:
                continue
            if not empty_or_zero(e):
                log.append(
                    f"REVIEW {q['id']} {p}: hidden {hidden} but expected {e['rows'][:3]}; unchanged"
                )
                continue
            q["expected"][p] = {"error": ERROR, "hidden": hidden, "was": e}
            log.append(f"{q['id']} {p}: refuse ({'; '.join(hidden)})")
    if write:
        path.write_text("".join(json.dumps(q) + "\n" for q in qs))
    return log


if __name__ == "__main__":
    write = "--write" in sys.argv
    with psycopg.connect(f"{DSN} dbname=d3 user=postgres") as admin:
        for name in [a for a in sys.argv[1:] if not a.startswith("--")]:
            for line in apply(HERE / name, admin, write):
                print(f"{name}: {line}")
