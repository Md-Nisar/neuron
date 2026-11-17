# Bugs and fixes

Knowledge (RAG) scope, functional-testing round. Every item below was found by running the real stack
(Postgres 16 + pgvector 0.8.7, API, ingestion worker, docling-serve, web app, live NVIDIA models) and is traceable
to scenario IDs in `manual_test_scenarios.csv`. "Verified" means the failing scenario/test was re-run against the
fixed code, not that the code was re-read.

Summary: **5 product defects fixed** (2 code/behaviour, 1 UI behaviour, 2 documentation/contract), **1 test-infrastructure
hardening fixed**, **1 feature gap and 9 observations left open** (with recommendations). Nothing found was a data-isolation
or authentication failure: tenant isolation, role grants, RLS and least-privilege roles held in every scenario.

Also listed (section 4): Cycle 1 had 20 first-contact failures, but only 4 were product defects (BUG-01..04); 13 were my own test mistakes,
1 was environment, 1 an observation and 1 a feature gap, so the failure count is not a defect count.

## 1. Fixed

| ID | Severity | Area | Found by |
|----|----------|------|----------|
| BUG-01 | Medium | API / search | SRCH-11 (Cycle 1), regression SRCH-21 |
| BUG-05 | Medium | Web UI / upload | UI-40 (Cycle 2), verified in the browser |
| BUG-03 | Low | API contract | KB-05, KB-21 |
| BUG-02 | Low | Docs (idempotency) | DOC-10, DOC-10b |
| BUG-04 | Low | Docs (agent tools) | AGENT-06 |
| TI-01 | Low | Test infrastructure / secret hygiene | live rerank gate, Cycle 1 |

### BUG-01 (Medium): a NUL byte in a search query returned HTTP 503 and fired the alert path
- **Repro:** `POST /v1/knowledge/search {"query": "a\u0000b"}` as any signed-in user. Response `503 internal_server_error`;
  log `knowledge_search_failed ... DataError`, mapped to `persistence_error` (documented as `alert=true`).
  The same character was already rejected with 422 on base names and with 400 on the agent message, so search was the odd one out.
- **Impact:** any authenticated user can raise a pageable "database error" at will; the model-driven `search_knowledge` tool
  would have reported "knowledge unavailable" for the same input.
- **Root cause:** `KnowledgeSearchRequest.query` only checked blank/length; Postgres cannot store or compare NUL in `text`.
- **Fix:** `schemas/knowledge.py` rejects control characters (except tab/newline/CR) with 422; `knowledge/tools.py` rejects a NUL
  in the tool's `query` with the tool's fixed invalid-input error.
- **Regression tests (fail before, pass after):** `tests/security/test_knowledge_api.py` `search-nul-character`, `search-control-character`;
  `tests/security/test_knowledge_tools.py` NUL case. Browser/API scenario SRCH-21.

### BUG-05 (Medium): dropping more files than the ingestion cap silently lost the extras
- **Repro:** select 8 text files at once in a base (server allows 5 documents in flight per user). Only 5 were stored; the other 3
  were refused with "Too many of your documents are still being processed. Try again in a moment." and had to be re-selected by hand.
  A folder upload of N files loses N-5.
- **Root cause:** `DocumentsPanel.upload` sent each file once with a fresh `Idempotency-Key`, and treated a busy refusal like a permanent
  error. The API helper's own comment says the caller keeps the key so a retry is safe, but nothing retried.
- **Fix:** `web/src/features/knowledge/DocumentsPanel.tsx`: a file refused as busy (`ingestion_concurrency_exceeded`, `upload_busy`) waits for the
  server's `Retry-After` (default 5 s, capped at 30 s) and is sent again with the **same** key, up to 10 attempts; after that the existing
  "refused" message is shown. No new UI state.
- **Tests:** two new Vitest cases (retry with same key and no alert while waiting; gives up and says so). **Verified in the browser:** UI-40
  went from 5/8 stored to 8/8 Ready in 35 s.

### BUG-03 (Low): OpenAPI said base names may be 200 characters; 80 is enforced
- **Repro:** `GET /openapi.json` shows `maxLength: 200` for `KnowledgeBaseCreate.name` and `KnowledgeBaseUpdate.name`; a 100-character name returns 422.
  Docs say 1 to 80. Generated clients would validate against the wrong limit.
- **Fix:** both schemas use a named constant `NAME_MAX_CHARS = 80` (a local constant because `schemas.agent` already imports this module).
- **Test:** `test_the_advertised_name_limit_is_the_enforced_one` ties the OpenAPI limit to `plain_title`'s limit. Scenario KB-21.

### BUG-02 (Low, documentation): idempotency conflict was documented as "different base or file"
- **Observed:** reusing a key with a different *file* in the same base returns the first document (202); only a different *base* gives 409.
  The route docstring states this deliberately ("returns the first document without reading the body"), so the code is the design and the docs were wrong.
