# RAG-13.02: baseline and failure analysis on hard questions

Date: 2026-11-28. Story #661, epic RAG-E13 (#658). Not a release: this records where today's
system fails on hard questions and why, and recommends an order for RAG-13.03 to RAG-13.06.
The owner picks which start.

## How it was measured

- **Set:** the RAG-13.01 hard set (`tests/fixtures/knowledge/hard/`, version 1.0.0): 72 cases
  from MuSiQue, 2WikiMultihopQA, FRAMES, MTRAG and ClapNQ over 628 documents, parsed and
  chunked as ingestion does, in one knowledge base.
- **Harness:** `tests/integration/test_live_knowledge_hard.py`. Live and billed, not a gate.
- **Models (NVIDIA free tier):** chat `nvidia/nemotron-3-ultra-550b-a55b`, embedding
  `nvidia/nemotron-3.5-embed-1b`, reranker `nvidia/nemotron-3.5-rerank-8b`. The chat model
  earlier in the plan (`nemotron-3-super-120b`) reached end of life on 2026-10-03, and this is
  the only NVIDIA reranker still served.
- **Retrieval:** every question is searched as the knowledge tool searches (hybrid, reranker
  on), 50 deep.
  - *Complete recall@k:* every required source is in the top k.
  - *MRR:* the first source found.
  - A follow-up is also searched by its benchmark's human-written standalone rewrite.
- **Answers:** asked through `AgentService` three times (three trials); a follow-up's thread
  starts with its earlier turns.
  - Short answers (MuSiQue, 2WikiMultihopQA, FRAMES) are graded by `grade_answer` against the
    benchmark answer and its aliases; only a perfect grade counts as correct.
  - A long-form answer (MTRAG, ClapNQ) counts as correct when it cites a passage holding a
    required source.
  - An unanswerable case is correct only if the agent abstains.
- **Failure classes** (`classify_failure` in `src/neuron_agent/retrieval_metrics.py`), checked
  in this order:
  1. The agent's own searches returned every required source: *false abstention* if it
     abstained, else *synthesis*.
  2. The standalone rewrite has every source in the top 5 and the raw question does not:
     *follow-up not resolved*.
  3. Every source is somewhere in the 50: *ranking*.
  4. Otherwise: *retrieval miss*.
- **Runs:** 216 planned, 213 scored; 3 infrastructure errors (2 rate limits, 1
  structured-output error) are recorded, not scored.
  - The free tier rate-limited the first full run, so the harness was made to resume from a
    file of finished runs (`APP_KNOWLEDGE_EVAL_RUNS`).
  - No search fell back (no degraded searches).
- **Privacy:** reports hold case ids and metrics only.

## Retrieval

| Category | Cases | Complete recall@5 | Complete recall@10 | MRR | Any source @5 |
| --- | ---: | ---: | ---: | ---: | ---: |
| multi_hop | 15 | 0.467 | 0.467 | 0.967 | 1.000 |
| comparison | 12 | 0.583 | 0.667 | 1.000 | 1.000 |
| synthesis | 10 | 0.600 | 1.000 | 1.000 | 1.000 |
| follow_up | 15 | 0.600 | 0.667 | 0.724 | 0.933 |
| vocabulary_mismatch | 10 | 1.000 | 1.000 | 0.742 | 1.000 |

**What the retrieval numbers show:**

- **Finding the first source is not the problem; finding all of them is.** MRR is high
  everywhere but follow-ups and vocabulary mismatch.
- **Multi-hop misses its second hop.** The first hop is in the top 5 in every case, but
  complete recall stays at 0.467 even at 10. MuSiQue builds its questions so that the second
  hop is named only by the first hop's answer, so one query cannot reach it.
- **Synthesis and comparison miss on depth.** All of a synthesis case's articles are in the
  top 10, but only 60% are in the top 5.
- **Follow-up rewriting gains nothing.** The human-written standalone rewrite reaches the same
  complete recall@5 (0.600) as the raw follow-up question.

## Answers (three trials)

| Category | Runs | Correct | Abstained | Saw all sources | p50 s |
| --- | ---: | ---: | ---: | ---: | ---: |
| multi_hop | 44 | 0.523 | 0.364 | 0.409 | 18.0 |
| comparison | 36 | 1.000 | 0.000 | 1.000 | 12.2 |
| synthesis | 29 | 0.586 | 0.069 | 0.724 | 14.6 |
| follow_up | 44 | 0.750 | 0.159 | 0.636 | 14.9 |
| vocabulary_mismatch | 30 | 0.933 | 0.000 | 0.967 | 12.0 |
| unanswerable | 30 | 0.733 | 0.733 | — | 16.7 |

