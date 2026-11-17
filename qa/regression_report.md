# Regression report: three testing cycles

Scope: Knowledge (RAG) feature set of neuron v1.4.0, tested against the running stack (see `test_summary.md` for the environment).
Raw per-scenario results for each cycle are in `raw_results/`; the merged view is `manual_test_scenarios.csv/json`
(`cycleN_first_attempt` = first run in that cycle, `cycleN_status` = last run in that cycle, with the failed first attempt quoted in `cycleN_observations`).

| | Cycle 1: audit | Cycle 2: fix + regression | Cycle 3: final verification |
|---|---|---|---|
| Code under test | unmodified v1.4.0 | after BUG-01/02/03/04/05 | after TI-01 as well (final) |
| Scenarios existing | 174 (218 at the end; 44 were written later) | 211 | 218 |
| First attempt: PASS / FAIL | 154 / 20 | 201 / 10 (7 not yet written: real-Keycloak set) | 216 / 2 |
| Last result: PASS / FAIL | 160 / 14 | 209 / 2 | **217 / 1** |
| Product defects found | 5 (BUG-01..05; BUG-05 surfaced in Cycle 2) | 0 new after fixes (OBS and GAP only) | 0 |
| `make format lint typecheck test security` | pass; 2770 passed, 2 skipped | pass; 2774 passed, 2 skipped | pass; **2775 passed**, 2 skipped |
| Frontend lint / typecheck / format / build / audit | pass / pass / pass / pass / 0 vulns | pass (623 tests) | pass; **625 tests** (41 files) |
| Postgres integration (non-live) | all pass except 3 role tests (environment: no `postgres` superuser; 32/32 after creating one) | 315 passed, 14 skipped | **316 passed**, 13 skipped |

Notes on reading the table: a scenario that failed first for a test-side reason and passed after the *test* was corrected is counted as FAIL in "first attempt",
which is why the first-attempt FAIL counts are larger than the defect counts. The classification of every Cycle 1 failure is in `bugs_and_fixes.md` section 4.

## Cycle 1: initial audit, execution and bug identification (unmodified code)

1. Stood up the stack (Postgres 16 + pgvector, migrations 1-31 applied twice to prove idempotency, API, worker, stand-in IdP, web).
   **First environment finding:** the distro pgvector (0.6.0) cannot run migration 18 (`type "halfvec" does not exist`); the repo's pinned image (0.8.7) can. Not a product bug (the docs already require pgvector 0.7+), noted for local setups.
2. Gates: format, lint, mypy strict, bandit, pip-audit all clean; `make test` 2770 passed, 2 skipped.
3. Postgres integration: green apart from 3 role tests that assume a `postgres` superuser (environment). Live gates: rerank "inconclusive" (provider latency vs 6 s default); retrieval and answers gates exceeded the repo's 120 s per-test watchdog (they are nightly jobs, throttled to 30 calls/min).
4. Built the scenario catalogue and executed it: 126 API scenarios (115 passed on first contact, 11 failed), then 6 extra API scenarios, then docling-serve was added and 10 Office/PDF scenarios ran. 34 browser scenarios: UI-01..18 first run, UI-19..22 and the rest after harness repairs (see below).
5. Findings: BUG-01 (confirmed by SRCH-11), BUG-02/03/04 (contract and docs), OBS-01..05, GAP-01. Of Cycle 1's 20 first-contact failures: 4 were product defects (BUG-01/02/03/04), 13 were my own test mistakes (6 API, 7 UI), 1 was environment (DOC-31, no parser), 1 an observation (DOC-30) and 1 a feature gap (UI-34). Each is listed in `bugs_and_fixes.md` section 4.
6. Harness repairs during the cycle (not product changes): the first UI run was lost to my own 25-minute timeout (results were saved only at the end); it was rewritten to save after every scenario and to enforce a per-scenario limit.

## Cycle 2: fixes, refactoring, complete regression

Fixes applied (see `bugs_and_fixes.md`): BUG-01 (code + 3 regression tests), BUG-03 (schema + 1 test), BUG-02/04 (docs), later BUG-05 (UI + 2 tests) and TI-01 (test fixture + 1 test).
Each regression test was **run first against the unfixed code and observed failing**:

| Fix | Regression test | Before fix | After fix |
|-----|-----------------|------------|-----------|
| BUG-01 | `test_knowledge_api.py::test_an_invalid_request_is_422[search-nul-character]`, `[search-control-character]` | FAILED (got 503 / 200) | pass |
| BUG-01 | `test_knowledge_tools.py::test_invalid_arguments_get_one_fixed_error[...search_knowledge-args2]` | FAILED (tool ran the query) | pass |
| BUG-03 | `test_the_advertised_name_limit_is_the_enforced_one` | FAILED (`200 == 80`) | pass |
| BUG-05 | `DocumentsPanel.test.tsx` "waits out a 'too many in processing' refusal and retries the file with the same key" | FAILED | pass (17/17) |
| TI-01 | `tests/unit/test_live_key_fixture.py` | ImportError | pass |

