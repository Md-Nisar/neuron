# Knowledge system review (summary)

**Date:** 2026-11-19 · **Code:** `main` at `fc9065a` · **Scope:** `src/neuron_agent/knowledge/` (21 modules), its agent integration (`graphs/main_graph.py`), the knowledge schema (`persistence/migrations.py`), ADR 0014 and its amendments, the RAG tracker and the release evidence.

**Method:** code reading, the knowledge unit and security tests (635 passed), and the recorded baselines. The Postgres integration suites and the live-model evals were not re-run for this review; their figures come from `evals/baselines/`, `docs/releases/` and `qa/`. This is an assessment, not a certification: nothing here has run in a production environment.

## Verdict

**Developing, at the upper end.** Overall maturity **7.1 / 10**. The design, security and retrieval engineering are at production level. What is missing is operational evidence: Neuron has never been deployed. The review found no defect that blocks a first production deployment. It found one gap worth closing first: the knowledge path could lose quality without any alert. This pull request closes it (see "Changes in this pull request").

## Ratings

| Area | Rating | Basis |
|---|---|---|
| Architecture and design | 8.0 | One Postgres for storage, queue and permissions (ADR 0014 K1); import boundaries enforced by `test_knowledge_boundaries.py`; every extension recorded as an ADR amendment. The reranker's circuit breaker and the query-embedding cache are per process. |
| Sources, ingestion, parsing | 7.5 | PDF, Office, text, Markdown, CSV and web pages. The real file type is sniffed from its bytes. Encrypted PDFs, macro files and archives are refused, and zip bombs are bounded (`parsing.py`). Docling runs in its own process with no egress. Jobs are durable and idempotent (`ingest.py`, `reconcile.py`, `purge.py`). Web pages are fetched once and never refreshed. |
| Chunking, embeddings, indexing | 7.0 | Chunks follow the document's headings, and the heading path is embedded with the text (`chunking.py`, `ingest.py:445`). halfvec storage, one HNSW index per index profile, re-index without downtime. Token counts are estimated, chunks do not overlap, and one chunk size serves every kind of content. |
| Retrieval and ranking | 8.5 | Authorization is applied before ranking, in SQL, and row-level security repeats it. Dense and full-text candidates are fused with RRF, then reranked behind a circuit breaker (`retrieval.py`). Recall@5 0.984; MRR 0.833, or 0.977 reranked. In practice there is no relevance floor (`min_similarity` 0.0, measured as not separating unanswerable questions), and no per-document diversity. |
| Pipeline and context | 6.5 | Tool output is framed and capped: 6,000 characters per call, 5 searches and 10 excerpts per run. A repeated search is refused. Nothing budgets the run as a whole, and passages do not carry over to the next turn. |
| Grounding and citations | 8.0 | `cite_id`s are minted by the server and validated per run (`citations.py`). An abstaining answer drops its citations in code. The live eval scored `cited_correctly` 1.0 and 12 of 12 abstentions with the reranker. Nothing checks that a cited passage supports the claim, and the eval set is small (31 documents, 76 cases). |
| Freshness, versioning, scale | 6.5 | Duplicates are found by SHA-256, files are set once, re-index swaps profiles, and per-user quotas apply. Synthetic benchmark at 300,000 chunks (`qa/retrieval_scale_benchmark.md`): HNSW recall@10 0.94, and hybrid p95 0.25 s after migration 33. There are no document versions and no web refresh. |
| Permissions, security, privacy, memory | 8.5 | Identity comes only from the trusted context. Grants are per base, by owner and by role, re-read in each transaction. Row-level security on chunks, embeddings and tables. Processing locality per base. Retrieved text taints the run. Erasure covers knowledge. Telemetry carries no content. `documents` relies on application filters, and there is no PII scan. |
| Agent integration and tools | 7.5 | Five read-only, scoped tools with per-run caps and fixed error texts. The table SQL runs in a SQLite sandbox. The model sometimes answers a table question from search without calling `find_tables` (a known issue). |
| Operations, performance, cost | 7.0 → 8.0 | Stable error codes, spans and metrics, and per-document embedding tokens. Before this pull request, one knowledge alert (queue stuck) and silent degradation. |
| Testing, eval, docs | 8.0 | 30 Postgres integration files, a retrieval baseline gate, live answer and rerank evals, an injection suite, and runbooks covered by tests. Live evals are run by hand. |
| Production readiness | 4.5 | Never deployed; all evidence is local. |

## Top strengths

