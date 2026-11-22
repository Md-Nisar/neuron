# nl2data-ref

Tested reference components for *AI-to-Database Solution Architecture v2.0*.

| Module | Purpose |
|---|---|
| `guard.py` | Allowlist SQL guard (sqlglot 30.33.0 pinned) |
| `metrics.py` | Typed Tier 1 metric requests and server-side filter compilation |
| `answer_checks.py` | Runtime numeric faithfulness check; golden-set result comparator |
| `governance.py` | Scope-partitioned value index, trace redaction, router threshold calibration |
| `executor.py` + `sql/001_hardened_model_b.sql` | Identity model B on Postgres 16 with DB-enforced claims |
| `capacity.py` | Cost-per-answer, peak QPS and warehouse concurrency (Little's law) |

```bash
pip install -e '.[test]'
pytest -q                                  # unit tests
# integration (needs a disposable Postgres 16 you can administer):
PG_TEST_DSN_ADMIN="host=... user=postgres dbname=postgres" \
PG_TEST_DSN_AGENT="host=... user=agent_login_finance dbname=postgres" pytest -q
```

Reference code, not a product: review, pin, and extend the function allowlist deliberately.
