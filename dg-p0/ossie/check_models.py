"""Check an Ossie model against its live database (DG-00.02).

Ossie validation checks the document only. This runs it: every field expression, every
dataset-scoped and model-scoped metric, and every relationship (no dangling keys) as one
query each, as the superuser so row-level security does not hide rows.
   D3_DSN="host=... port=..." python check_models.py <model.yaml> <dbname>"""
import sys, os
import psycopg, yaml

model, db = yaml.safe_load(open(sys.argv[1])), sys.argv[2]
ds = {d["name"]: d for d in model["datasets"]}
rels = model.get("relationships", [])


def cte(d):
    cols = ", ".join(f'({f["expression"]["sql"]}) AS "{f["name"]}"' for f in d.get("fields", []))
    return f'"{d["name"]}" AS (SELECT {cols} FROM {d["source"]})'


def with_(*names):
    return "WITH " + ", ".join(cte(ds[n]) for n in dict.fromkeys(names)) + " "


def join_clause(names):
    """FROM for a model metric: chain the datasets it names along direct relationships."""
    names, done = list(names), [names[0]]
    sql = f'"{names[0]}"'
    while len(done) < len(names):
        for r in rels:
            a, b = r["from"], r["to"]
            new = b if a in done and b in names and b not in done else a if b in done and a in names and a not in done else None
            if new:
                on = " AND ".join(f'"{a}"."{x}" = "{b}"."{y}"' for x, y in zip(r["from_columns"], r["to_columns"]))
                sql += f' JOIN "{new}" ON {on}'
                done.append(new)
                break
        else:
            raise SystemExit(f"no relationship path for {names}")
    return sql


checks, bad = [], 0
for d in ds.values():
    checks.append((f'dataset {d["name"]} (all fields)', with_(d["name"]) + f'SELECT count(*) FROM "{d["name"]}"', None))
    for m in d.get("metrics", []):
        checks.append((f'metric {d["name"]}.{m["name"]}', with_(d["name"]) + f'SELECT {m["expression"]["sql"]} FROM "{d["name"]}"', None))
for m in model.get("metrics", []):
    used = [n for n in ds if f"{n}." in m["expression"]["sql"]]
    checks.append((f'metric {m["name"]}', with_(*used) + f'SELECT {m["expression"]["sql"]} FROM {join_clause(used)}', None))
for r in rels:
    a, b = r["from"], r["to"]
    on = " AND ".join(f'f."{x}" = t."{y}"' for x, y in zip(r["from_columns"], r["to_columns"]))
    notnull = " AND ".join(f'f."{x}" IS NOT NULL' for x in r["from_columns"])
    checks.append((f'relationship {r["name"]} (no dangling keys)',
                   with_(a, b) + f'SELECT count(*) FROM "{a}" f LEFT JOIN "{b}" t ON {on} WHERE {notnull} AND t."{r["to_columns"][0]}" IS NULL', 0))
    checks.append((f'relationship {r["name"]} (target key unique)',
                   with_(b) + f'SELECT count(*) FROM (SELECT 1 FROM "{b}" GROUP BY {", ".join(chr(34)+c+chr(34) for c in r["to_columns"])} HAVING count(*) > 1) x', 0))

with psycopg.connect(os.environ["D3_DSN"] + f" dbname={db} user=postgres", autocommit=True) as c:
    for name, sql, want in checks:
        try:
            got = c.execute(sql).fetchone()[0]
            ok = want is None or got == want
            print("PASS" if ok else "FAIL", name, "" if ok else f"got {got}")
        except psycopg.Error as e:
            ok = False
            print("FAIL", name, str(e).splitlines()[0])
        bad += not ok
print(f"{sys.argv[1]}: {len(checks)} checks, {bad} failure(s)")
sys.exit(bad > 0)