Full regression after the fixes:
- API catalogue re-run in full against the fixed API: **140 of 142 passed**; the 2 failures were `rate_limit_error` from the NVIDIA free tier under 4-way parallel load (AGENT-17, DOC-31). Both passed on isolated re-run together with the worker-crash scenario (RES-01).
- New scenarios added and run: Office/PDF (8), tables (5), database (7: RLS, least privilege, migrations, purge, erase, delete-while-ingesting), security/injection (4), boundaries (7), resilience (DB outage, client disconnect, concurrency cap), feedback.
- Browser: 34 scenarios, 32 passed. The 2 failures: UI-34 (GAP-01) and UI-18 (my check raced the list load; passes in Cycle 3). Then UI-35..40 were added: **UI-40 failed for a real reason (BUG-05)**, was fixed and re-verified in the browser the same cycle.
- `make test` 2774 passed; integration 315 passed / 14 skipped / 0 failed; frontend 623 tests (then 625).

## Cycle 3: final verification and regression validation (final code)

| Layer | Result |
|-------|--------|
| `make format lint typecheck test security` | exit 0. ruff clean, mypy strict clean (124 files), **2775 passed, 2 skipped**, bandit clean, pip-audit "No known vulnerabilities" |
| Frontend | prettier, eslint, tsc, build all clean; **625 passed (41 files)**; `npm audit` 0 vulnerabilities |
| Postgres integration (real DB, non-live) | **316 passed, 13 skipped (9 image-layout, 3 Keycloak in that run, 1 eval dir), 0 failed**, run while a DB-outage scenario paused the same Postgres |
| Keycloak integration (real Keycloak 26.8.2) | 3 passed (skipped in earlier cycles) |
| docling-serve integration | 2 passed |
| Live retrieval-quality gate (live embeddings + reranker, 20 s rerank timeout) | passed (490 s) |
| Live rerank gate (20 s rerank timeout) | passed (584 s) |
| API catalogue, full, final code | **167 / 167 passed** in one run, plus RES-01, RES-02, AGENT-19, AGENT-20 isolated: 4 / 4 |
| Browser catalogue (Chromium, 40 scenarios) | 38 passed; UI-34 = GAP-01; UI-25 failed first (my scenario did not follow the designed repeat-erase flow) and passed after correcting the scenario |
| Real identity provider (Keycloak, 7 scenarios) | **7 / 7 passed**: PKCE login, bad password, full RAG journey with a PDF page citation, reader refusal, sign-out, cross-tenant, grant-needs-permission |
| Repo Playwright E2E (`web/e2e`, default config: fake model, in-memory) | **12 / 12 passed** |
| Repo Playwright knowledge E2E (Postgres + worker, fake embeddings, axe checks) | **6 / 6 passed** (after fixing my own provisioning: `setup` must run with `APP_MEMORY_ENABLED=true`) |
| Live table-answers gate | `tools=on` (shipped feature): **passed, 8/8 correct**; `tools=off` baseline: inconclusive (2 provider-side errors, `RunTimeoutError` and `StructuredOutputError`), not re-run |

Regression verdict: no scenario that passed in an earlier cycle failed in a later one. Every scenario that failed in Cycle 1 either passed after a product fix (SRCH-11, KB-05 -> KB-21, DOC-10 -> DOC-10b, AGENT-06),
after correcting a wrong expectation, or remains open and documented (UI-34 / GAP-01).

## Not run / blocked (stated, not hidden)

| Item | Why | Substitute evidence |
|------|-----|---------------------|
| `docker compose up` of the reference stack | API image build fails in this sandbox: `docker build` does not trust the sandbox's TLS-intercepting proxy (`uv sync`: `UnknownIssuer`). I did not disable verification. | Same components started natively; Postgres/docling/Keycloak run from the repo's pinned images with the repo's init SQL, realm and hardening flags. |
| `tests/integration/test_image_layout.py` (9 tests) | Needs the `neuron-test` image (same cause) | None (Dockerfile layout unverified here). |
| Keycloak login theme | Theme build (`npm ci`, Maven) needs the same blocked network; stock Keycloak image used | Functional login verified (KC-01..07). |
| `test_live_knowledge_answers.py` (85 cases) | Documented to take hours at 30 calls/min; stopped after ~10 minutes to leave the provider budget for Cycle 3 | Functional answer-quality scenarios AGENT-01..21, TAB-01..05, OFF-02, UI-19..23 on the live model (all pass). |
| Live re-index to a second embedding model | Not executed live | `test_postgres_knowledge_reindex*.py` (CLI, swap, retire, locality) all pass on real Postgres with the fake provider. |
| Load / performance, multi-replica, production environment | Out of scope for functional testing round 1; no production environment exists (CLAUDE.md) | Single scenario timings are in `test_summary.md`. |
| Other browsers, Safari/iOS, screen readers | Chromium only | axe-core (light and dark) on the Knowledge screen passes (UI-29, repo E2E). |
