"""Convert Apache Ossie models between 0.3.0.dev0 (the pinned spec, 91689e6) and the 0.2.0.dev0
shape Auto Ontology 1.3.0 reads and writes (finding F10). DG-00.05.

  python convert_ossie.py to02 <in.yaml> <out.yaml> --database=d3
  python convert_ossie.py to03 <in.yaml> <out.yaml>

to02 (for Auto Ontology's importer): version 0.2.0.dev0; `nonportable_extensions` -> `custom_extensions`
with `data` as a JSON string; every expression {sql: X} -> {dialects: [{dialect: ANSI_SQL, expression: X}]}
(the importer requires dialects); dataset sources prefixed with the database (it requires
database.schema.table). Model and dataset metrics are carried as they are, in the same shape.
to03 (for the pinned validator): the reverse renames; `data` parsed to an object; expressions and
sources are left as written (dialects and three-part sources are valid 0.3).
Nothing else is changed: anything 0.3 has that 0.2 lacks is reported, not dropped silently.
"""

from __future__ import annotations

import json
import sys

import yaml


def walk(node, fn):
    if isinstance(node, dict):
        fn(node)
        for v in list(node.values()):
            walk(v, fn)
    elif isinstance(node, list):
        for v in node:
            walk(v, fn)


def to02(model: dict, database: str) -> dict:
    model = json.loads(json.dumps(model))
    model["version"] = "0.2.0.dev0"

    def fix(n: dict) -> None:
        if "nonportable_extensions" in n:
            n["custom_extensions"] = [
                {"vendor_name": e["vendor_name"], "data": json.dumps(e["data"])}
                for e in n.pop("nonportable_extensions")
            ]
        e = n.get("expression")
        if isinstance(e, dict) and "sql" in e:
            n["expression"] = {
                "dialects": [{"dialect": "ANSI_SQL", "expression": e["sql"]}]
                + [d for d in e.get("dialects", []) if d.get("dialect") != "ANSI_SQL"]
            }

    walk(model, fix)
    for ds in model.get("datasets", []):
        if ds["source"].count(".") == 1:
            ds["source"] = f"{database}.{ds['source']}"
    return model


def to03(model: dict) -> dict:
    model = json.loads(json.dumps(model))
    model["version"] = "0.3.0.dev0"

    def fix(n: dict) -> None:
        if "custom_extensions" in n:
            n["nonportable_extensions"] = [
                {
                    "vendor_name": e["vendor_name"],
                    "data": json.loads(e["data"]) if isinstance(e["data"], str) else e["data"],
                }
                for e in n.pop("custom_extensions")
            ]

    walk(model, fix)
    return model


if __name__ == "__main__":
    mode, src, dst = sys.argv[1:4]
    opts = dict(a.lstrip("-").split("=", 1) for a in sys.argv[4:])
    m = yaml.safe_load(open(src))
    out = to02(m, opts["database"]) if mode == "to02" else to03(m)
    with open(dst, "w") as f:
        yaml.safe_dump(out, f, sort_keys=False, width=110, allow_unicode=True)
