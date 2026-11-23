# D3 mart (DG-00.01)

Spike code on `spike/data-gateway-p0`; never merged to `main`. Results go to
`docs/releases/data-gateway-p0/`.

| File | Purpose |
| --- | --- |
| `sql/01_schema.sql` | Sales schema: regions, countries, customers, products, sales reps, orders, order lines, returns, rep compensation |
| `sql/02_hardening.sql` | ADR 0016 decision 5, adapted from `nl2data-ref`: claims via a `SECURITY DEFINER` function, forced fail-closed RLS, one login per data role |
| `gen_seed.py` → `sql/03_seed.sql` | Deterministic synthetic data (seed 20261123): 300 customers, 3,000 orders, 7,551 lines, 325 returns |
| `personas.json` | `emea_analyst`, `apac_analyst` (role `d3_analyst`), `global_manager` (role `d3_manager`) |
| `load.sh` | One command: recreates database `d3` and loads it |
| `check.py` | Acceptance checks: isolation, fail-closed, escape attempts, reference questions |

```bash
D3_ADMIN_DSN="host=... port=... user=postgres" ./load.sh
D3_DSN="host=... port=..." python check.py     # needs psycopg 3 and sqlglot 30.33.0
```

## Known failures

Three escape checks fail (F1, F1b, F1c in the log): `SET app.regions`, `RESET ROLE` then `set_claims`, and lifting `statement_timeout`. Revoking `set_config` does not
block the `SET` command, so with the guard bypassed a second statement can rewrite the claims
and read other regions. Recorded as finding F1 in the design spike log; fix awaiting owner
decision.
