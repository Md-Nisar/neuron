# Knowledge retrieval at scale: benchmark (2026-11-18)

**Status:** Finding 1 is fixed by migration 33 (`knowledge.search_text`); see "After the fix" below.

Local benchmark on synthetic data. It is not a production measurement and is not a gate.

## Setup

- **Database:** `pgvector/pgvector:pg16` in Docker (pgvector 0.8.7, the CI image), on 4 vCPUs and 15 GB RAM. The benchmark client ran on the same machine.
- **Postgres settings:** `shared_buffers=2GB`, `work_mem=16MB`, `maintenance_work_mem=1800MB` for the migrator role.
- **Schema:** every migration, applied by `run_setup` as a migrator role. Searches run as a separate app role, so row-level security applies, as in production.
- **Code path:** the real `Retriever.search` (`allowed_kbs`, `SET LOCAL neuron.kb_ids`, the choice between exact scan and HNSW, full text, RRF), with `k=10`, no reranker, and default settings (`knowledge_exact_scan_max_chunks=10000`, `hnsw.ef_search=100`). Query vectors were precomputed, so no embedding provider was called.
- **Corpus:** three bases, each owned by a different user:

  | Base | Chunks | Path it exercises |
  |---|---|---|
  | small | 2,000 | exact scan |
  | mid | 20,000 | HNSW, filtered to part of the table |
  | big | the rest | HNSW over most of the table |

  Every document has 50 chunks.
- **Vectors:** 1,024 dimensions, stored as halfvec, clustered around 2,000 topics plus a shared direction.
- **Text:** 300 Zipf-distributed words per chunk, using English function words plus synthetic terms, under the `simple` config.
- **Queries:** 40 per base, each near a random chunk of that base. Each query's text is a 3-word phrase from that chunk, so every text search has matches. A separate run searched the single word `the`, the worst full-text case.
- **Recall@10:** the HNSW top 10 compared with the app's own exact scan of the same base.
- **Reproduce:** `scripts/knowledge_scale_bench.py` (`load`, `index`, `bench`).

## Results

All figures are latencies of `Retriever.search`, one client at a time unless stated. Each cell is p50 / p95 in milliseconds.

### 100,000 chunks (big base: 78,000)

| Base | Dense | Full text | Hybrid (default) | Full text, `the` | Exact scan forced | Recall@10 |
|---|---|---|---|---|---|---|
| small (2k, exact) | 24 / 41 | 12 / 23 | 41 / 71 | 21 / 29 | 29 / 40 | 1.00 |
| mid (20k, HNSW) | 16 / 26 | 67 / 167 | 92 / 211 | 134 / 183 | 142 / 168 | 1.00 |
| big (78k, HNSW) | 12 / 19 | **280 / 762** | **405 / 978** | 616 / 768 | 430 / 480 | 0.975 |

With 8 hybrid searches in flight: 17.3 searches/s, p50 246 ms, p95 1,406 ms, max 2.4 s.

### 300,000 chunks (big base: 278,000)

| Base | Dense | Full text | Hybrid (default) | Full text, `the` | Exact scan forced | Recall@10 |
|---|---|---|---|---|---|---|
| small (2k, exact) | 26 / 43 | 9 / 21 | 30 / 43 | 18 / 22 | 23 / 26 | 1.00 |
| mid (20k, HNSW) | 23 / 37 | 77 / 201 | 107 / 230 | 140 / 177 | 179 / 243 | 0.975 |
| big (278k, HNSW) | 14 / 20 | **1,066 / 3,621** | **1,540 / 3,890** | 2,267 / 2,818 | 1,707 / 1,954 | 0.94 |

With 8 hybrid searches in flight: 5.8 searches/s, p50 278 ms, **p95 4.6 s, max 14.9 s**.

### Index build and load

