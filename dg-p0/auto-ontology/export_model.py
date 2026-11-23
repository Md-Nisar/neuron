"""DG-00.04: snapshot Auto Ontology's compiled model, as its own YAML and as Apache Ossie (zip of
semantic model, ontology and mapping). Export needs the admin role; the viewer token gets 403.

  AO_LOCAL_ENV=... AUTO_ONTOLOGY_ADMIN_EMAIL=... python export_model.py http://127.0.0.1:3000 <dir>
"""
import io
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


os.makedirs(out, exist_ok=True)
with open(os.path.join(out, "d3.auto_ontology.yaml"), "wb") as f:
    f.write(export(b'{"format": "auto_ontology"}'))
zipfile.ZipFile(io.BytesIO(export(b'{"format": "ossie", "include_ontology": true}'))).extractall(os.path.join(out, "ossie"))
print(sorted(os.listdir(out)), sorted(os.listdir(os.path.join(out, "ossie"))))
