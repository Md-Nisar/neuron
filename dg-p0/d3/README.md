# D3 mart (DG-00.01)

Spike code on `spike/data-gateway-p0`; never merged to `main`. Results go to
`docs/releases/data-gateway-p0/`.

| File | Purpose |
| --- | --- |
| `sql/01_sales_schema.sql` | Schema `sales`: regions, countries, customers, products, sales reps, orders, order lines, returns, rep compensation (confidential) |
| `sql/02_skills_schema.sql` | Schema `skills`: departments, employees, skills, assessment cycles, assessments, role targets, certifications, assessor notes (confidential) |
| `gen_sales.py` → `sql/03_sales_seed.sql` | Seed 20261123: 300 customers, 3,000 orders, 7,551 lines, 325 returns |
| `gen_skills.py` → `sql/04_skills_seed.sql` | Seed 20261124: 242 employees, 6,213 assessments, 138 certifications, 377 assessor notes |
| `sql/05_hardening.sql` | Option A': policies keyed on the data role through `app.role_regions`; one login per data role; forced, fail-closed RLS on every table, including the mapping itself (F3) |
| `sql/06_planted.sql` | Adversarial content: instructions planted in 9 names, 3 confidential notes and 10 column or table comments. Text only, no rows added |
| `questions.jsonl` | The 300 accepted questions: per domain 100 answerable, 30 unanswerable, 20 ambiguous, with expected results per persona |
| `adversarial.jsonl` | 60 adversarial cases (30 per domain): planted instructions, cross-role probes, write attempts |
| `personas.json` | `emea_analyst`, `apac_analyst`, `global_manager`, each with its own login and data role |
| `load.sh` | One command: recreates database `d3` and loads it |
| `check.py` | Acceptance checks: isolation, fail-closed, escape attempts, adversarial cases, every question |
| `batch.py` | Freezes one batch of 25 (`batches/<name>.src.jsonl`) with expected answers per persona, runs the second annotator, writes `batches/<name>.md` for owner review |
| `batches/` | One review file per batch: both annotators' queries and every persona's answer. A batch joins `questions.jsonl` only once accepted (by the owner; from D12 on, by Claude, logged) |

```bash
D3_ADMIN_DSN="host=... port=... user=postgres" ./load.sh
D3_DSN="host=... port=..." python check.py     # needs psycopg 3 and sqlglot 30.33.0
```

Generators use the standard library only and are deterministic: rerunning one reproduces its
SQL file byte for byte.

## Residual limit

`KNOWN escape: a session can lift statement_timeout` (finding F1c). A role's timeout is a
default; PostgreSQL 16 cannot stop a second statement from lifting it. The executor must set
`SET LOCAL statement_timeout` itself and run exactly one validated `SELECT`.
