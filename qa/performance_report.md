# Performance report: Knowledge (RAG) stack, round 1

Date 2026-11-17. Target: neuron v1.4.0 plus the changes in this branch. Test cases and per-cycle results: `performance_test_scenarios.json` / `.csv` (22 load scenarios and 11 other measurements).

## 1. Verdict

**The API is fast and cheap; the limits are the model providers, not the application.**

- Reads, search and ingestion are not bottlenecked by Postgres (at most 1 to 5 queries active; every table is read through an index) or by memory. One API process is limited by one CPU core.
- Everything that calls NVIDIA is capped by the provider: chat about **40 calls/min**, query embeddings about **20 requests/s**, and the reranker answers in 3 to 13 s, slower than the app's 6 s timeout. These caps, not the code, set the maximum load.
- **Where the bottleneck is:** mainly the LLM provider (chat 40 calls/min, query embeddings about 20/s, reranker slower than our timeout); a paid or dedicated quota raises the first two. In Cycle 1 our own code also made it worse (6 s rerank wait on every search, retries that kept 429s going, three middleware layers using a third of the CPU on reads); those were fixed. Still ours: no throttle on query embeddings (silent keyword-only fallback) and one CPU core per API process for reads. To get more chat capacity, buy a larger provider quota and set `APP_PROVIDER_MAX_REQUESTS_PER_MINUTE` just under it.
- Cycle 1 found that the app made things worse under those caps. Four changes fixed that (section 4); the headline effects are search 6.4 s to 75 ms median, chat success under overload 2 to 21 % to 92 to 100 %, and about 80 % more read throughput per process.
- Of 22 load scenarios, **9 passed in Cycle 1 and 11 pass now**. The 11 that still fail are listed in section 3; most fail their preset latency limit because chat is rate-limited by the provider, not because of errors.

## 2. What was run

| Part | Real service used |
|------|-------------------|
| Chat, embeddings, reranker | NVIDIA catalog (free tier) with the `LLM_*` key: `nemotron-3-ultra-550b-a55b`, `nemotron-3.5-embed-1b`, `nemotron-3.5-rerank-8b`. Nothing was mocked in any load run. |
| Database | Postgres 16 with pgvector 0.8 (Docker), migrations 1-31, 24 knowledge documents (about 1,800 chunks) seeded for the load users |
| API, worker, parser | `uvicorn` (1 process unless stated), `neuron-worker`, docling-serve |
| Identity | repo's stand-in OIDC provider, a token per virtual user (the API's rate limits per user were switched off so that one machine could stand in for many users) |
| Load generator | Locust, on the same 4 vCPU / 16 GB machine as everything else |

The key was never written to a file, log or commit. The Cycle 1 chat runs are included in the token counts below.

## 3. Results

Cycle 1 = original code. Final = Cycle 3. p95 in ms unless marked s.

| Area | Scenario | Cycle 1 | Final |
|------|----------|---------|-------|
| Reads | 100 users | p95 100, 98 req/s | p95 60, 99 req/s |
| Reads | 250 users | p95 320 | **p95 31** |
| Reads | stress 500 users | p95 2.2 s, 223 req/s, knee at about 200 users | **p95 0.8 s, 352 req/s, knee at about 300 users** (no errors) |
| Reads | spike 2 to 250 users | p95 770 | p95 60 |
| Search | 10 users | p95 6.6 s, 1.4 req/s | **p95 94, 9.4 req/s** |
| Search | 25 users | p95 6.5 s, 3.5 req/s | **p95 100, 23 req/s** |
| Search | 100 users | p95 6.9 s, 13.6 req/s | p95 4.1 s, 46 req/s, 4.5 % keyword-only results (see 5) |
| Search, new queries only | 10 / 100 users | p95 6.5 / 6.9 s | p95 5.3 / 3.7 s (see 5) |
| Search | spike 2 to 60 users | p95 7.1 s | **p95 0.67 s** |
| Chat | 1 user | 13 s, 100 % | 13 s, 100 % |
| Chat | 10 users | **21 % success** | **100 % success**, p95 60 s (queued) |
| Chat | 25 users | **0 % success** | 52 % success (the rest time out in the queue) |
| Chat | stress 60 users | 2.4 % success | 92 % success, p95 68 s |
| Chat | spike 2 to 30 users | 5 % success | 100 % success, p95 66 s |
| Soak | 20 users mixed, 10 to 15 min | chat 0 % success | chat 97.8 %, reads and search 100 % |
| Ingestion | 3 users x 4 docs of 80 chunks | 78 docs/min | 78 docs/min (unchanged, not a bottleneck) |

