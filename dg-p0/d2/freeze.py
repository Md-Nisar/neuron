"""Freeze D2's expected answers (DG-00.05): BIRD Mini-Dev, PostgreSQL edition.

Runs each of the 500 gold queries in mini_dev_postgresql.json as d2_reader on its database
(d2_<db_id>, loaded by load.sh) under the same 15 s limit the engines get, and writes
questions.jsonl in the D1 format: category answerable, one persona ("reader"), row order ignored.
BIRD's evidence is kept and given to every arm. A gold query that fails or times out is not
repaired: its question is left out and listed in excluded.json. D2 is indicative only (label
noise in BIRD; ADR 0016).
   BIRD_SRC=.../minidev D3_DSN="host=... port=..." python freeze.py"""
import json, os, pathlib
from decimal import Decimal
import psycopg

HERE = pathlib.Path(__file__).parent
src = pathlib.Path(os.environ["BIRD_SRC"]) / "MINIDEV/mini_dev_postgresql.json"
out, excluded = [], []
for n, e in enumerate(json.loads(src.read_text()), 1):  # BIRD repeats two question_ids: number by position
    with psycopg.connect(os.environ["D3_DSN"] + f" dbname=d2_{e['db_id']} user=d2_reader") as c:
        try:
            cur = c.execute(e["SQL"])
        except psycopg.Error as err:
            excluded.append({"id": f"B-{n:03d}", "question_id": e["question_id"], "db_id": e["db_id"], "question": e["question"],
                             "error": str(err).splitlines()[0]})
            continue
        cols = [d.name for d in cur.description]
        rows = [[float(v) if isinstance(v, Decimal) else v for v in r] for r in cur.fetchall()]
        rows = json.loads(json.dumps(rows, default=str))
    out.append({"id": f"B-{n:03d}", "bird_question_id": e["question_id"], "category": "answerable", "db": f"d2_{e['db_id']}",
                "question": e["question"], "evidence": e.get("evidence") or "", "difficulty": e["difficulty"],
                "reference_sql": e["SQL"], "order_matters": False,
                "expected": {"reader": {"columns": cols, "rows": rows}}})
(HERE / "excluded.json").write_text(json.dumps(excluded, indent=1) + "\n")
(HERE / "questions.jsonl").write_text("".join(json.dumps(q) + "\n" for q in out))
print(len(out), "questions;", len(excluded), "excluded;", sum(not q["expected"]["reader"]["rows"] for q in out),
      "with empty results;", sum(len(q["expected"]["reader"]["rows"]) > 1000 for q in out), "over 1000 rows")
