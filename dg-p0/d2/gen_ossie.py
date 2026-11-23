"""Generate D2's Ossie models (DG-00.05) from BIRD's own documentation, for arms B and A2.

D2 has no hand-written model (DG-00.02 wrote D1 and D3 only). Each of the 11 BIRD Mini-Dev
databases gets one model built mechanically, with no judgement and without reading the
questions: a dataset per table, a field per column with BIRD's column and value descriptions
(database_description/*.csv), primary keys and relationships from dev_tables.json. No metrics:
BIRD defines none. Columns are matched to the loaded PostgreSQL columns by lower-cased name.
   BIRD_SRC=.../minidev D3_DSN="host=... port=..." python gen_ossie.py   -> ossie/d2_<db>.ossie.yaml"""
import csv, json, os, pathlib, re
import psycopg, yaml

HERE = pathlib.Path(__file__).parent
SRC = pathlib.Path(os.environ["BIRD_SRC"]) / "MINIDEV"
TYPES = {"integer": "Integer", "bigint": "Integer", "smallint": "Integer", "real": "Float",
         "double precision": "Float", "numeric": "Decimal", "text": "String", "character varying": "String",
         "date": "Date", "timestamp without time zone": "DateTime", "timestamp with time zone": "DateTimeTz",
         "boolean": "Boolean", "time without time zone": "Time"}


RESERVED = set("all and any as asc between by case check column cross default desc distinct end except fetch "
               "foreign from full group having in inner intersect into is join left like limit natural not "
               "null offset on only or order outer primary references right select table to union user "
               "when where window".split())


def ident(name: str) -> str:
    return name if re.fullmatch(r"[a-z_][a-z0-9_]*", name) and name not in RESERVED else '"' + name.replace('"', '""') + '"'


def fname(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.lower())).strip("_") or "field"


def clean(s: str | None) -> str:
    return " ".join((s or "").replace("﻿", "").split())


def describe(db_dir: pathlib.Path, table: str) -> dict:
    for p in (db_dir / "database_description").glob("*.csv"):
        if p.stem.lower() == table.lower():
            for enc in ("utf-8-sig", "latin-1"):
                try:
                    rows = list(csv.DictReader(p.open(encoding=enc)))
                    break
                except UnicodeDecodeError:
                    continue
            out = {}
            for r in rows:
                col = clean(r.get("original_column_name")).lower()
                text = clean(r.get("column_description")) or clean(r.get("column_name"))
                val = clean(r.get("value_description"))
                out[col] = (text + (f". Values: {val}" if val else "")).strip()
            return out
    return {}


(HERE / "ossie").mkdir(exist_ok=True)
for db in json.loads((SRC / "dev_tables.json").read_text()):
    name = db["db_id"]
    tables = [t.lower() for t in db["table_names_original"]]
    cols = db["column_names_original"]
    with psycopg.connect(os.environ["D3_DSN"] + f" dbname=d2_{name} user=postgres") as c:
        phys = {}
        for t, col, typ in c.execute("SELECT table_name, column_name, data_type FROM information_schema.columns "
                                     "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"):
            phys.setdefault(t, []).append((col, typ))
    fmap = {}  # (table index, lower column) -> field name
    datasets = []
    for ti, t in enumerate(tables):
        desc = describe(SRC / "dev_databases" / name, db["table_names_original"][ti])
        fields, used = [], set()
        for col, typ in phys[t]:
            f = fname(col)
            while f in used:
                f += "_"
            used.add(f)
            fmap[(ti, col.lower())] = f
            fd = {"name": f, "expression": {"sql": ident(col)}}
            if TYPES.get(typ):
                fd["datatype"] = TYPES[typ]
            if desc.get(col.lower().strip()):
                fd["description"] = desc[col.lower().strip()]
            fields.append(fd)
        ds = {"name": t, "source": f"public.{ident(t)}", "description": f"{db['table_names'][ti]}.", "fields": fields}
        pk = [p for p in db["primary_keys"] for p in (p if isinstance(p, list) else [p]) if cols[p][0] == ti]
        if pk:
            ds["primary_key"] = [fmap[(ti, cols[p][1].lower())] for p in pk]
        datasets.append(ds)
    rels, seen = [], set()
    for a, b in db["foreign_keys"]:
        (ta, ca), (tb, cb) = cols[a], cols[b]
        key = (tables[ta], tables[tb], ca.lower(), cb.lower())
        if key in seen or (ta, ca.lower()) not in fmap or (tb, cb.lower()) not in fmap:
            continue
        seen.add(key)
        rels.append({"name": f"{tables[ta]}_{fmap[(ta, ca.lower())]}_to_{tables[tb]}_{len(rels)}",
                     "from": tables[ta], "to": tables[tb],
                     "from_columns": [fmap[(ta, ca.lower())]], "to_columns": [fmap[(tb, cb.lower())]]})
    model = {"version": "0.3.0.dev0", "name": f"d2_{name}",
             "description": f"BIRD Mini-Dev database {name}, generated from BIRD's column descriptions.",
             "datasets": datasets, "relationships": rels}
    head = ("# Generated by d2/gen_ossie.py from BIRD Mini-Dev's database_description and dev_tables.json\n"
            "# (DG-00.05). Not hand-written; no metrics. Spec: Apache Ossie main at 91689e6.\n")
    (HERE / "ossie" / f"d2_{name}.ossie.yaml").write_text(head + yaml.safe_dump(model, sort_keys=False, width=110, allow_unicode=True))
    print(name, len(datasets), "datasets", sum(len(d["fields"]) for d in datasets), "fields", len(rels), "relationships",
          sum("description" in f for d in datasets for f in d["fields"]), "described")
