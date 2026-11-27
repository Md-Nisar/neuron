# Hard-question eval set (RAG-13.01)

Questions the main eval set (`tests/fixtures/knowledge_cases.json`) does not ask: they need
several passages, several documents, the earlier turns of a conversation, or a passage that
shares almost no words with the question. They are **selected from published benchmarks**,
not written here (owner decision, 2026-11-27), so results can be compared with published work
and nobody's guess decides what "hard" means.

`scripts/build_hard_eval.py` makes both files from the benchmarks' own downloads, with a fixed
seed. `tests/unit/test_knowledge_hard_cases.py` checks them in `make test`.

| File | Holds |
| --- | --- |
| `cases.json` | The cases, each with its benchmark id |
| `documents.json.gz` | Every document the cases search, as Markdown text, in one knowledge base of its own |
| `cases.schema.json` | The format of `cases.json` |

The documents are kept apart from the main corpus, so the main eval and its baselines
(`evals/baselines/knowledge_retrieval*.json`) are unchanged.

## Cases

| Category | Cases | Benchmark | What makes it hard |
| --- | --- | --- | --- |
| `multi_hop` | 15 (5 each of 2, 3 and 4 hops) | MuSiQue v1.0 dev | The answer is found through other facts, each in its own passage |
| `comparison` | 12 (6 comparison, 6 bridge-comparison) | 2WikiMultihopQA dev | Two entities, each in its own article |
| `synthesis` | 10 | FRAMES test | Three or four whole Wikipedia articles, combined with counting or constraints |
| `follow_up` | 15 (one per conversation) | MTRAG human, ClapNQ domain | The question only makes sense with the earlier turns, which the case carries |
| `vocabulary_mismatch` | 10 | ClapNQ dev | The 10 questions sharing the fewest content words with their answer passage |
| `unanswerable` | 10 | MuSiQue v1.0 dev, unanswerable contrast questions | A passage the answer needs was removed; the rest are present |

How each was chosen (`scripts/build_hard_eval.py`):

- **multi_hop:** answerable MuSiQue questions, in the seed's order, five per hop count. All 20
  of each question's paragraphs go into the corpus: its supporting paragraphs and the
  benchmark's own distractors.
- **unanswerable:** the unanswerable twin of a MuSiQue question not used above. The build
  fails if a withheld paragraph is anywhere in the corpus, and the test checks it again.
- **comparison:** 2WikiMultihopQA `comparison` and `bridge_comparison` questions, with their ten
  context paragraphs (two supporting, eight distractors).
- **synthesis:** FRAMES questions linking three or four articles, without temporal or tabular
  reasoning (both depend on when the article was read). Each article is the last revision before
  2024-09-01, FRAMES' release; the revision id is stored. Articles over 120,000 characters are
  skipped, so no single one dominates the corpus. FRAMES names articles, not passages, so these
  sources have no quote.
- **follow_up:** MTRAG turns annotated `Follow-up` and `ANSWERABLE`, from turn 2 on, whose
  human-written standalone rewrite (`standalone`) adds at least two content words the turn
  itself lacks. The answer passages are MTRAG's relevance judgements; the reference answer is
  the conversation's agent reply.
- **vocabulary_mismatch:** ClapNQ answerable dev questions with at least three content words,
  ordered by the share of them that appear in the gold passage, lowest first.

The MTRAG and ClapNQ documents are whole articles, rebuilt from MTRAG's passage-level ClapNQ
corpus. The other passages of each article act as distractors.

## Format

- `required_sources` lists every passage the answer needs. `evidence` is the passage's first
  sentence (at most 160 characters), so a search hit counts when its chunk contains it, whatever
  the chunk boundaries. It is `null` for FRAMES, where the whole article counts.
- `answer` holds the benchmark's short answer and aliases. MTRAG and ClapNQ have long-form answers
  instead: `reference_answer`.
- `turns` (follow-ups only) are the earlier user and assistant messages, in order.

## Sources and licences

| Benchmark | Source | Licence of the benchmark |
| --- | --- | --- |
| MuSiQue v1.0 (Trivedi et al., TACL 2022) | [StonyBrookNLP/musique](https://github.com/StonyBrookNLP/musique), the authors' download | CC BY 4.0 |
| 2WikiMultihopQA (Ho et al., COLING 2020) | [Alab-NII/2wikimultihop](https://github.com/Alab-NII/2wikimultihop), `data_ids_april7.zip` | Apache-2.0 |
| FRAMES (Krishna et al., 2024) | [google/frames-benchmark](https://huggingface.co/datasets/google/frames-benchmark), `test.tsv` | Apache-2.0 |
| MTRAG (Katsis et al., TACL 2025) | [IBM/mt-rag-benchmark](https://github.com/IBM/mt-rag-benchmark) at `e0970de` | Apache-2.0 |
| ClapNQ (Rosenthal et al., 2024) | [primeqa/clapnq](https://github.com/primeqa/clapnq) at `c508d78` | Apache-2.0 |

The checksums of the downloads are in `scripts/build_hard_eval.py`.

**Document text.** Every passage is Wikipedia text, so `documents.json.gz` is licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), not under this repository's
Apache-2.0. Attribution: Wikipedia contributors, the article named by each document's title;
FRAMES documents also carry the article URL and revision. Questions, answers and relevance
judgements are the benchmarks' own, under the licences above, credited to their authors.

The data is public and holds no private information, so it may be sent to a hosted embedding
or chat API.
