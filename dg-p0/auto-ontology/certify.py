"""DG-00.04 A2: apply a2/certify.yaml to Auto Ontology as the admin, idempotently.

  AO_LOCAL_ENV=... AUTO_ONTOLOGY_ADMIN_EMAIL=... python certify.py http://127.0.0.1:3000 a2/certify.yaml
  ... python certify.py http://127.0.0.1:3000 a2/certify.yaml --columns-report a2/columns.tsv

With --columns-report it only writes every column attribute (term, table, column, description,
certified) for review; column attributes listed as approved in the spec's `columns` key are
certified on a normal run.
"""
import json
import os
import sys
import urllib.error
import urllib.request

import yaml

import service_account as sa

spec = yaml.safe_load(open(sys.argv[2]))
env = dict(line.split("=", 1) for line in open(os.environ["AO_LOCAL_ENV"]).read().split())
admin = sa.sign_in(os.environ["AUTO_ONTOLOGY_ADMIN_EMAIL"], env["AUTO_ONTOLOGY_ADMIN_PASSWORD"])


def call(method: str, path: str, body=None):
    try:
        return sa.call(admin, method, path, body)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path} -> {e.code}: {e.read().decode()[:500]}") from None


terms = {t["name"]: t for t in call("GET", "/api/terms?limit=100")["terms"]}
columns = []
for name, t in sorted(terms.items()):
    for c in call("GET", f"/api/terms/{t['id']}/column-attributes?limit=100")["data"]:
        columns.append((name, c))

if "--columns-report" in sys.argv:
    with open(sys.argv[sys.argv.index("--columns-report") + 1], "w") as f:
        f.write("term\ttable\tcolumn\tcertified\tdescription\n")
        for name, c in columns:
            f.write(f"{name}\t{c['primary_column']['table_name']}\t{c['source_column']}\t{c['certified']}\t{c['description']}\n")
    print(len(columns), "column attributes written")
    sys.exit(0)

done = {"terms_certified": 0, "terms_described_only": 0, "sql_attributes": 0, "columns_certified": 0, "invalid": []}
for name, s in spec["terms"].items():
    certify = s.get("certify", True)
    call("PATCH", f"/api/terms/{terms[name]['id']}",
         {"description": s["description"], "name_certified": certify, "description_certified": certify})
    done["terms_certified" if certify else "terms_described_only"] += 1

existing = {}
for name, t in terms.items():
    for a in call("GET", f"/api/terms/{t['id']}/sql-attributes")["data"]:
        existing[(name, a["name"])] = a
for a in spec["sql_attributes"]:
    cur = existing.get((a["term"], a["name"]))
    check = {"expression": a["expression"], "term_id": terms[a["term"]]["id"]}
    if cur:
        check["attribute_id"] = cur["id"]
    v = call("POST", "/api/sql-attributes/validate", check)["data"]
    if not v.get("valid", True):
        done["invalid"].append({a["name"]: v})
        continue
    body = {"name": a["name"], "description": a["description"], "expression": a["expression"],
            "term_id": terms[a["term"]]["id"], "source": "manual"}
    attr = (call("PUT", f"/api/sql-attributes/{cur['id']}", body) if cur else call("POST", "/api/sql-attributes", body))["data"]
    call("PATCH", f"/api/sql-attributes/{attr['id']}", {"certified": True})
    done["sql_attributes"] += 1

approved = {(c["table"], c["column"]): c.get("description") for c in spec.get("columns", [])}
for name, c in columns:
    key = (c["primary_column"]["table_name"], c["source_column"])
    if key in approved:
        patch = {"certified": True}
        if approved[key]:
            patch["description"] = approved[key]
        call("PATCH", f"/api/terms/{terms[name]['id']}/column-attributes/{c['id']}", patch)
        done["columns_certified"] += 1
print(json.dumps(done, indent=1))
