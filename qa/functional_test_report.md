# Functional test report: Knowledge (RAG), round 1

Date: 2026-11-17. Target: neuron v1.4.0, branch `ccr-7c4dd17f-k9sle9`. Tester: Claude (QA automation / architecture / full-stack roles as requested).
Test cases and their status: `manual_test_scenarios.csv` / `.json` (same data, 218 scenarios).

## 1. Verdict

**The Knowledge feature set is in good shape.** Across 218 documented scenarios on the running stack, the final cycle passes 217 and fails 1, and that one is a documented feature gap, not a regression.
Tenant isolation, role-based sharing, row-level security, least-privilege roles, prompt-injection resistance, citation integrity, crash recovery and database-outage recovery all held in every scenario.
Testing found **5 product defects** (2 medium, 3 low), all fixed and re-verified, plus 1 test-infrastructure leak of the API key into failure logs (fixed). It also left **1 feature gap and 9 observations** open for decision ().

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
(I did not disable verification); the same components ran as native processes or from the repo's pinned images.

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

Product code changed: 38 lines in 3 files, plus tests and docs.

## 5. Open items for the owner

**Feature gap**


| ID | Description | Recommendation |
|----|-------------|----------------|
| GAP-01 (UI-34) | The web UI has no way to download an original file; `GET /v1/knowledge/documents/{id}/file` exists and the functional spec lists "download original files" for `read`. Backlog RAG-03.04 scopes the UI to chunk inspection only, so this is an enhancement, not a regression. | Add a download action to the document row and the source sheet if the spec's wording is meant to cover the web app. |


**Observations (not fixed; judgement calls)**

# Open: observations (not fixed; each is a judgement call for the maintainers)

| ID | Obs. | Evidence | Recommendation |
|----|------|----------|----------------|
| OBS-01 | A text file that is not UTF-8 (for example cp1252 "Café") is refused as `unsupported_media_type`, with no hint that the problem is the encoding. | DOC-30 | Return a specific code/message ("save as UTF-8"), or decode with a fallback. |
| OBS-02 | The web app shows "Not grounded: no passage in your documents supports this answer" under answers that never needed documents (for example "What is 18% of 2450?"). | UI-24 | Show the banner only when the user selected bases or the answer claimed document support. |
| OBS-03 | The reranker's default 6 s timeout (`APP_KNOWLEDGE_RERANKER_TIMEOUT_SECONDS`) is often exceeded from this sandbox: 11 `knowledge_rerank_skipped rerank_timeout` events in Cycle 1; the live rerank gate was "inconclusive" (fell back to RRF) at the default and **passed** at 20 s. Search degrades correctly to RRF with `reranked:false`. A comment in `test_live_knowledge_retrieval.py` still says the production timeout is 3 s. | SRCH-20, live gate | Consider a higher default or an adaptive timeout for hosted rerankers; surface `reranked` in operations dashboards; fix the stale comment. |
| OBS-04 | There is no relevance floor with the reranker on: an unrelated query returns 4 passages with negative scores (about -4) and `status: ok`. The agent still answered correctly ("not in your documents", AGENT-03 / UI-21), so there is no user-visible defect, but `no_relevant_results` cannot fire. | SRCH-04 | Apply a minimum rerank score, tuned on the eval set. |
| OBS-05 | The agent searched knowledge for an arithmetic question (no bases at all) and sometimes repeats a search 2-3 times in one turn. | UI-22, UI-24 | Prompt/tool tuning only; cost and latency, not correctness. |
| OBS-06 | "Erase all my data" with documents present needs a second confirmation ("Your knowledge files are still being deleted. Try again in a moment") and the phrase must be retyped. Designed (asynchronous purge, matches the repo's own E2E), but easy to miss. | UI-25 | Keep the phrase filled and auto-retry. |
| OBS-07 | The knowledge/data endpoints have no statement or request deadline. With Postgres stalled (not down), readiness correctly turns 503 after 12 s and liveness stays 200, but an in-flight list request waits until the database returns (42 s here) and then succeeds. The run guard, token ledger and rate limiter all set `statement_timeout`. | RES-02 + manual stall test | Set a bounded `statement_timeout` for API-role knowledge transactions (needs an operational decision and a setting). |
| OBS-08 | Unknown or deleted ids in `knowledge_base_ids` are ignored silently (by design, to avoid revealing existence); the caller gets an ungrounded answer rather than an error. | AGENT-13 | Fine for security; consider a `scope_ignored` hint in the response. |
| OBS-09 | A Wikipedia page was refused by the fetcher with `fetch_http_status` (the site answers non-200 to this client); example.com and docs.python.org ingest and cite correctly with `source_url`. | WEB-11, WEB-13 | External; document that some sites block bots. |


## 6. Limitations (read before relying on this)

- One tester, one machine, one browser (Chromium); no load, soak, multi-replica or production-environment testing (none exists yet, per `CLAUDE.md`).
- The live 85-case answer gate was stopped (documented to run for hours); live table-answers gate: the `tools=on` variant (the shipped feature, 8 cases: 6 whole-table aggregates + 2 lookups) **passed**; the `tools=off` baseline variant (expected to miss aggregates) was reported "inconclusive, rerun" because of 2 provider-side errors (`RunTimeoutError`, `StructuredOutputError`), not wrong answers. I did not re-run it.
- A live re-index to a second embedding model was not run; the repo's fake-provider re-index integration tests pass.
- Scanned/OCR PDFs and very large files were not tested. 9 Docker-image layout tests could not run (image build blocked).
- 13 of my 20 Cycle 1 first-contact failures were my own test mistakes; they are listed and were corrected openly, never by weakening a product assertion without saying so.
- Live-model scenarios depend on a free-tier provider and can fail on throttling (`rate_limit_error`); such cases were re-run in isolation and noted.

## 7. Coverage

Backend 97.1 % statements (knowledge package 96.4 %, security 96.4 %, persistence 96.0 %, api 95.6 %, worker 87.8 %; branch coverage not enabled in the repo config).
Frontend 95.2 % statements, 90.0 % branches, 96.8 % lines. Every feature layer (auth, bases, documents, search, sharing, agent, tables, web pages, data rights, UI) is covered by at least one scenario; gaps are listed in section 6.

## 8. Results per cycle

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

A scenario that failed first for a test-side reason and passed after the test was corrected counts as a first-attempt FAIL, which is why first-attempt FAIL counts exceed defect counts. Of Cycle 1's 20 first-contact failures: 4 product defects, 13 test mistakes of mine, 1 environment, 1 observation, 1 feature gap.
