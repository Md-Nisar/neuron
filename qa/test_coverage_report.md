# Test coverage report

Two kinds of coverage: **measured code coverage** (tooling output) and **feature coverage** (what each layer was exercised against, from the scenario catalogue).
Measured numbers are from the final code, Cycle 3.

## 1. Measured code coverage

### Backend (`src/neuron_agent`), `coverage` 7.16 over the whole offline suite plus the real-Postgres integration suite

Command: `coverage run --parallel-mode --source=src/neuron_agent -m pytest tests/unit tests/graph tests/security tests/resilience tests/e2e tests/evals`
and the same for `tests/integration -m integration` (non-live, real Postgres + docling-serve), then `coverage combine`.

**Total: 97.1 % statement coverage (10,152 statements, 294 missed).** Branch coverage was not enabled in the repo's config and was not measured.

| Package | Statements | Missed | Coverage |
|---------|-----------:|-------:|---------:|
| knowledge (RAG engine) | 2768 | 101 | 96.4 % |
| persistence (Postgres, migrations, limits) | 1629 | 65 | 96.0 % |
| security (auth, authorization, input policy) | 878 | 32 | 96.4 % |
| api | 817 | 36 | 95.6 % |
| services | 808 | 17 | 97.9 % |
| top-level modules | 586 | 12 | 98.0 % |
| models | 533 | 15 | 97.2 % |
| config | 489 | 5 | 99.0 % |
| tools | 442 | 5 | 98.9 % |
| observability | 393 | 3 | 99.2 % |
| schemas | 318 | 2 | 99.4 % |
| graphs / errors / agents / state / prompts | 314 | 0 | 100 % |
| memory | 177 | 1 | 99.4 % |

Knowledge engine by module (statements, coverage): `authorization` 21 / 100 %, `blobs` 139 / 95.0 %, `chunking` 75 / 100 %, `citations` 30 / 100 %,
`docling_serve` 186 / 98.4 %, `ingest` 243 / 96.7 %, `jobs` 29 / 100 %, `parsing` 304 / 96.7 %, `providers` 124 / 99.2 %, `purge` 41 / 100 %,
`reconcile` 77 / 98.7 %, `reindex` 134 / 94.8 %, `reranking` 75 / 100 %, `retrieval` 220 / 97.3 %, `service` 367 / 96.2 %, `table_engine` 106 / 98.1 %,
`tables` 95 / 100 %, `tools` 239 / 95.8 %, **`worker` 263 / 87.8 %** (lowest: process lifecycle, signal handling and drain paths).

Interpretation: coverage says the code ran, not that behaviour is right. The 4 lines I changed in product code are covered by new tests that fail without them (`bugs_and_fixes.md`).
Live-provider code paths are covered by real calls in the scenario runs, but those calls are not in the coverage run (the live suites need minutes to hours).

### Frontend (`web/src`), Vitest 5.0.5 + v8 coverage (temporary `--no-save` install; `package.json` and the lockfile are unchanged)

**Total: statements 95.2 %, branches 90.0 %, functions 95.7 %, lines 96.8 %** (625 tests, 41 files).

| Area | Lines | Branches | Functions |
|------|------:|---------:|----------:|
| features/knowledge (screen, documents, sharing) | 96.7 % | 85.3 % | 96.4 % |
| features/chat (composer, sources, picker, feedback) | 97.0 % | 92.9 % | 95.7 % |
| features/data (export, erase, memories) | 98.6 % | 91.1 % | 100 % |
| features/threads | 98.4 % | 88.3 % | 100 % |
| lib/auth (OIDC PKCE) | 96.6 % | 92.5 % | 98.2 % |
| lib/stream (SSE client) | 99.1 % | 92.0 % | 93.8 % |
| lib (request) | 88.1 % | 93.8 % | 85.7 % |

The knowledge UI has the lowest branch coverage (85.3 %); the real-browser scenarios below cover its error and role branches that unit tests mock.

## 2. Feature coverage by layer

