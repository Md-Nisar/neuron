# DG-00.06: safety prototype (spike S3)

| File | Purpose |
| --- | --- |
| `gateway.py` | Gateway prototype: identity (persona login and data role) -> engine decision -> nl2data-ref guard -> A' executor (read-only, SET LOCAL ROLE, 15 s, one statement), with a foreign-row probe in the same transaction; runs the 60 adversarial cases (`../d3/adversarial.jsonl`) and writes `results.json` and `cases.md` |
| `cases.md` | Case-by-case log: every case, every path, its outcome |
| `test_mart_bypass.py` | nl2data-ref's guard-bypassed database tests (`tests/test_postgres_integration.py`), mapped to the mart's A' hardening; `bypass_tests.txt` is the last run |

Engine decisions are replayed from the DG-00.05 runs (arms C, B (D16), A1, A2), so the safety run
covers exactly the outputs the accuracy table scores. The 26 SQL cases run twice: through the
gateway, and straight to the executor with the guard bypassed.

    D3_DSN="host=... port=..." python gateway.py      # psycopg 3, sqlglot 30.33.0
    D3_DSN="host=... port=..." pytest test_mart_bypass.py
