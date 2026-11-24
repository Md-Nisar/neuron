"""DG-00.05 A2 on D1 and D2: certify one database's compiled model from its Ossie model.

  AO_LOCAL_ENV=... AUTO_ONTOLOGY_ADMIN_EMAIL=... python certify_db.py http://127.0.0.1:3000 <database> \\
      <model.ossie.yaml> [<extra.yaml>] [--dry-run]

The same rules as the D3 certification (a2/certify.yaml), applied mechanically so that A2 has
exactly the knowledge arm B has, nothing tuned to the questions:
- a term whose one table is a dataset's `source` gets the dataset's description (when it has one)
  and is certified, name and description; a term for a table the model leaves out stays as
  generated and uncertified;
- a column attribute whose column is a field's plain-column expression gets the field's
  description (when it has one) and is certified; other column attributes stay uncertified;
- each dataset-scoped metric becomes a certified SQL attribute on its table's term, as
  "SELECT <expression with fields expanded> FROM <source>"; model-scoped metrics, which need joins,
  come from <extra.yaml> (`sql_attributes`, the a2/certify.yaml shape, keyed by table).
Terms and columns are found through an admin export scoped to the database, so equal table
names in other databases cannot collide. Writes a TSV of every decision beside the model output.
"""

import io
import json
import re
import sys
import urllib.error
import urllib.request

import service_account as sa
import yaml

args = [a for a in sys.argv[1:] if not a.startswith("--")]
db, model_path = args[1], args[2]
extra = yaml.safe_load(open(args[3])) if len(args) > 3 else {}
dry = "--dry-run" in sys.argv
env = dict(line.split("=", 1) for line in open(sa.ENV_FILE).read().split())
admin = sa.sign_in(sa.os.environ["AUTO_ONTOLOGY_ADMIN_EMAIL"], env["AUTO_ONTOLOGY_ADMIN_PASSWORD"])


def call(method: str, path: str, body=None):
    if dry and method != "GET" and path != "/api/model/export":
        return {"data": {"id": "dry", "valid": True}}
    try:
        return sa.call(admin, method, path, body)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} -> {e.code}: {e.read().decode()[:500]}") from None


def norm(name: str) -> str:
    return name.replace('"', "").strip().lower()


def export(scope: dict) -> dict:
    req = urllib.request.Request(
        sa.BASE + "/api/model/export",
        method="POST",
        data=json.dumps({"format": "auto_ontology", **scope}).encode(),
        headers={"Content-Type": "application/json", "Origin": sa.BASE},
    )
    with admin.open(req) as r:
        return yaml.safe_load(io.TextIOWrapper(r, encoding="utf-8"))


# The export filter takes catalog database ids, so look the name up in a full export first.
db_id = next(
    d["id"]
    for d in export({})["data_layer"]["databases"]
    if any(s.get("database_name") == db for s in d["schemas"])
)
doc = export({"databases": [db_id]})
tables, columns = {}, {}
for d in doc["data_layer"]["databases"]:
    for s in d["schemas"]:
        for t in s["tables"]:
            tables[t["id"]] = f"{s['name']}.{t['name']}".lower()
            for c in t["columns"]:
                columns[c["id"]] = (tables[t["id"]], c["name"].lower())

model = yaml.safe_load(open(model_path))
by_source = {norm(ds["source"]): ds for ds in model["datasets"]}
plain = {}  # (table, column) -> field
for ds in model["datasets"]:
    for f in ds.get("fields", []):
        col = norm(f["expression"]["sql"])
        if re.fullmatch(r"[a-z_][a-z0-9_ ()%/\-]*", col) and not re.search(r"[*+<>=]", col):
            plain[(norm(ds["source"]), col)] = f

