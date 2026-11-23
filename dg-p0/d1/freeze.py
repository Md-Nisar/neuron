"""Freeze D1's expected answers (DG-00.03).

Runs each of the 41 reference queries in NVIDIA auto-ontology-eval's evaluation.json as d1_reader
and writes questions.jsonl in the D3 format: category answerable, one persona ("reader"), row
order ignored (the comparator checks row order only when order_matters is set). A reference query
that fails on Postgres is not repaired: its question is left out and listed in excluded.json.
   D1_SRC=... D3_DSN="host=... port=..." python freeze.py"""
import json, os, pathlib
from decimal import Decimal
import psycopg

HERE = pathlib.Path(__file__).parent
src = pathlib.Path(os.environ["D1_SRC"]) / "datasets/wideworldimporters/evaluation.json"
out, excluded = [], []
with psycopg.connect(os.environ["D3_DSN"] + " dbname=d1 user=d1_reader") as c:
    for e in json.loads(src.read_text()):
        try:
            cur = c.execute(e["SQL"])
        except psycopg.Error as err:
            c.rollback()
            excluded.append({"question_id": e["question_id"], "question": e["question"],
                             "error": str(err).splitlines()[0]})
            continue
        cols = [d.name for d in cur.description]
        rows = [[float(v) if isinstance(v, Decimal) else v for v in r] for r in cur.fetchall()]
        rows = json.loads(json.dumps(rows, default=str))
        out.append({"id": f"W-A-{e['question_id']:03d}", "category": "answerable", "question": e["question"],
                    "evidence": e.get("evidence") or "", "reference_sql": e["SQL"], "order_matters": False,
                    "expected": {"reader": {"columns": cols, "rows": rows}}})
        c.rollback()
(HERE / "excluded.json").write_text(json.dumps(excluded, indent=1) + "\n")
(HERE / "questions.jsonl").write_text("".join(json.dumps(q) + "\n" for q in out))
print(len(out), "questions;", len(excluded), "excluded;", sum(len(q["expected"]["reader"]["rows"]) == 0 for q in out), "with empty results;",
      max(len(q["expected"]["reader"]["rows"]) for q in out), "max rows")
