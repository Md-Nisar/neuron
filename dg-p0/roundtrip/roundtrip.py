"""DG-00.05 S4: does Ossie YAML round-trip between the hand-written model and Auto Ontology?

  AO_LOCAL_ENV=... AUTO_ONTOLOGY_ADMIN_EMAIL=... OSSIE_SRC=... \\
    python roundtrip.py http://127.0.0.1:3000 <out-dir>

Run last: each import replaces Auto Ontology's semantic layer for database d3.

1. hand -> AO -> hand. The two hand-written D3 models (dg-p0/ossie/d3_*.ossie.yaml, spec 0.3.0.dev0)
   are merged into one model (Auto Ontology imports one model per database and replaces that
   database's layer), converted to 0.2.0.dev0 (convert_ossie.to02), imported, exported as Ossie,
   converted back (to03) and validated with the pinned validator.
2. AO -> Ossie -> AO. The A2 export taken before step 1 (auto-ontology/a2/export/ossie) is converted
   to 0.3.0.dev0 and validated, converted back, imported, and exported again.
Every metric and every field (dimension) of the source is listed as kept (same name, same
expression after whitespace and case normalisation), changed (found, expression differs, or a
metric that came back only as a field), or lost. Certification is listed too: Ossie core has no
certified flag (D13), so the question is whether Auto Ontology's own flags survive.
"""

from __future__ import annotations

import io
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.request
import zipfile

import yaml

HERE = pathlib.Path(__file__).parent
DG = HERE.parent
sys.path.insert(0, str(DG / "auto-ontology"))
sys.argv = [sys.argv[0], *sys.argv[1:]]
import service_account as sa  # noqa: E402  (reads the base URL from argv[1])
from convert_ossie import to02, to03  # noqa: E402

OUT = pathlib.Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
env = dict(line.split("=", 1) for line in open(os.environ["AO_LOCAL_ENV"]).read().split())
admin = sa.sign_in(os.environ["AUTO_ONTOLOGY_ADMIN_EMAIL"], env["AUTO_ONTOLOGY_ADMIN_PASSWORD"])


def http(path: str, body: bytes, ctype: str) -> bytes:
    req = urllib.request.Request(
        sa.BASE + path, method="POST", data=body, headers={"Content-Type": ctype, "Origin": sa.BASE}
    )
    try:
        with admin.open(req) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{path} -> {e.code}: {e.read().decode()[:800]}") from None


def database_id(name: str) -> str:
    full = yaml.safe_load(http("/api/model/export", b'{"format": "auto_ontology"}', "application/json"))
    return next(d["id"] for d in full["data_layer"]["databases"]
                if any(s.get("database_name") == name for s in d["schemas"]))


def export_ossie(name: str = "d3") -> dict:
    z = http(
        "/api/model/export",
        json.dumps({"format": "ossie", "databases": [database_id(name)]}).encode(),
        "application/json",
    )
    try:
        return yaml.safe_load(zipfile.ZipFile(io.BytesIO(z)).read("semantic_model.yaml"))
    except zipfile.BadZipFile:
        return yaml.safe_load(z)


def import_model(model: dict) -> dict:
    return json.loads(
        http(
            "/api/model/import?replace=true",
            yaml.safe_dump(model, sort_keys=False).encode(),
            "application/yaml",
        )
    )


def certified_counts(name: str) -> dict:
    """Certification flags of one database's terms and SQL attributes, read through the API."""
    doc = yaml.safe_load(http("/api/model/export", json.dumps({"format": "auto_ontology", "databases": [database_id(name)]}).encode(), "application/json"))
    out = {"terms": 0, "terms_name_certified": 0, "sql_attributes": 0, "sql_attributes_certified": 0}
    for t in doc["semantic_layer"]["terms"]:
        live = sa.call(admin, "GET", f"/api/terms/{t['id']}")
        live = live.get("data", live)
        out["terms"] += 1
        out["terms_name_certified"] += bool(live.get("name_certified"))
        for a in sa.call(admin, "GET", f"/api/terms/{t['id']}/sql-attributes")["data"] or []:
            out["sql_attributes"] += 1
            out["sql_attributes_certified"] += bool(a.get("certified"))
    return out


