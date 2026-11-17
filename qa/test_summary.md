# Test summary: Knowledge (RAG) functional testing, round 1

Date: 2026-11-17. Target: neuron v1.4.0, branch `ccr-7c4dd17f-k9sle9`. Tester: Claude (QA automation / architecture / full-stack roles as requested).
Companion files in this folder: `manual_test_scenarios.csv|json`, `test_coverage_report.md`, `bugs_and_fixes.md`, `regression_report.md`, `harness/` (everything needed to re-run), `raw_results/` (per-run JSON and gate logs), `evidence/` (screenshots).

## 1. Verdict

**The Knowledge feature set is in good shape.** Across 218 documented scenarios on the running stack, the final cycle passes 217 and fails 1, and that one is a documented feature gap, not a regression.
Tenant isolation, role-based sharing, row-level security, least-privilege roles, prompt-injection resistance, citation integrity, crash recovery and database-outage recovery all held in every scenario.
Testing found **5 product defects** (2 medium, 3 low), all fixed and re-verified, plus 1 test-infrastructure leak of the API key into failure logs (fixed). It also left **1 feature gap and 9 observations** open for decision (`bugs_and_fixes.md`).

| Layer | Final result |
|-------|--------------|
| Quality gates `make format lint typecheck test security` | all pass; **2775 tests passed**, 2 skipped; mypy strict, bandit, pip-audit clean |
| Frontend (lint, typecheck, format, build, audit, Vitest) | all pass; **625 tests**; 0 npm vulnerabilities |
| Postgres integration, real DB | **316 passed**, 13 skipped, 0 failed |
| Real Keycloak, docling-serve | 3 + 2 integration tests passed (skipped in earlier cycles) |
| Live-model gates | rerank gate, retrieval-quality gate and table-answers (`tools=on`, 8/8) **passed**; table baseline (`tools=off`) inconclusive (provider errors); 85-case answer gate not completed |
| Scenario catalogue (171 API-level, 47 browser incl. 7 on real Keycloak) | **217 PASS, 1 FAIL** (GAP-01); first-attempt 216 / 2 |
| Repo's own Playwright E2E | 12/12 (flows) and 6/6 (knowledge, with axe checks) |
| Code coverage | backend 97.1 % statements; frontend 95.2 % statements / 90.0 % branches |

## 2. The stack that was run (nothing mocked where a real service was available)