- **Fix:** `docs/.../error-catalogue.md` and `how-to/knowledge-engine-rag.md` now describe the real behaviour, including "use a fresh key for a different file".
- **Scenarios:** DOC-10 (other base: 409) and DOC-10b (same base: replay).

### BUG-04 (Low, documentation): agent knowledge tools are not gated on `knowledge_base_ids`
- **Observed:** the how-to said the three knowledge tools exist "when `knowledge_base_ids` is provided". In fact they search every base the caller can read;
  the ids only narrow the search, and ids the caller cannot read (or that were deleted) are ignored, not errors. Verified with AGENT-06 (Alice finds her handbook
  with no ids, and Bob's secret is not disclosed). Scenario notes also refer to this as "OBS-07".
- **Fix:** how-to section 4 rewritten.

### TI-01 (Low): a failing live test printed the real NVIDIA key into the log
- **Observed:** pytest prints a failing test's fixture arguments with `repr`; `live_nvidia_key` returned a plain `str`, so the key appeared in the failure
  report of `test_live_knowledge_rerank.py` (this happened to me; I redacted the log before saving it). CI masks secrets, local runs and saved logs do not.
- **Fix:** `tests/conftest.py` returns `MaskedSecret` (a `str` subclass with a masked `repr`; still usable as the key).
  Test `tests/unit/test_live_key_fixture.py` fails (ImportError) without the change.

## 2. Open: feature gap

| ID | Description | Recommendation |
|----|-------------|----------------|
| GAP-01 (UI-34) | The web UI has no way to download an original file; `GET /v1/knowledge/documents/{id}/file` exists and the functional spec lists "download original files" for `read`. Backlog RAG-03.04 scopes the UI to chunk inspection only, so this is an enhancement, not a regression. | Add a download action to the document row and the source sheet if the spec's wording is meant to cover the web app. |

## 3. Open: observations (not fixed; each is a judgement call for the maintainers)

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

## 4. Cycle 1 first-contact failures that were not product defects

Scenario expectations I got wrong, environment, an observation and a gap, kept visible rather than silently edited (the four real defects are BUG-01..04 above). Full text is in the `cycle1_triage` column of the CSV.

| Scenario | Cause |
|----------|-------|
| AUTH-12 | `/health` is deliberately exempt from the Host check; `/v1` enforces it (400). |
| DOC-15 | httpx sent urlencoded instead of multipart; the API correctly answered 415 `multipart_required`. |
| DOC-30 | Observation OBS-01 (clean refusal accepted; message is the issue). |
| SRCH-01 | My formatter indexed `headings[-1]` on a chunk with no headings. |
| SHARE-07 | `bad role!` is a legal role name by design (outer whitespace and control characters are not). |
| AGENT-13 / AGENT-14 | Unknown ids are ignored by design (OBS-08); an over-long message is a 400 `validation_error`. |
| DOC-31 | Environment: XLSX/PDF/Office need docling-serve; passes once it runs. |
| UI-16 | Tokens live in memory only (by design), so a reload requires signing in again. |
| UI-17 | My check read the list before it loaded; a shared role name also matched bases from earlier runs. |
| UI-19, 20, 21 | My harness waited on `response.finished()` of an SSE stream, which never resolves. The product answered in 13-20 s. |
| UI-22 | Locator matched the "Knowledge" nav button, not the chat picker. |
| UI-25 | The erase flow needs the typed phrase and a repeat (OBS-06). |
| Integration `test_postgres_roles` (3) | Environment: the tests assume a `postgres` superuser. 32/32 pass once it exists. |
| Live rerank gate | Environment: provider latency exceeded the 6 s default timeout; passes at 20 s. |

Later cycles' first-attempt failures (also test-side): AGENT-17, DOC-31 (provider `rate_limit_error` under 4-way parallel load, pass in isolation), UI-18 (check raced the list load),
AGENT-19 (thread ids are server-issued), DB-04 (counted blobs globally while other scenarios wrote), TAB-05 (matched digits inside a UUID), WEB-13 (Wikipedia blocks the fetcher), UI-38 (harness did not pass the browser object), UI-25 in Cycle 3 (repeat-erase flow).

## 5. Files changed

```
 docs/product_documentation/how-to/knowledge-engine-rag.md      |  4 +--
 docs/product_documentation/reference/error-catalogue.md        |  2 +-
 src/neuron_agent/knowledge/tools.py                            |  2 +-
 src/neuron_agent/schemas/knowledge.py                          |  9 +++--
 tests/conftest.py                                              | 15 +++++++-
 tests/security/test_knowledge_api.py                           | 13 +++++++
 tests/security/test_knowledge_tools.py                         |  1 +
 tests/unit/test_live_key_fixture.py                            | new (20 lines)
 web/src/features/knowledge/DocumentsPanel.test.tsx             | 40 ++++++++++
 web/src/features/knowledge/DocumentsPanel.tsx                  | 27 +++++++--
```
Product code changed: 38 lines. No dependency was added.
