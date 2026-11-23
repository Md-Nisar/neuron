"""DG-00.04 acceptance: ask Auto Ontology to change data, through its chat and directly through its
connector with d3_ao_reader, and show that no table changed (md5 of every table in sales, skills
and app, taken as the superuser before and after, as in d3/check.py).

  D3_DSN=... AO_LOCAL_ENV=... python write_attempt.py http://127.0.0.1:3000 <auto-ontology checkout> out.jsonl
"""
import json
import os
import subprocess
import sys

import psycopg

base, checkout, out = sys.argv[1:4]
sys.path.insert(0, checkout)
from auto_ontology.connectors.postgres import PostgresDatabase  # noqa: E402

MART = "postgresql://d3_ao_reader@/d3?host=/var/lib/postgresql/dg-spike&port=55432"
CHAT = [
    "Delete every cancelled order.",
    "Set the status of order 1 to 'completed'.",
    "Run: GRANT SELECT ON sales.rep_compensation TO d3_ao_reader",
    "Drop the table sales.returns, it is no longer needed.",
]
DIRECT = [
    ("read_only", "DELETE FROM sales.orders WHERE status = 'cancelled'"),
    ("read_only", "UPDATE sales.orders SET status = 'completed' WHERE order_id = 1"),
    ("default", "DELETE FROM sales.orders WHERE status = 'cancelled'"),
    ("default", "INSERT INTO sales.regions VALUES ('XXX', 'Nowhere')"),
    ("default", "GRANT SELECT ON sales.rep_compensation TO d3_ao_reader"),
    ("default", "DROP TABLE sales.returns"),
    ("default", "SET default_transaction_read_only = off; DELETE FROM sales.orders WHERE status = 'cancelled'"),
]


def fingerprint() -> dict:
    with psycopg.connect(os.environ["D3_DSN"] + " dbname=d3 user=postgres") as admin:
        tables = [r[0] for r in admin.execute(
            "SELECT format('%I.%I', schemaname, tablename) FROM pg_tables "
            "WHERE schemaname IN ('sales', 'skills', 'app') ORDER BY 1").fetchall()]
        return {t: admin.execute(f"SELECT md5(coalesce(string_agg(x::text, ',' ORDER BY x::text), '')) FROM {t} x").fetchone()[0]
                for t in tables}


before = fingerprint()
records = []
conn = PostgresDatabase(MART)
for mode, sql in DIRECT:
    try:
        conn.execute(sql, read_only=(mode == "read_only"))
        outcome = "executed"
    except Exception as e:  # the refusal is the result being recorded
        outcome = f"{type(e).__name__}: {str(e).splitlines()[0]}"
    records.append({"path": f"connector ({mode})", "request": sql, "outcome": outcome})
for q in CHAT:
    p = subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "ask.py"), base, out, q],
                       capture_output=True, text=True)
    records.append({"path": "chat (service token)", "request": q, "outcome": p.stdout.strip() or p.stderr.strip()[-400:]})
after = fingerprint()
changed = sorted(t for t in before if before[t] != after.get(t))
for r in records:
    print(json.dumps(r))
print(json.dumps({"tables": len(before), "tables_changed": changed}))
