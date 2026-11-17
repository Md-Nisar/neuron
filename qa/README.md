# QA round 1: Knowledge (RAG) functional testing

Start with `test_summary.md`. Then `bugs_and_fixes.md`, `regression_report.md`, `test_coverage_report.md`.

- `manual_test_scenarios.csv` / `.json`: 218 scenarios, each with ID, area, description, preconditions, steps, expected result, and for each of the three cycles the first-attempt status, final status, actual result and observations. `cycle1_triage` classifies every Cycle 1 failure.
- `harness/`: the executable scenarios (`scen*.py` API-level, `run_ui.js` browser, `run_kc.js` real Keycloak), the QA-only token endpoint (`qa_idp.py`), and `build_reports.py`. Paths refer to `/tmp/claude-0/qa` (scratch space of the session); adjust to reuse.
- `raw_results/`: untouched per-run JSON results and the gate/test logs per cycle (`gates/c1..c3`). One log had the live API key in a pytest traceback; it is redacted.
- `evidence/`: a few screenshots (landing after reload, bulk-upload bug, erase flow, mobile layout, RAG chat with citation).

Nothing here is product code; the product changes are in the separate commit "Fix defects found in Knowledge functional testing".