def validate(path: pathlib.Path) -> str:
    src = os.environ["OSSIE_SRC"]
    r = subprocess.run(
        [
            sys.executable,
            "-I",
            f"{src}/validation/validate.py",
            "--schema",
            f"{src}/core-spec/ossie-schema.json",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    return (
        "passed"
        if r.returncode == 0
        else "failed: " + (r.stdout + r.stderr).strip().splitlines()[-1][:200]
    )


def norm(s: str) -> str:
    s = re.sub(r"\s+", " ", re.sub(r'"', "", str(s))).strip().lower()
    return re.sub(r"\s*([(),])\s*", r"\1", s)  # spacing around brackets and commas is not a change


def expr(item: dict) -> str:
    e = item.get("expression") or {}
    if "sql" in e:
        return norm(e["sql"])
    return norm((e.get("dialects") or [{}])[0].get("expression", ""))


def tbl(source: str) -> str:
    return ".".join(norm(source).split(".")[-2:])


def inventory(model: dict) -> dict:
    """{('field'|'metric', table or '(model)', name): expression}."""
    inv = {}
    for ds in model.get("datasets", []):
        t = tbl(ds["source"])
        for f in ds.get("fields", []):
            inv[("field", t, norm(f["name"]))] = expr(f)
        for m in ds.get("metrics", []) or []:
            inv[("metric", t, norm(m["name"]))] = expr(m)
    for m in model.get("metrics", []) or []:
        inv[("metric", "(model)", norm(m["name"]))] = expr(m)
    return inv


def compare(src: dict, back: dict) -> list[dict]:
    a, b = inventory(src), inventory(back)
    by_name = {}
    for (kind, t, n), e in b.items():
        by_name.setdefault(n.replace(" ", "_"), []).append((kind, t, e))
    rows = []
    for (kind, t, n), e in sorted(a.items()):
        if (kind, t, n) in b:
            outcome = "kept" if b[(kind, t, n)] == e else "changed: expression"
            got = b[(kind, t, n)]
        else:
            hits = by_name.get(n.replace(" ", "_"), [])
            if not hits:
                outcome, got = "lost", ""
            else:
                k2, t2, got = hits[0]
                outcome = f"changed: came back as {k2} on {t2}" + (
                    "" if got == e else ", expression differs"
                )
        rows.append(
            {"kind": kind, "table": t, "name": n, "outcome": outcome, "expression": e, "back": got}
        )
    return rows


def merged_hand_model() -> dict:
    parts = [
        yaml.safe_load((DG / "ossie" / f"{n}.ossie.yaml").read_text())
        for n in ("d3_sales", "d3_skills")
    ]
    m = {
        "version": "0.3.0.dev0",
        "name": "d3",
        "description": "D3 hand-written models (sales and skills), merged.",
        "datasets": [],
        "relationships": [],
        "metrics": [],
    }
    for p in parts:
        for k in ("datasets", "relationships", "metrics"):
            m[k] += p.get(k, []) or []
    # Both models carry the shared reference table sales.regions as dataset "regions"; keep one.
    seen, ds = {}, []
    for d in m["datasets"]:
        if d["name"] in seen:
            assert seen[d["name"]] == d["source"], d["name"]
            continue
        seen[d["name"]] = d["source"]
        ds.append(d)
    m["datasets"] = ds
    names = set()
    m["relationships"] = [r for r in m["relationships"] if not (r["name"] in names or names.add(r["name"]))]
    return m


def summary(rows: list[dict]) -> dict:
    out: dict = {}
    for r in rows:
        key = f"{r['kind']}s {r['outcome'].split(':')[0]}"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


report: dict = {}
# 2 first needs the A2 export as it was; it is on disk (DG-00.04 snapshot).
a2 = yaml.safe_load((DG / "auto-ontology/a2/export/ossie/semantic_model.yaml").read_text())
(OUT / "a2_as_0.3.yaml").write_text(yaml.safe_dump(to03(a2), sort_keys=False))
report["ao_export_validates_as_exported"] = validate(
    DG / "auto-ontology/a2/export/ossie/semantic_model.yaml"
)
report["ao_export_validates_after_to03"] = validate(OUT / "a2_as_0.3.yaml")

# 1. hand -> AO -> hand
hand = merged_hand_model()
(OUT / "hand_merged.yaml").write_text(yaml.safe_dump(hand, sort_keys=False))
report["hand_validates"] = validate(OUT / "hand_merged.yaml")
# Importing it as database "d3" fails: Auto Ontology tries to create a second catalog database
# named d3 (500, unique constraint uq_catalog_database_name). It goes in as "d3_hand" instead,
# which leaves the live d3 layer alone and tests the format round trip itself.
report["hand_import_as_d3"] = "500: duplicate key uq_catalog_database_name (recorded, not retried)"
# A second relationship between the same two tables (assessments -> employees as employee and as
# assessor) makes the importer fail (500, ON CONFLICT ... cannot affect row a second time), so
# the import copy keeps the first relationship per table pair; the rest are reported as lost.
src = {d["name"]: d["source"] for d in hand["datasets"]}
pairs, importable, dropped = set(), [], []
for r in hand["relationships"]:
    key = tuple(sorted((src[r["from"]], src[r["to"]])))
    (dropped if key in pairs else importable).append(r)
    pairs.add(key)
report["relationships_not_importable"] = [r["name"] for r in dropped]
report["hand_import"] = import_model(to02({**hand, "relationships": importable}, "d3_hand"))
back = to03(export_ossie("d3_hand"))
(OUT / "hand_back.yaml").write_text(yaml.safe_dump(back, sort_keys=False))
report["hand_back_validates"] = validate(OUT / "hand_back.yaml")
report["hand_certified_after_import"] = certified_counts("d3_hand")
rows1 = compare(hand, back)

# 2. AO -> Ossie -> AO
report["a2_import"] = import_model(to02(to03(a2), "d3"))
again = to03(export_ossie())
(OUT / "a2_back.yaml").write_text(yaml.safe_dump(again, sort_keys=False))
report["a2_back_validates"] = validate(OUT / "a2_back.yaml")
report["a2_certified_after_import"] = certified_counts("d3")
rows2 = compare(to03(a2), again)

report["hand_roundtrip"] = summary(rows1)
report["ao_roundtrip"] = summary(rows2)
(OUT / "report.json").write_text(
    json.dumps({"report": report, "hand": rows1, "ao": rows2}, indent=1, default=str) + "\n"
)
md = [
    "# DG-00.05 Ossie round trip",
    "",
    "```json",
    json.dumps(report, indent=1, default=str),
    "```",
    "",
]
for title, rows in (
    ("Hand-written D3 model -> Auto Ontology -> Ossie", rows1),
    ("Auto Ontology A2 -> Ossie 0.3 -> Auto Ontology -> Ossie", rows2),
):
    md += [
        f"## {title}",
        "",
        "| Kind | Table | Name | Outcome | Source expression | Came back as |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    md += [
        f"| {r['kind']} | {r['table']} | {r['name']} | {r['outcome']} | `{r['expression'][:80]}` | `{r['back'][:80]}` |"
        for r in rows
    ]
    md.append("")
(OUT / "report.md").write_text("\n".join(md))
print(json.dumps(report, indent=1, default=str))
