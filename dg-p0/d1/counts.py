"""Check D1 row counts: every table holds exactly the rows of its CSV (DG-00.02).
   D1_SRC=... D3_DSN="host=... port=..." python counts.py"""
import csv, os, pathlib, sys
import psycopg

csv.field_size_limit(sys.maxsize)
data = pathlib.Path(os.environ["D1_SRC"]) / "datasets/wideworldimporters/data"
bad = 0
with psycopg.connect(os.environ["D3_DSN"] + " dbname=d1 user=postgres") as c:
    for f in sorted(data.glob("*.csv")):
        with f.open(newline="") as h:
            want = sum(1 for _ in csv.reader(h)) - 1
        got = c.execute(f"SELECT count(*) FROM {f.stem.lower()}").fetchone()[0]
        bad += want != got
        print("PASS" if want == got else "FAIL", f.stem, want, got)
print(f"{bad} failure(s)")
sys.exit(bad > 0)