"Saw all sources" means the agent's own searches, across all its turns, returned every
required source.

**Comparison holds** even with complete recall@5 at 0.583, because the agent's own searches
found every source in every run (saw all sources 1.0). A comparison names both of its
entities, so separate searches find what one search's top 5 misses. A multi-hop question does
not name its second hop, so the agent's searches find it in only 41% of runs.

**Consistency across trials:**

| Category | Cases failed in all trials | In some trials | In none |
| --- | ---: | ---: | ---: |
| multi_hop | 6 | 2 | 7 |
| synthesis | 3 | 2 | 5 |
| follow_up | 3 | 2 | 10 |
| unanswerable | 2 | 2 | 6 |
| vocabulary_mismatch | 0 | 2 | 8 |
| comparison | 0 | 0 | 12 |

Most failures repeat, so they come from the system rather than from sampling.

## Failure classification

There were 54 wrong runs. The 46 answerable ones fall into the five classes; the other 8 are
unanswerable cases that answered, a failure outside the five classes.

| Class | Runs | Categories | Story that addresses it |
| --- | ---: | --- | --- |
| retrieval miss | 14 | multi_hop 14 | RAG-13.04 (decomposition); RAG-13.05 in part |
| ranking | 12 | synthesis 5, multi_hop 4, follow_up 2, vocabulary 1 | RAG-13.06, RAG-13.04 |
| false abstention | 11 | follow_up 7, multi_hop 3, synthesis 1 | none (see below) |
| synthesis | 7 | synthesis 6, vocabulary 1 | RAG-13.06 |
| follow-up not resolved | 2 | follow_up 2 | RAG-13.03 |
| answered an unanswerable question | 8 | unanswerable 8 | none (see below) |

**Abstention is wrong in both directions: 19 runs of the 54.**

- In every one of the 11 false abstentions, the agent's searches had returned all the
  evidence. None was a step limit, and none cited anything.
- 8 unanswerable runs gave an answer instead of abstaining.

So the threshold the model applies to "the evidence answers this" is miscalibrated on hard
questions. No RAG-13 story covers it. It belongs to the prompt and the grounding check, and
would be a new story if the owner wants it.

## Recommended order for RAG-13.03 to RAG-13.06

1. **RAG-13.04, multi-query and decomposition. Start.**
   - It addresses the largest class: 14 retrieval misses, all multi-hop, plus most of the
     multi-hop ranking failures.
   - The comparison category suggests that more than one query works when each query names
     what it needs: its searches saw every source in every run.
   - **Target:** multi-hop complete recall@5 from 0.467, and correct from 0.523.
   - **Cost:** more searches and input tokens per answer, to report against the RAG-14.01
     budget (input tokens p95 28.4k against a proposed 30k).
2. **RAG-13.06, context assembly for synthesis. Start after 13.04.**
   - It addresses 12 ranking and 7 synthesis failures: the sources are within 10 (synthesis
     complete recall@10 is 1.0) but not within 5, and the model sees them in pieces.
   - **Target:** synthesis correct from 0.586.
3. **RAG-13.05, contextual chunk enrichment. Hold.**
   - Vocabulary mismatch is already 0.933 correct with complete recall@5 of 1.0, so the hard
     set gives it little to gain.
   - Re-measure once RAG-13.04 shows how much of the multi-hop second-hop miss is left. Titles
     in the chunk text might help there.
4. **RAG-13.03, follow-up rewriting. Do not start.**
   - Only 2 runs failed on resolution, and the human-written standalone rewrite gains no
     complete recall@5 (0.600 against 0.600).
   - Follow-ups fail by false abstention (7 runs) with the evidence in hand, which rewriting
     cannot fix.

**Outside RAG-13.03 to RAG-13.06:**

- An abstention-calibration story (19 runs, both directions) would rank second by size.
- RAG-11.05 (plan-and-verify subgraph), which waited on these multi-hop numbers, should wait
  for RAG-13.04's result: a bounded decomposition inside the tool may be enough.

## Reproduce

See `docs/releases/rag-14.01-latency-cost-profile.md`, "Reproduce": the same run writes
`APP_KNOWLEDGE_EVAL_REPORT`, the source of every table here.