- **HNSW build** through `run_setup`, the same path an upgrade uses: 18 s at 100,000 vectors and 52 s at 300,000.
- **Loading with the HNSW index in place** (the worker's normal path): about 3.3 ms per chunk. That is 100,000 chunks in 5.5 minutes. Without the index, the same load ran about 5 times faster.
- **Database size:** about 1.1 GB at 100,000 chunks and 3.3 GB at 300,000, or about 11 KB per chunk.

## Findings

### 1. Verified: full-text search scans every chunk of the bases it searches, because RLS stops it from using the GIN index

**Severity: High for large bases.**

The full-text candidate query filters on `c.tsv @@ websearch_to_tsquery(...)`. The `@@` operator (`ts_match_vq`) is not `LEAKPROOF`. On a table with row-level security, Postgres must apply the policy before any non-leakproof qual from the query. So it cannot use that qual as an index condition, and `chunks_tsv_idx` is never used for the app role.

The plan for the app role is always an index scan of every chunk in the allowed bases via `chunks_kb_idx`, with `@@` checked row by row. Each row also has its TOASTed `tsvector` read.

Evidence: the same query on the 278,000-chunk base, as the app role and as a superuser (who bypasses RLS):

| Query | App role (RLS) | Superuser (no RLS) |
|---|---|---|
| `zebra t39999` (rare words, 0 matches), at 78,000 chunks | 249 ms, every chunk read | 0.3 ms, GIN |
| `of t00123 his` (about 23,000 matches), at 278,000 chunks | 1,127 ms | 313 ms, GIN |

Consequences:

- Full-text and hybrid latency grow linearly with the size of the searched bases, even for a query that matches nothing. A 278,000-chunk base gives a hybrid p95 of 3.9 s, and 8 concurrent searches reach a p95 of 4.6 s and a maximum of 14.9 s. A base of 1,000,000 chunks would take several seconds per search. The default limits allow that size: 20,000 chunks per document.
- Dense search is not affected. The HNSW and exact-scan paths stay fast.
- This is a performance finding only. Isolation still holds: the explicit `allowed_kbs` filter and the RLS policy both apply.

Fix options. Each one touches the RLS design (ADR 0014), so each needs your decision and a security review.

| Option | What it does | Trade-off |
|---|---|---|
| a | Make the full-text candidate query use the index without weakening the policy. One way: a `LEAKPROOF` SQL wrapper around `@@`, used only in that query, created by an operator superuser step. | Needs a superuser, and a judgement that `ts_match_vq` cannot leak through its errors. |
| b | Run the full-text candidate query (ids only) in a `SECURITY DEFINER` function owned by the migrator. It filters on the explicit `kb_ids` it is given; passages are still read under RLS. | RLS no longer double-checks that one query. The SQL filter remains. |
| c | Keep RLS as it is and cap the cost: a `statement_timeout` on the full-text query, with hybrid falling back to dense-only on timeout, as it already does when the embedding provider is down. | Hides the problem rather than fixing it. Simplest to do. |

Even with the index, a phrase made only of very common words matches a large share of chunks and is ranked one row at a time (313 ms for 23,000 matches). That case is smaller, and a stop-word-aware `ts_config` per base helps it.

### 2. Measured: dense search scales well; HNSW recall is 0.94 to 0.975

- HNSW search costs 12 to 23 ms at p50 and stays roughly flat from 100,000 to 300,000 vectors.
- Recall@10 against the exact scan is 1.00 for the 20,000-chunk base at 100,000 chunks, 0.975 for that base at 300,000 and for the big base at 100,000, and 0.94 for the 278,000-chunk base. All of this is at `ef_search=100`.
- The exact scan forced on large bases costs 0.4 to 1.7 s, which supports the 10,000-chunk threshold.
- Recall on real embeddings will differ from these synthetic clusters. Measure it again on a real corpus before tuning `ef_search`.

### 3. Measured: ingestion slows when HNSW is maintained during inserts

- About 3.3 ms per chunk with the index in place, against about 0.55 ms without it.
- One 20,000-chunk document spends about a minute on index inserts.
- No action is needed at current volumes. A bulk import or a re-index of a large corpus would benefit from building the index after the load, as `run_setup` already does on a rebuild.

## After the fix (migration 33)

Full-text candidates now come from `knowledge.search_text`. It is a `SECURITY DEFINER` function owned by the migrator, so `kb_scope` does not bind it. It applies the policy's own `neuron.kb_ids` filter as a plain condition, which lets `chunks_tsv_idx` serve the match, and returns chunk ids only. Passages are still read under RLS.

It ranks at most 10,000 matches. Without that cap, a phrase made only of common words (for example `of that the`) still took up to 4.5 s, because it matches nearly every chunk and every match was ranked. With the cap, the slowest phrase in the query set takes 274 ms.

Same corpus, same queries, 300,000 chunks, warm cache (p50 / p95 ms):

| Base | Full text, before | Full text, after | Hybrid, before | Hybrid, after | Full text `the`, before | Full text `the`, after |
|---|---|---|---|---|---|---|
| small (2k) | 9 / 21 | 10 / 23 | 30 / 43 | 39 / 56 | 18 / 22 | 19 / 27 |
| mid (20k) | 77 / 201 | 82 / 152 | 107 / 230 | 98 / 185 | 140 / 177 | 99 / 108 |
| big (278k) | 1,066 / 3,621 | **19 / 229** | 1,540 / 3,890 | **29 / 252** | 2,267 / 2,818 | **88 / 111** |

With 8 hybrid searches in flight:

| | Searches/s | p50 | p95 | Max |
|---|---|---|---|---|
| Before | 5.8 | 278 ms | 4.6 s | 14.9 s |
| After | **19.7** | 247 ms | **0.94 s** | **2.3 s** |

Dense search and recall are unchanged. The small and mid bases change within run-to-run noise.

Trade-off: for a query that matches more than 10,000 chunks, the text ranking draws on an arbitrary 10,000 of them. Such a query is mostly common words, so its text ranking says little anyway. In hybrid mode, dense search still covers the whole base.

Tests:

- `tests/integration/test_postgres_knowledge_search.py` checks three things:
  - The function's query uses `chunks_tsv_idx`, which the same query under RLS cannot.
  - The function returns nothing outside the transaction's `neuron.kb_ids`, even for bases passed to it, and nothing at all when the scope is unset.
  - Only the app role may run it, and it is hardened: `SECURITY DEFINER`, pinned `search_path`, no PUBLIC.
- All 319 Postgres integration tests pass on pgvector 0.8.7.

## Limits of this benchmark

- The data is synthetic. Real embeddings, real prose, other languages and `ts_config` values will shift the numbers, though not the cause of Finding 1, which comes from the query plan.
- Everything ran on one 4-vCPU machine with the client on the same host, using local Docker storage.
- No reranker, no embedding provider latency, and no API or HTTP overhead. These are `Retriever.search` times only.
- 1,000,000 chunks was not run, because the disk could not hold about 11 GB plus WAL. The linear trend in Finding 1 is clear from 78,000 to 278,000 chunks.