Scenarios still failing their preset limits (11): single-user and 5-user search (the circuit breaker's first three slow searches and one probe every 30 s dominate a tiny sample), all chat scenarios above 1 user (queue wait; provider-bound), the 100/150-user search scenarios (embedding provider limit), unique-query search at 10 users (reranker latency hovering at its timeout), and the soak (chat p95 108 s).

Time to first token: the answer is returned as one structured result, so the first `token` event arrives when the model finishes; TTFT equals total time (about 13 s for a RAG question). Tokens per RAG chat: about 3,200 in and 160 out over two model calls. Provider direct: 15 to 45 output tokens/s, 0.4 to 1.0 s to first token.

## 4. Bottlenecks found and what was changed

| # | Finding (Cycle 1 evidence) | Change | Effect |
|---|-----------------------------|--------|--------|
| 1 | **Every search waited the 6 s rerank timeout.** The reranker answers in 3 to 13 s, so it almost never finished; its result was thrown away each time. Search p50 6.4 s at any load. | Rerank circuit breaker: after 3 failures in a row the search keeps the keyword/vector order for 30 s, then one search at a time probes again. (`knowledge/retrieval.py`) | median 6.4 s to 75 ms; 10 to 25 users scale from 1.4 to 23 req/s |
| 2 | **Retries amplified provider 429s.** At 10 to 60 chat users 79 to 100 % of runs failed; 5,416 retry calls hit a provider that allows 40/min and sends no `Retry-After`, so the window never recovered (the 10-min soak had 0 % success). | Optional `APP_PROVIDER_MAX_REQUESTS_PER_MINUTE`: model calls wait for a slot under the configured rate. Off by default; the eval harness' throttle moved to `models/throttle.py` unchanged. Run at 36. | chat success 2 to 21 % to 92 to 100 % (latency is now queue wait) |
| 3 | **CPU per request.** One process saturated at about 275 req/s (API CPU 100 %); three `BaseHTTPMiddleware` layers cost about a third of the active time. | Rate-limit, correlation-id and security-header middleware rewritten as plain ASGI (same order and headers). `scripts/knowledge_mutations.py` updated for the moved line. | knee 200 to 300 users, 223 to 352 req/s at 500 users; p95 at 250 users 320 to 31 ms |
| 4 | No caching of repeated queries; repeated searches (agent repeats, popular questions) each spent a provider call. | Bounded (256) per-owner query-embedding cache holding hashes and vectors only. Scoped per owner after a security review: a shared cache let one tenant tell from timing that another had asked the same text. | fewer provider calls for repeats; no effect on first-time queries |

Not changed because the evidence did not call for it: ingestion (one embedding request per chunk is slow in theory, but 80 chunks take 2 s), the database (no slow query, no missing index, pool never saturated), the frontend (177 KB gzip, 55 to 74 ms load on localhost, 2 API calls after sign-in).

All changes have tests that fail without them (13 new tests). `make format lint typecheck test security`: 2788 passed, 2 skipped. The 171 functional API scenarios from the functional round pass again (9 failed on the first run through two environment problems, a worker killed when the sandbox froze and chat throttling; all pass on re-run) and 29 browser scenarios pass.

## 5. Capacity and where it breaks

On this machine, one API process, real providers:

| Workload | Sustainable | Breaks at | What breaks |
|----------|-------------|-----------|-------------|
| Reads (list, threads, health) | about 300 users, 350 to 490 req/s | 500 users: p95 0.8 s, still no errors | one CPU core. A second process gave 469 to 716 req/s (+53 %); a third added nothing because the 4-core machine also hosts the load generator and Postgres |
| Search | about 50 users (47 req/s) with p95 100 ms, 100 % correct | 100 users | the embedding provider rejects above about 20 requests/s for new queries; after its retries the search silently falls back to keyword-only ranking, still returns HTTP 200, and in 3 to 5 % of cases misses the right passage. Cycle 1 never showed this only because its 6 s rerank wait kept throughput at 14 req/s |
| Chat (RAG) | **about 18 answers/min, about 4 users who chat continuously** | any higher load | the provider's 40 calls/min (two calls per answer). Above it requests queue; beyond about 120 s they time out. Overload is now graceful, but capacity does not grow with more users |
| Ingestion | 78 docs/min of 80 chunks with 3 users | per-user cap of 5 documents in flight | by design |

Soak: over 15 minutes at 20 users the API's memory rose from 484 to 515 MB (about 2 MB/min, no plateau visible), file descriptors, threads and DB connections stayed flat. This is not proof of no leak; a multi-hour run is needed.

## 6. Open findings and recommendations

1. **Silent quality loss under embedding throttling (new, highest impact).** Searches above about 20 new queries/s degrade to keyword-only with status 200. Throttle query embeddings like model calls (the same `RequestThrottle`), or flag degraded results in the response.
2. **Reranker.** At 3 to 13 s from this network it adds nothing and sometimes costs 6 s. Either raise the timeout, run it only on request, or measure from the real deployment region first. The breaker does not help when the latency sits just under the timeout: the circuit keeps closing (visible in the 10-user unique-query scenario, p95 5.3 s).
3. **Chat capacity** needs a paid or dedicated provider quota; set `APP_PROVIDER_MAX_REQUESTS_PER_MINUTE` just under it and divide it among replicas (each process counts its own calls). Consider a bounded queue that answers "busy" earlier than the 120 s run timeout.
4. **Token use.** About 3,200 input tokens per answer for a one-line question (system prompt and tool definitions); prompt trimming would cut cost and latency, but was not attempted because it can change answer quality.
5. **Streaming.** The answer arrives in one piece at the end; users see nothing for about 13 s.
6. Scale API replicas for reads (at least 2 processes per 4 cores), keep one worker, and give Postgres its own host before judging the API's ceiling.

## 7. Cost

All provider calls used NVIDIA's free catalog, so **nothing was billed (0 USD)**. Real consumption, from the API's own run logs (failed runs counted): chat 2,154 runs, 379 k input / 21.7 k output tokens in Cycle 1; 238 runs, 536 k / 28 k in Cycle 2; 519 runs, 1.66 M / 83 k in Cycle 3 (about 2.6 M tokens in total, 1.1 M of them in the two soaks). A typical RAG answer is 3.2 k in plus 160 out tokens. Embedding calls are not metered in the logs. At any price P_in and P_out per million tokens, one answer costs 0.0032 x P_in + 0.00016 x P_out, and a sustained 18 answers/min is 1,080 answers/hour.

## 8. How far to trust the numbers

- One 4 vCPU machine ran the API, Postgres, worker, docling and the load generator. Absolute throughput is therefore a lower bound for the API and says nothing about multiple hosts or a real network.
- The providers are a free tier with variable latency. A first Cycle 2b search run (15 to 33 s tails) coincided with embedding timeouts and 429s in the API log and was discarded; it was re-run and the first attempt is not in the table. The reranker's latency also changed over the day (5 to 13 s), which is why Cycle 2 and Cycle 3 differ for the 10-user search scenarios.
- Baseline scenarios with one or a few users have 3 to 18 samples; their p95 is the maximum. The 35 s p95 of the single-user chat in Cycle 2 was one slow call in three samples and did not recur.
- Two scenarios (unique-query search) were added after Cycle 1, so their baseline was measured against the original code in a separate checkout; the same API ran in Cycles 1 and 3.
- Thresholds were fixed before measuring for the 22 load scenarios, after the first probe for the other 11.
- My own probes of the providers (rate limits, direct calls) used part of the same quota just before some runs; the start of the first Cycle 1 soak was affected.
- Not run: multi-replica, multi-hour soak, real-network frontend, more than 60 simultaneous chat users, production hardware, billing-tier providers.
