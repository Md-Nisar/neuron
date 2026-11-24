"""DG-00.05: restore D3's A1 model (the DG-00.04 snapshot a1/d3.auto_ontology.yaml) before the A1 run.

  AO_LOCAL_ENV=... AUTO_ONTOLOGY_ADMIN_EMAIL=... python restore_a1.py http://127.0.0.1:3000

Imports the snapshot with replace=true (Auto Ontology replaces the semantic layer of the
databases in the document only), then makes sure nothing in D3 is certified: the native export
carries no certification flags, so flags set by A2 could survive an import. Prints what it did.
"""
import json
import os
import urllib.request

import service_account as sa

env = dict(line.split("=", 1) for line in open(os.environ["AO_LOCAL_ENV"]).read().split())
admin = sa.sign_in(os.environ["AUTO_ONTOLOGY_ADMIN_EMAIL"], env["AUTO_ONTOLOGY_ADMIN_PASSWORD"])
body = open("a1/d3.auto_ontology.yaml", "rb").read()
req = urllib.request.Request(sa.BASE + "/api/model/import?replace=true", method="POST", data=body,
                             headers={"Content-Type": "application/yaml", "Origin": sa.BASE})
with admin.open(req) as r:
    print("import:", json.dumps(json.load(r)["summary"])[:600])
d3_terms = []
skip = 0
while True:
    page = sa.call(admin, "GET", f"/api/terms?limit=100&skip={skip}")["terms"]
    d3_terms += [t for t in page if "d3" in json.dumps(t.get("tables") or t.get("database") or "") or True]
    if len(page) < 100:
        break
    skip += 100
unset = {"terms": 0, "columns": 0, "sql_attributes": 0}
a1_ids = {t["id"] for t in __import__("yaml").safe_load(body)["semantic_layer"]["terms"]}
for t in [t for t in d3_terms if t["id"] in a1_ids]:
    if t.get("name_certified") or t.get("description_certified"):
        sa.call(admin, "PATCH", f"/api/terms/{t['id']}", {"name_certified": False, "description_certified": False})
        unset["terms"] += 1
    for c in sa.call(admin, "GET", f"/api/terms/{t['id']}/column-attributes?limit=100")["data"]:
        if c.get("certified"):
            sa.call(admin, "PATCH", f"/api/terms/{t['id']}/column-attributes/{c['id']}", {"certified": False})
            unset["columns"] += 1
    for a in sa.call(admin, "GET", f"/api/terms/{t['id']}/sql-attributes")["data"] or []:
        unset["sql_attributes_left"] = unset.get("sql_attributes_left", 0) + 1
print("certification removed:", unset, "of", len(a1_ids), "A1 terms")

# An import with replace=true skips items that already exist (same ids), so it does not undo A2's
# descriptions. Put back each term's and column attribute's A1 description.
fixed = {"terms": 0, "columns": 0}
for t in __import__("yaml").safe_load(body)["semantic_layer"]["terms"]:
    live = sa.call(admin, "GET", f"/api/terms/{t['id']}")
    live = live.get("data", live)
    if (live.get("description") or "") != (t.get("description") or ""):
        sa.call(admin, "PATCH", f"/api/terms/{t['id']}", {"description": t.get("description") or ""})
        fixed["terms"] += 1
    want = {c["id"]: c.get("description") or "" for c in t.get("columns_attributes", [])}
    for c in sa.call(admin, "GET", f"/api/terms/{t['id']}/column-attributes?limit=100")["data"]:
        if c["id"] in want and (c.get("description") or "") != want[c["id"]]:
            sa.call(admin, "PATCH", f"/api/terms/{t['id']}/column-attributes/{c['id']}", {"description": want[c["id"]]})
            fixed["columns"] += 1
print("descriptions restored to A1:", fixed)