Legend: **R** = exercised against real services (Postgres, worker, docling, Keycloak, live NVIDIA models), **S** = stand-in IdP, **F** = fake/in-memory (repo's own tests).

### Database (Postgres 16 + pgvector 0.8.7, `halfvec`, HNSW)
| Aspect | Evidence | Mode |
|--------|----------|------|
| Migrations 1-31, idempotent re-run, vector >= 0.7 and an HNSW index present | setup run twice, DB-03, `test_postgres_migrations` | R |
| Row-level security on chunks / embeddings / document_tables (app role sees 0 rows without a scope) | DB-01, `test_postgres_roles` (32 tests, with a `postgres` superuser) | R |
| Least privilege (app and worker cannot truncate, drop, create; worker cannot read checkpoints) | DB-02, role tests | R |
| Cross-tenant ownership of rows | DB-07, KB-15, SRCH-07/08, DOC-18/20/25 | R |
| Purge after document delete: chunks, embeddings and the blob file | DB-04 | R |
| Erase-my-knowledge removes bases, documents, chunks | DB-05, DATA-02/03, UI-25 | R |
| Delete base while documents are ingesting leaves no orphans; worker survives | DB-06 | R |
| Worker killed mid-ingestion: stalled jobs reclaimed (4 documents, 40 s) | RES-01 | R |
| Database stalled / outage: readiness 503, liveness 200, recovery without restart | RES-02 + manual stall test (finding OBS-07) | R |
| Job queue, reconcile, rate limiter, token budget, run guard, quotas, sharing, reindex, web-page and table storage | 34 `tests/integration/test_postgres_*.py` files: 316 passed | R |

### Backend / API (171 scenarios + 2775 automated tests)
| Feature | Scenarios | Mode |
|---------|-----------|------|
| Authentication: missing/garbled/expired/wrong-audience/foreign-key/`alg=none` tokens, scopes, header spoofing, Host and CORS | AUTH-01..13, KC-01/02/06/07 | S and R (Keycloak) |
| Knowledge-base CRUD, limits, naming, unicode, rename, delete, cap of 20, isolation | KB-01..22 | R |
| Documents: md, txt, csv, xlsx, pdf, docx, pptx; empty, whitespace, binary, corrupt, oversized (51 MB), zip, macro, encrypted, encoding, long names/lines, traversal, idempotency, concurrency, pagination, download, chunk read, delete | DOC-01..38, OFF-01..08 | R |
| Web pages: 10 unsafe-URL classes refused (http, credentials, localhost, loopback, RFC1918, metadata IP, IPv6, scheme, garbage, over-length); 2 real public pages ingested and cited with `source_url` | WEB-01..13 | R |
| Search: semantic, exact keyword, cross-document, German stemming, cross-lingual, limits, SQL-injection and tsquery operators, unicode, NUL/control (BUG-01), deleted doc/base, scores, rerank on/off | SRCH-01..22 | R |
| Sharing: read / write / admin semantics, revoke, invalid roles, exact case-sensitive role match, non-member | SHARE-01..11, UI-16/17/38, KC-07 | R |
| Agent answers on the live model: grounded + citation, multi-document, unanswerable, indirect injection (4 variants), cross-tenant, tables, German/Spanish, follow-up thread, streaming, citation resolution, disconnect mid-stream, concurrency cap, feedback | AGENT-01..21, SEC-01..04, TAB-01..05 | R |
| Tables: `;` CSV, quoted commas, 1,500-row aggregate (233,932 computed exactly), blanks and duplicate headers, XLSX | TAB-01..05, DOC-31, OFF-07 | R |
| Data rights: export scope, erase, unauthenticated access | DATA-01..04 | R |

### Frontend (47 browser scenarios, Chromium 1280x900 and 390x844) plus the repo's 18 Playwright specs
| Feature | Scenarios | Mode |
|---------|-----------|------|
| Sign-in/out, signed-out landing, no data leak after sign-out and Back | UI-01/02/26, KC-01/05 | S, R |
| Knowledge screen: create (processing + language), validation messages, double-click, 80-char limit, rename, two-step delete, keyboard-only, XSS in names | UI-03..07, 14, 15, 28, 32, 33, 36 | S |
| Documents: upload (single, three, eight at once, 55 listed), unsupported/corrupt file messages, http URL refusal, delete with confirm | UI-08..13, 39, 40 | S |
| Sharing UI per role (read / write / manage), tenant isolation | UI-16, 17, 18, 38 | S |
| Chat with RAG: answer, source chips, source sheet, picker restriction, unanswerable, reload persistence, deleted source, conversation delete | UI-19..24, 37 | S |
| Real PDF journey with page citation "p. 2" opened in the UI; reader role refusal | KC-03, KC-04 | R (Keycloak) |
| Data rights screen, erase with repeat flow | UI-25 | S |
| Accessibility: axe-core light and dark; keyboard; mobile overflow | UI-27..29 and repo `knowledge.spec.ts` axe checks | S |
| Resilience: API outage on the Knowledge screen, 503 on chat | UI-30, UI-31 | S |
| Security: hostile markdown/HTML in answers, no request to foreign hosts, no dialogs | UI-35, UI-36, repo `flows.spec.ts` | S |
| Repo E2E: 12 flow/download specs; 6 knowledge specs (upload, ready, ask, citation, reload, picker, delete, export, erase, markup, sharing) | `web/e2e` | F (fake model, fake embeddings; Postgres + worker real for the knowledge spec) |

### RAG pipeline quality
| Measure | Result |
|---------|--------|
| Live retrieval gate (recall@5 / MRR vs committed baseline, live NVIDIA embeddings + reranker) | pass |
| Live rerank gate (rerank beats RRF on the corpus) | pass (at 20 s timeout; inconclusive at the 6 s default from this network) |
| Grounded answers with verified citations | 21 / 21 agent scenarios and 7 chat scenarios pass; every returned citation resolved to a readable chunk of the caller's base (AGENT-11, SEC-04) |
| Hallucination control (no answer in documents) | AGENT-03, UI-21: no invented figure, no citation |
| Indirect prompt injection (in text, in a filename, instructing cross-tenant search, instructing markdown exfiltration, fake citation markers) | SEC-01..04, AGENT-04: none obeyed |
| Numeric accuracy on tables | live table gate `tools=on`: 8/8 (6 whole-table aggregates + 2 lookups); my 1,500-row total exact (233,932); 3-row xlsx total exact |
| Ingestion latency (live embeddings, batch size 1) | 739 B markdown < 1 s; 60 KB / 40 sections 3 s; 3-page PDF 5.0 s, DOCX 2.7 s, PPTX 2.2 s through docling (warm) |
| Chat latency (live `nemotron-3-ultra` reasoning model) | 13-42 s per answer with retrieval |

## 3. Known coverage gaps

- Live re-index to a different embedding model and dimension (only the repo's fake-provider integration tests ran).
- Scanned/OCR PDFs and very large documents (50 MB, 2,000 pages) with docling; only small, text-layer files were parsed.
- Load, soak and multi-replica behaviour; production TLS/ingress; operator runbooks.
- MCP tools and approvals (outside the Knowledge scope), LangSmith/OpenTelemetry export.
- Non-Chromium browsers, assistive-technology runs; branch coverage for the backend.
- The 85-case live answer gate and the Docker-image layout tests (blocked or too long; see `regression_report.md`).
