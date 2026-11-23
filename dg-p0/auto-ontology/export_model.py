"""DG-00.04: snapshot Auto Ontology's compiled model, as its own YAML and as Apache Ossie (zip of
semantic model, ontology and mapping). Export needs the admin role; the viewer token gets 403.

  AO_LOCAL_ENV=... AUTO_ONTOLOGY_ADMIN_EMAIL=... python export_model.py http://127.0.0.1:3000 <dir> [<database>]

With a database name (DG-00.05, several databases connected) only that database is exported, to
<dir>/<database>.auto_ontology.yaml and <dir>/ossie/; without one, everything, as d3 (DG-00.04).
"""
import io
import json
import os
import sys
import urllib.request
import zipfile

import service_account as sa

out = sys.argv[2]
env = dict(line.split("=", 1) for line in open(os.environ["AO_LOCAL_ENV"]).read().split())
admin = sa.sign_in(os.environ["AUTO_ONTOLOGY_ADMIN_EMAIL"], env["AUTO_ONTOLOGY_ADMIN_PASSWORD"])


def export(body: bytes) -> bytes:
    req = urllib.request.Request(sa.BASE + "/api/model/export", method="POST", data=body,
                                 headers={"Content-Type": "application/json", "Origin": sa.BASE})
    with admin.open(req) as r:
        return r.read()


db = sys.argv[3] if len(sys.argv) > 3 else None
scope = {"databases": [db]} if db else {}
os.makedirs(out, exist_ok=True)
with open(os.path.join(out, f"{db or 'd3'}.auto_ontology.yaml"), "wb") as f:
    f.write(export(json.dumps({"format": "auto_ontology", **scope}).encode()))
zipfile.ZipFile(io.BytesIO(export(json.dumps({"format": "ossie", "include_ontology": True, **scope}).encode()))).extractall(os.path.join(out, "ossie"))
print(sorted(os.listdir(out)), sorted(os.listdir(os.path.join(out, "ossie"))))