| Component | Real service used | Notes |
|-----------|-------------------|-------|
| Database | `pgvector/pgvector:pg16` (repo's pinned digest, pgvector 0.8.7) in Docker, repo's role and schema SQL | migrations 1-31, second run applies none |
| API | `uvicorn neuron_agent.api.main:app` (jwt auth, memory and knowledge on, postgres checkpointer) | native process |
| Ingestion worker | `neuron-worker` with only its own DSN (as in compose) | live NVIDIA embeddings |
| PDF/Office parser | docling-serve CPU image (repo's pinned digest), read-only, no capabilities | |
| Web app | production build served by `vite preview` on :5173 | |
| Identity provider | stand-in OIDC provider from the repo (`web/e2e/fake_idp.py`) plus a QA-only `/qa/mint` endpoint for Cycles 1-3; **real Keycloak 26.8.2** (repo realm, RS256, compose role mapping) for the real-IdP phase | KC-01..07 |
| Models | live NVIDIA catalog using the `LLM_*` key: chat `nemotron-3-ultra-550b-a55b`, embeddings `nemotron-3.5-embed-1b` (1024-d), reranker `nemotron-3.5-rerank-8b` | key was never written to the repo; one pytest traceback printed it into a saved log, which I redacted (TI-01 prevents recurrence) |

Deviations from "spin up everything": `docker compose` itself was not used because `docker build` of the app image fails behind this sandbox's TLS-intercepting proxy
(I did not disable verification); the same components ran as native processes or from the repo's pinned images. Details and impact: `regression_report.md`, "Not run / blocked".

## 3. What was tested

- **Unit, graph, security, resilience, e2e, eval** (2775): re-run in every cycle. New regression tests: 5 backend, 2 frontend.
- **Database**: migrations and idempotency, pgvector/halfvec/HNSW, RLS, role privileges, purge after delete, erase completeness, delete-during-ingestion, worker `kill -9` recovery, Postgres paused and resumed.
- **API (171 scenarios)**: auth, base CRUD, documents (md, txt, csv, xlsx, pdf, docx, pptx, web pages, hostile and malformed files, limits, idempotency, concurrency), search (semantic, exact, stemming, cross-lingual, injection, unicode), sharing, agent answers on the live model, tables, injection, data rights.
- **RAG quality**: citations resolve; unanswerable questions are not fabricated; four injection styles not obeyed; table totals exact; German and Spanish questions answered; PDF page numbers correct.
- **Browser (47)**: sign-in, knowledge screen, uploads (incl. 8 at once and 55 documents), sharing per role, chat with source sheet, tenant isolation, erase, mobile layout, keyboard use, axe accessibility (light and dark), outage handling, hostile markup, and the same journeys on real Keycloak.
- **Edge cases and failure conditions**: empty, binary, corrupt, encrypted, oversized, zip, macro files; NUL/control characters; foreign tokens; DB down; client disconnect; concurrency caps; provider throttling.

## 4. Defects found and fixed

| ID | Sev. | Summary |
|----|------|---------|
| BUG-01 | Medium | NUL byte in a search query returned 503 `persistence_error` (alerting) instead of 422 |
| BUG-05 | Medium | Web UI silently lost files beyond the 5-in-flight ingestion cap (8 dropped, 5 stored); now waits and retries with the same idempotency key (8/8 stored) |
| BUG-03 | Low | OpenAPI advertised base-name max 200; 80 is enforced |
| BUG-02 | Low | Docs promised 409 for a different file under a reused `Idempotency-Key`; the design replays the first document (docs corrected) |
| BUG-04 | Low | Docs said knowledge tools need `knowledge_base_ids`; they do not (docs corrected) |
| TI-01 | Low | Failing live tests printed the real API key (fixture now masked) |

Product code changed: 38 lines in 3 files, plus tests and docs (`bugs_and_fixes.md`, section 5).

## 5. Open items for the owner

- **GAP-01**: no "download original file" in the web UI (API route exists; functional spec mentions it).
- **OBS-07** (most worth a decision): knowledge/data endpoints have no statement/request deadline; with Postgres stalled, a request waits for the database (42 s observed) instead of failing fast. Other DB paths already set `statement_timeout`.
- **OBS-03/04**: the reranker's 6 s default timeout is frequently exceeded from this network (graceful RRF fallback), and no relevance floor exists when the reranker is on (unrelated queries still return passages with negative scores; the agent handled this correctly).
- **OBS-01, 02, 05, 06, 08, 09**: UX and tuning notes in `bugs_and_fixes.md`.

## 6. Limitations (read before relying on this)

- One tester, one machine, one browser (Chromium); no load, soak, multi-replica or production-environment testing (none exists yet, per `CLAUDE.md`).
- The live 85-case answer gate was stopped (documented to run for hours); live table-answers gate: the `tools=on` variant (the shipped feature, 8 cases: 6 whole-table aggregates + 2 lookups) **passed**; the `tools=off` baseline variant (expected to miss aggregates) was reported "inconclusive, rerun" because of 2 provider-side errors (`RunTimeoutError`, `StructuredOutputError`), not wrong answers. I did not re-run it.
- A live re-index to a second embedding model was not run; the repo's fake-provider re-index integration tests pass.
- Scanned/OCR PDFs and very large files were not tested. 9 Docker-image layout tests could not run (image build blocked).
- 13 of my 20 Cycle 1 first-contact failures were my own test mistakes; they are listed and were corrected openly, never by weakening a product assertion without saying so.
- Live-model scenarios depend on a free-tier provider and can fail on throttling (`rate_limit_error`); such cases were re-run in isolation and noted.

## 7. Re-running

```
# stack: Postgres (pgvector image) + roles/schema SQL from deploy/reference, then
uv run python -m neuron_agent.persistence.cli setup          # as migrator, APP_MEMORY_ENABLED=true
uv run neuron-worker ; uv run uvicorn neuron_agent.api.main:app --port 8000
# scenarios (tokens from the QA IdP in harness/qa_idp.py, or adapt tokens for Keycloak)
python qa/harness/run_api.py c4 ; node qa/harness/run_ui.js c4 ; node qa/harness/run_kc.js
python qa/harness/build_reports.py        # merges raw_results/ into manual_test_scenarios.*
```
`harness/` paths point at `/tmp/claude-0/qa` (scratch locations used in this session); adjust before reuse.