1. Server-validated citations, so the model cannot invent a source.
2. Authorization before ranking, in the same transaction, repeated by row-level security.
3. Hybrid search, fused with RRF and reranked, with a measured MRR of 0.977.
4. Hostile-file defences, with parsing out of process and without network access.
5. A durable, idempotent ingest pipeline with drift reconciliation.
6. Processing locality enforced for embedding, query embedding and reranking.
7. Re-indexing to a new embedding model without downtime.
8. Retrieved content is framed as data and taints the run.
9. A measured scale path, with its full-text bottleneck already fixed (migration 33).
10. Decision records, release evidence and runbooks that are kept current.

## Risks for a first production deployment

| Risk | Level | Handling |
|---|---|---|
| Embedder or reranker outage lowers answer quality while every search still succeeds | Medium-high | **Fixed here:** `neuron.knowledge.search.degraded` metric and `NeuronKnowledgeSearchDegraded` alert |
| Knowledge search failing or slow, or ingestion failing, with no alert | Medium | **Fixed here:** three alerts and two runbooks |
| Abstention depends on the reranker and the chat model | Medium | Deploy the configuration that was measured: the reranker on, the same chat model (operator checklist) |
| Citations are valid but do not support the claim | Medium | Wait: measure with real feedback first |
| Stale web pages, no document versions | Medium | Wait for a product need |
| Breaker and cache per process | Low | Wait: each replica only learns on its own |

## Changes in this pull request

**Code and configuration**
- `neuron.knowledge.search.degraded` (counter): one count per search that succeeded without its dense path (`dense_skipped`) or its reranker (`rerank_skipped`), with the stable `error.type`. These were logged only.
- Four alerts in `deploy/observability/prometheus-alerts.yaml`, with runbooks in `OPERATIONS.md`:

  | Alert | Fires when | Severity |
  |---|---|---|
  | `NeuronKnowledgeSearchErrors` | errors above 5% of searches, and 0.01/s, for 15 minutes | page |
  | `NeuronKnowledgeSearchSlow` | search p95 above 5 s for 15 minutes; the reranker's measured p95 is 3.8 s and its timeout 6 s | ticket |
  | `NeuronKnowledgeSearchDegraded` | over 10% of searches skipped the embedder or reranker for 15 minutes; locality refusals are configuration and left out | ticket |
  | `NeuronKnowledgeIngestFailing` | over 25% of finished ingestions failed in an hour, with at least 5 failures | ticket |

**Tests**
- Each rerank skip is counted with its code: provider error, timeout, and an open circuit.
- The counter carries only `neuron.outcome` and `error.type`.
- A hybrid search whose provider is down is counted as `dense_skipped` (Postgres integration test).
- The alert expressions read the metric names, outcomes and bucket bounds the code records.

The thresholds are provisional, like the existing rejection alerts. Retune them after the first weeks of traffic.

**Retest**
- `promtool check rules` passed (58 rules), and `otelcol-contrib validate` passed.
- A one-off `promtool test rules` run, not committed, confirmed two things:
  - all four alerts fire on synthetic failure series;
  - none fires on healthy traffic, or when the only skips are locality refusals.

## Operator checklist before the first deployment (no code)

- Leave the reranker on. `APP_KNOWLEDGE_RERANKER` unset already means `nvidia` when NVIDIA embeddings and a key are configured. Use the chat model the live eval measured.
- Configure the blob bucket with encryption at rest and public access blocked (`blobs.py`). The operator owns this.
- Set the processing policy to what users are told about where their data is processed.
- Set production values for the per-user quotas (`APP_KNOWLEDGE_MAX_*`).
- Restore a Postgres backup once before launch.
- Rotate the NVIDIA key, if that is still pending.
- Route the new `page` alert to the on-call channel, and `ticket` alerts to the queue.
- Start with a small group of users, and watch the alerts for one to two weeks.

## Deferred until production data shows a need

| Item | Trigger to start it |
|---|---|
| Relevance floor based on the reranker score | Real "the documents do not have it" cases that the model answers anyway |
| Checking that citations support their claims | 👎 feedback on cited answers |
| Larger eval set (300+ cases, repeated trials) | Build it from real questions |
| Document versions, scheduled web refresh | A user asks for updates to their documents |
| Run-wide context budget | Context-length errors; today 5 × 6,000 characters is about 8,000 tokens |
| Row-level security on `documents` | Defence in depth, at the next schema change to that table |
| Shared circuit breaker and cache | Several API replicas, with uneven reranker behaviour between them |
| Chunk overlap, query rewriting, multi-hop | An eval that shows the failure (recall@5 is 0.984 today) |
