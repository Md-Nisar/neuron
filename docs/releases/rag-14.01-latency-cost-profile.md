# RAG-14.01: latency and cost profile per answer

Date: 2026-11-28. Story #662, epic RAG-E14 (#659). Not a release: this records the profile and
proposes the budget the owner agrees.

## How it was measured

- **Run:** the hard-question baseline of RAG-13.02 (`tests/integration/test_live_knowledge_hard.py`,
  72 cases, three trials, 213 finished answers), on the local reference stack: Postgres 16 with
  pgvector 0.8.0 on the session host, one knowledge base of 628 documents.
- **Models (NVIDIA free tier):** chat `nvidia/nemotron-3-ultra-550b-a55b`, embedding
  `nvidia/nemotron-3.5-embed-1b`, reranker `nvidia/nemotron-3.5-rerank-8b`.
- **Spans:** every answer's spans went to `APP_KNOWLEDGE_EVAL_SPANS`, and the report is
  `uv run python scripts/knowledge_profile.py SPANS.jsonl`.
  - Each search stage is now a child span `neuron.knowledge.search.<stage>`: embed, fts, dense,
    fuse, passages, rerank.
  - The citation check is `neuron.citations.validate`, with kept and rejected counts.
  - Model turns and tool calls already had spans (`chat {model}`, `execute_tool {tool}`).
- **Privacy:** the span file and the report keep only ids, names, durations and the
  allow-listed attributes (`KEPT` in the script): no query, passage, answer or title.
  `tests/unit/test_knowledge_profile.py` checks this, and the collector allowlist
  (`deploy/observability/otel-collector.yaml`) has the three new attributes.
- **Failed answers left out:** 45 answer attempts failed, all from the provider's rate limit
  except one structured-output error. Run 1 recorded its spans before an answer span carried
  `error.type`, so its failed traces were dropped by hand: a trace counts as finished only if
  it has a citation-check span. That leaves exactly the 213 runs the report scores.

**Caveats:**

- A model turn's span covers the eval's throttle (a sliding window of 20 calls a minute) and
  the provider retries. The agent averaged about 11 calls a minute, so the throttle rarely
  waited, but the p95 includes retries after the free tier's 429s.
- These are free-tier and single-host figures, not a production deployment.

## Profile

213 answers; 365 searches (1.7 per answer); 601 model turns.

| Stage | Spans | p50 ms | p95 ms | Mean ms |
| --- | ---: | ---: | ---: | ---: |
| answer (whole run) | 213 | 14,110 | 40,476 | 17,514 |
| model turn | 601 | 3,944 | 14,731 | 5,520 |
| tool call | 445 | 876 | 3,194 | 1,061 |
| search (whole) | 365 | 925 | 3,672 | 1,287 |
| search.embed (query) | 365 | 387 | 449 | 275 |
| search.fts | 365 | 1.4 | 3.5 | 1.6 |
| search.dense | 365 | 23 | 42 | 27 |
| search.fuse | 365 | 0.1 | 0.2 | 0.2 |
| search.passages | 365 | 1.9 | 3.5 | 2.1 |
| search.rerank | 365 | 526 | 3,344 | 974 |
| citation check | 213 | 0.1 | 0.1 | 0.1 |

| Per answer | p50 | p95 | Mean |
| --- | ---: | ---: | ---: |
| model turns | 2 | 6 | 2.8 |
| input tokens | 5,125 | 28,411 | 8,189 |
| output tokens | 512 | 1,414 | 631 |

The search embed mean (275 ms) is below its p50 because a repeated query's embedding is
served from the owner-scoped query cache (under 5 ms, 64 of 414 embed spans). Most of those
hits are trials 2 and 3 asking the same question again, so production would see fewer.

## Where the time and tokens go

- **Model turns are most of an answer.** A mean of 2.8 turns at a mean of 5.5 s is about
  15.5 s of the 17.5 s mean answer, about 88%. Searches are about 2.2 s an answer (1.7 at
  1.3 s), about 13%. Everything else is noise.
- **Inside a search, the hosted calls are the whole cost.** The reranker is 57% of the p50 and
  most of the tail: its p95 is 6.4 times its p50. The query embedding is 42% of the p50.
  Postgres (full text, dense, fusion, passages) is under 30 ms at p50 and under 50 ms at p95
  at this size; RAG-14.02 checks it at 1M and 5M chunks.
- **Input tokens grow with turns.** Each turn resends the conversation and the search results,
  so a 6-turn answer costs about five times a 2-turn one (p95 28k against p50 5k). Output is
  small. Cost is mostly input tokens, and it follows the number of searches and turns.

## Proposed budget (for the owner to agree)

Budgets are p95 targets on the reference stack. A stage over its budget is a candidate for
RAG-14.05 and RAG-14.06; "Now" is today's p95.

| Stage | Now (p95) | Proposed budget (p95) | Note |
| --- | ---: | ---: | --- |
| query embedding | 449 ms | 500 ms | within |
| full text + dense + fusion + passages | ~50 ms | 150 ms | within; RAG-14.02 re-checks at scale |
| rerank | 3,344 ms | 1,500 ms | **over**: the largest search stage and the tail |
| whole search | 3,672 ms | 2,000 ms | over, because of the reranker |
| citation check | 0.1 ms | 5 ms | within |
| model turn | 14.7 s | 15 s | within, and bound by the provider |
| answer | 40.5 s | 45 s | within |
| model turns per answer | 6 | 6 | within |
| input tokens per answer | 28.4k | 30k | within; the first to move as RAG-13.04 adds searches |
| output tokens per answer | 1.4k | 2k | within |

**The proposal in short:**

- **Rerank is the one stage over budget.** Its long tail is the free tier's variance, not our
  code. The reranker timeout is 15 s today, so a 1.5 s budget means either a lower timeout,
  with RRF order as the fallback (it already is on a timeout), or a self-hosted reranker.
  RAG-14.05 should measure the quality cost of the fallback before choosing.
- **Any RAG-13 story that adds searches or turns** (RAG-13.03 and RAG-13.04) must report its
  change to tokens and turns per answer against this table.

## Reproduce

```bash
export APP_TEST_POSTGRES_DSN=postgresql://postgres:postgres@127.0.0.1:5432/postgres \
  APP_DEFAULT_MODEL=nvidia:nvidia/nemotron-3-ultra-550b-a55b \
  APP_KNOWLEDGE_EVAL_SPANS=spans.jsonl APP_KNOWLEDGE_EVAL_RUNS=runs.jsonl \
  APP_KNOWLEDGE_EVAL_REPORT=report.json APP_KNOWLEDGE_HARD_VECTORS=vectors.json.gz
uv run python -m pytest tests/integration/test_live_knowledge_hard.py -m integration \
  -o faulthandler_timeout=36000
uv run python scripts/knowledge_profile.py spans.jsonl
```

The free tier rate-limited the first full run, so the run was finished by resuming from the
saved runs file. It took about 8 hours in all.
