# Ossie models (DG-00.02)

Spike code on `spike/data-gateway-p0`; never merged to `main`. Results go to
`docs/releases/data-gateway-p0/`.

| File | Purpose |
| --- | --- |
| `d3_sales.ossie.yaml` | D3 sales schema: 8 datasets, 10 relationships, 7 metrics. Leaves out `sales.rep_compensation` (confidential) |
| `d3_skills.ossie.yaml` | D3 skills schema: 8 datasets, 10 relationships, 5 metrics. Leaves out `skills.assessor_notes` (confidential). Carries its own `regions`, since Ossie has no cross-model references |
| `d1_wwi.ossie.yaml` | D1 Wide World Importers: 28 datasets, 52 relationships, 15 metrics. Leaves out history tables, sensors, system parameters, the website views, and credential and bank columns |
| `validate.sh` | One command: the pinned Ossie validator on all three, a negative control that must fail, then `check_models.py` on each |
| `check_models.py` | Runs every field, metric and relationship against the live database (relationships: no dangling keys, unique target key) |
| `../d1/load.sh` | Loads D1 as database `d1` from NVIDIA `auto-ontology-eval` at `e727e4d` (MIT; data from Microsoft's sql-server-samples) |
| `../d1/counts.py` | Checks every D1 table holds exactly its CSV's rows (48 tables) |

**Pinned spec:** Apache Ossie `main` at `91689e6` (spec `0.3.0.dev0`). The only tag, `osi-0.1.1-rc1`,
uses an older shape (D13).

**Certified terms:** Ossie core has no "certified" flag. Each model lists its certified terms
in a `neuron` entry under `nonportable_extensions`, `certified_by: "Claude, DG-00.02; owner to confirm"`.

**How they were written:** from the schema DDL and the documented business rules only. The
D3 and D1 evaluation questions were not read (D13). Every descriptive claim was checked against
the data. For example, D1's customer ledger holds only invoices and payments.

```bash
D1_SRC=<auto-ontology-eval@e727e4d> D3_ADMIN_DSN="host=... port=... user=postgres" ../d1/load.sh
OSSIE_SRC=<apache/ossie@91689e6> D3_DSN="host=... port=..." PYTHON=<python with jsonschema 4.26.0, pyyaml 6.0.3, sqlglot 30.33.0, psycopg 3> ./validate.sh
```