log, done = (
    [],
    {
        "terms_certified": 0,
        "terms_left": 0,
        "columns_certified": 0,
        "columns_left": 0,
        "sql_attributes": 0,
        "invalid": [],
    },
)
term_by_table = {}
for term in doc["semantic_layer"]["terms"]:
    tabs = [tables[i] for i in term.get("represents", []) if i in tables]
    ds = by_source.get(tabs[0]) if len(tabs) == 1 else None
    if ds is None:
        done["terms_left"] += 1
        log.append(("term", term["name"], ",".join(tabs), "left", ""))
    else:
        term_by_table[tabs[0]] = term
        body = {"name_certified": True, "description_certified": True}
        if ds.get("description"):
            body["description"] = ds["description"]
        call("PATCH", f"/api/terms/{term['id']}", body)
        done["terms_certified"] += 1
        log.append(
            (
                "term",
                term["name"],
                tabs[0],
                "certified",
                body.get("description", "(generated kept)"),
            )
        )
    for ca in term.get("columns_attributes", []):
        f = plain.get(columns.get(ca["column_id"], ("", "")))
        if ds is None or f is None:
            done["columns_left"] += 1
            log.append(
                (
                    "column",
                    term["name"],
                    ".".join(columns.get(ca["column_id"], ("?", "?"))),
                    "left",
                    "",
                )
            )
            continue
        patch = {"certified": True}
        if f.get("description"):
            patch["description"] = f["description"]
        call("PATCH", f"/api/terms/{term['id']}/column-attributes/{ca['id']}", patch)
        done["columns_certified"] += 1
        log.append(
            (
                "column",
                term["name"],
                ".".join(columns[ca["column_id"]]),
                "certified",
                patch.get("description", "(generated kept)"),
            )
        )


def expand(expr: str, ds: dict) -> str:
    fields = {f["name"]: f["expression"]["sql"] for f in ds.get("fields", [])}
    return re.sub(
        r"\b[a-z_][a-z0-9_]*\b",
        lambda m: f"({fields[m.group(0)]})" if m.group(0) in fields else m.group(0),
        expr,
    )


attrs = [
    {
        "table": norm(ds["source"]),
        "name": m["name"].replace("_", " ").title(),
        "description": m.get("description") or m["name"].replace("_", " ").capitalize() + ".",
        "expression": f"SELECT {expand(m['expression']['sql'], ds)} FROM {ds['source']}",
    }
    for ds in model["datasets"]
    for m in ds.get("metrics", []) or []
]
attrs += extra.get("sql_attributes", [])
existing = {}
for t in term_by_table.values():
    for a in call("GET", f"/api/terms/{t['id']}/sql-attributes")["data"] or []:
        existing[(t["id"], a["name"])] = a
for a in attrs:
    term = term_by_table.get(a["table"])
    if term is None:
        done["invalid"].append({a["name"]: f"no certified term for {a['table']}"})
        continue
    # SQL attribute names are unique across every database in Auto Ontology: on a clash with
    # another database's attribute, the name carries this database's name.
    cur = existing.get((term["id"], a["name"])) or existing.get((term["id"], f"{a['name']} ({db})"))
    if cur:
        a = {**a, "name": cur["name"]}
    check = {
        "expression": a["expression"],
        "term_id": term["id"],
        **({"attribute_id": cur["id"]} if cur else {}),
    }
    v = call("POST", "/api/sql-attributes/validate", check)["data"]
    if not v.get("valid", True):
        done["invalid"].append({a["name"]: v})
        continue
    body = {
        "name": a["name"],
        "description": a["description"],
        "expression": a["expression"],
        "term_id": term["id"],
        "source": "manual",
    }
    if cur:
        attr = call("PUT", f"/api/sql-attributes/{cur['id']}", body)["data"]
    elif dry:
        attr = {"id": "dry"}
    else:
        try:
            attr = sa.call(admin, "POST", "/api/sql-attributes", body)["data"]
        except urllib.error.HTTPError as e:
            if e.code != 409:
                raise SystemExit(
                    f"POST /api/sql-attributes -> {e.code}: {e.read().decode()[:300]}"
                ) from None
            body["name"] = a["name"] = f"{a['name']} ({db})"
            attr = call("POST", "/api/sql-attributes", body)["data"]
    call("PATCH", f"/api/sql-attributes/{attr['id']}", {"certified": True})
    done["sql_attributes"] += 1
    log.append(("sql_attribute", term["name"], a["table"], "certified", a["expression"]))

out = re.sub(r"\.ossie\.yaml$", "", model_path.rsplit("/", 1)[-1])
with open(f"a2/{out}.certified.tsv", "w") as fh:
    fh.write("kind\tterm\tobject\toutcome\tdescription_or_sql\n")
    fh.writelines(
        "\t".join(str(x).replace("\t", " ").replace("\n", " ") for x in row) + "\n" for row in log
    )
print(json.dumps(done, indent=1))
