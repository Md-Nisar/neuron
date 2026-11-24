# Knowledge and RAG evaluation framework for Neuron

**Status:** proposal for owner review. Written 2026-11-24 against `main` at v1.4.0. Nothing here is
implemented, and no new measurement was run for it: every Neuron number below comes from the
repository's own records (cited by file).

**Scope:** how to benchmark, diagnose and improve the quality of Neuron's Knowledge Engine and
answers, repeatedly, without regressions. It extends ADR 0007 (evaluation) and ADR 0014 (Knowledge
Engine). It adds no product feature.

**Evidence labels.** Every external claim carries one:

- **[V]** read in a source this session (links in section 13).
- **[K]** from the author's background knowledge, not re-checked here. Verify before quoting it
  outside this repository.
- **[J]** the author's judgment or a design proposal. Not from a source.

---

## 1. Summary

1. **The project already has most of a RAG evaluation harness.** It has recall@k, MRR, citation
   precision, abstention accuracy, CRAG-style answer labels, a claim-level faithfulness judge, a
   per-case regression gate with pass^k, a nightly live retrieval gate and committed baselines
   (`EVALUATION.md`). The task is therefore not to adopt a framework. It is to close the specific
   gaps below, so that the loop *baseline → diagnose → fix → re-measure* can be trusted.
2. **Six gaps limit what the current evaluation can tell us** (section 2): retrieval is near its
   ceiling, so it no longer discriminates; the corpus is public documents an LLM may already know;
   multi-document reasoning has 5 cases; the live baseline and the live answer eval predate
   dataset 2.0.0; the faithfulness judge is uncalibrated and ungated; and one dataset is used both
   to tune and to gate, with one trial per case.
3. **No public benchmark can serve as Neuron's quality gate.** BEIR, MS MARCO, HotpotQA, KILT, RGB,
   RAGBench, CRAG and MultiHop-RAG are research benchmarks on public corpora. They are useful for
   three narrower jobs: checking that the retrieval stack is wired correctly, calibrating the
   judge, and stress-testing abilities the golden set is too small to cover. The gate must be a
   project-specific golden set.
4. **There is no industry standard for RAG quality thresholds.** What is standard is the *metrics*
   of classic information retrieval (recall@k, MRR, nDCG) and a de facto vocabulary for judge
   metrics (faithfulness or groundedness, context relevance, answer relevance, from Ragas, TruLens
   and DeepEval). Thresholds must come from Neuron's own baseline noise and product risk (section 7).
5. **Recommendation:** keep the in-repo harness as the gate (ADR 0007's decision still holds). Borrow
   methods, not packages: RAGChecker's retrieval-versus-generator error split, ARES's use of a small
   human-labelled set to put confidence intervals on judge scores, the TREC RAG track's nugget
   recall, and two controls (closed-book, oracle-context) that separate retrieval from generation
   and expose memorisation. Add a frozen held-out split, paired statistical comparison, and an
   append-only evaluation history. Roadmap in section 11; six small PRs cover the first four phases.

---

## 2. Where Neuron stands (evidence from the repository)

| Area | What exists | Source |
| --- | --- | --- |
| Retrieval metrics | recall@5, MRR, recall@1 and @10; nightly live gate within 0.02 of baseline | `EVALUATION.md`; `evals/baselines/knowledge_retrieval*.json` |
| Answer metrics | `cited_correctly`, `abstention_accuracy`, CRAG labels (perfect, acceptable, incorrect, missing), `hallucination`, `false_refusal`, `vital_fact_recall`, `crag_score`, Wilson intervals | `EVALUATION.md`, "Answer metrics" |
| Judge | claim-level faithfulness, ALCE-style citation recall and precision. **Uncalibrated, not gated** | `evaluation_judge.py`; `EVALUATION.md` |
| Agent regression | per-case gate (passed all trials in baseline, fails all in candidate), pass^k, security pass^k = 100%, k >= 3 | `EVALUATION.md`; ADR 0007 section 6 |
| Dataset | 2.0.0: 188 answerable, 36 unanswerable, 5 ACL, 4 injection; 31 documents; plus 8 table cases | `tests/fixtures/knowledge_cases.json`, `.../knowledge/table_cases.json` |
| Operations | local load and scale benchmarks, SLO check, reranker latency (p50 1.32 s, p95 3.79 s) | `loadtest/`, `qa/retrieval_scale_benchmark.md`, v1.4.0 record |
| Security | 12-case knowledge security suite with 20 mutants, injection documents | tracker RAG-08.02 |

Latest recorded results: `cited_correctly` 1.0 and abstention 12 of 12 on the v1.4.0 run (live
model, one trial, which per the v1.4.0 record was the 64 + 12 case set of dataset 1.3.0); reranker
MRR 0.833 → 0.977 on 64 answerable cases (`docs/releases/v1.4.0-release-verification.md`).

### The six gaps

**G1. Retrieval is saturated on the old set, and the harder set has no live baseline.** On 64 cases
recall@5 reached 1.0 with the reranker, so it could not show further gains. Dataset 2.0.0 (188
cases) lowered the RRF baseline to recall@5 0.957 and MRR 0.823, but `knowledge_retrieval_live.json`
still holds the 1.3.0 figures (recall@5 0.984, MRR 0.924) (`tests/fixtures/knowledge/README.md`). The
reranked, live, 188-case number does not exist yet. Until it does, "retrieval is solved" is
unproven.

**G2. Contamination is unmeasured.** The corpus is largely public text (NIST AI 100-1, RFCs). A
model may answer from memory. The forced first search makes the agent *search*, but nothing shows
whether a correct answer came from the passage or from the weights. A closed-book run (section 8)
measures it. LLM benchmark contamination is a general risk for public corpora [J].

**G3. Multi-document reasoning is almost untested.** 182 of 188 answerable cases have one expected
source; 5 are `multi_hop` and 8 `comparison`. A per-type interval on 5 cases spans most of
[0, 1]. In addition, `recall@k` counts a hit when *any* expected passage is retrieved, which
overstates multi-evidence cases. HotpotQA scores supporting evidence as a set for this reason [V].

**G4. Staleness of evidence.** Release records mix datasets (64 cases in v1.1.0 to v1.4.0 answer
runs, 188 in the current retrieval baseline). Numbers from different dataset versions are not
comparable, and the history is prose in markdown, not queryable.

**G5. Judge not calibrated.** The repo's own bar is Cohen's kappa >= 0.6 on >= 200 labelled claims
(`EVALUATION.md`) and ADR 0007 asks for TPR and TNR >= 0.9 on >= 100 labelled runs. Neither has been
done, so faithfulness and citation precision are reported but cannot gate.

**G6. Tuning and gating share one dataset, with one trial.** The v1.1.0 record shows cases being
re-graded (`answerable-004, 016, 025` accept a second page) and a product change (forced first
search) after reading failing traces, all on the dataset that then gated the release.
`cited_correctly` varied from 0.891 to 0.952 across runs of near-identical code. At 64 cases a
95% interval on a rate near 0.9 is about ±0.073; at 188 it is about ±0.043 (normal approximation).
A run near a gate is not evidence either way. That is not an accusation: it is the expected result
of iterating on a small set, and the fix is a frozen held-out split.

---

## 3. Benchmarks: research artefacts versus industry practice

**What "standard" means here.** No standards body (ISO, NIST) defines RAG quality metrics or pass
thresholds [J]. The strongest standards are in *information retrieval*: TREC-style test
collections and the metrics of BEIR and MTEB. RAG-specific evaluation is a fast-moving research
area with de facto conventions set by open-source tools. Classification used below:

- **Established practice:** used across research and industry for years, with agreed definitions.
- **Research benchmark:** peer-reviewed, public, useful for comparison, not a product gate.
- **Tool convention:** metric names and prompts defined by a library; no independent standard.

| Benchmark | What it measures | Size and corpus | Class | Use for Neuron |
| --- | --- | --- | --- | --- |
| **BEIR** (Thakur et al., NeurIPS 2021) | Zero-shot retrieval across tasks; BM25 is a strong baseline; re-ranking and late interaction are best on average at higher cost [V] | 18 public datasets (the final paper says 18; the first arXiv version said 17) [V]; nDCG@10 is the primary metric [K, secondary source says so] | Established practice for retrieval | **Sanity check** of embed + chunk + hybrid + rerank on 3 to 4 small English subsets (e.g. SciFact, FiQA, NFCorpus) [J]. Compare against the paper's BM25 and dense rows [K]. A large gap means a wiring bug, not a product gap. Non-gating |
| **MTEB / MMTEB** | Embedding quality across 8 task types, up to 15 datasets each, 112 languages in MTEB [V] | Public leaderboard | Established practice for embeddings | **Model selection only** (embedding model swaps). Do not use as a product gate |
| **MS MARCO** + TREC Deep Learning | Passage ranking; leaderboard metric MRR@10; TREC DL also reports NDCG@10 over about 53 judged topics [V]. The authors of the TREC DL overview themselves question whether the leaderboard MRR is still meaningful [V] | Web queries, web passages | Established practice (metrics); leaderboard is contested | Source of the **metric definitions** and of NDCG with graded judgments. Licence is research-oriented [K]; check before any redistribution |
| **HotpotQA** (Yang et al., EMNLP 2018) | Multi-hop QA over Wikipedia, with sentence-level supporting-fact labels and comparison questions [V] | about 113k questions [V] | Research benchmark | Defines how to score **multi-evidence retrieval** (all supporting evidence found, not any). Use the *distractor* setting for a small multi-hop retrieval stress test [J] |
| **KILT** (Petroni et al., NAACL 2021) | 11 datasets, 5 tasks, one Wikipedia snapshot; downstream accuracy is credited only when the right provenance page is found [V] | Wikipedia | Research benchmark | Defines the **"answer counts only if provenance is right"** principle that `cited_correctly` already follows |
| **RGB** (Chen et al., AAAI 2024) | Four abilities: noise robustness, negative rejection, information integration, counterfactual robustness. English and Chinese [V] | Retrieved-document testbeds | Research benchmark | Template for **noise, rejection and conflict** cases. Neuron has rejection (36 unanswerable) but no noise-ratio or counterfactual testbed |
| **RAGBench** (Friel et al., Galileo) | 100k examples from 12 datasets (biomedical, legal contracts, customer support, finance, general). TRACe: utilisation, relevance, adherence, completeness. A fine-tuned 400M DeBERTa judge beat few-shot LLM judges [V]. Judge-facing labels at claim level | 100k | Research benchmark | **Judge meta-evaluation**: labelled adherence data to check Neuron's judge before the 200-claim human set exists. Non-gating |
| **CRAG** (Meta, KDD Cup 2024) | Factual QA, 4,409 questions, five domains, mock web and KG APIs. Labels perfect, acceptable, missing, incorrect scored 1, 0.5, 0, -1 [V]. Reports straightforward RAG lifts accuracy only from 34% to 44% [V] | 4,409 Q&A | Research benchmark | **Scoring rule already adopted** (`crag_score`). It encodes the right preference: a hallucination is worse than an abstention |
| **MultiHop-RAG** (Tang and Yang, 2024) | Multi-hop queries over news; compares embedding models and LLM reasoning [V]. Size and accuracy figures are from secondary pages, and a 2025 paper disputes the difficulty [V] | news, late 2023 | Research benchmark | Use only for **question-type design** (inference, comparison, temporal, null). Do not quote its size or accuracy without reading the paper |
| **ALCE** (Gao et al., EMNLP 2023) | Citation recall and precision with an NLI judge. Reported agreement with humans: 85.1% (recall), 77.6% (precision) [V] | ELI5, ASQA, QAMPARI | Research benchmark | Definitions already used by `evaluation_judge.py`. Also a **published ceiling** for what an automatic citation judge reaches: expect about 80%, not 100% |
| **TREC 2024 RAG track** | Nugget recall and support, with LLM-assisted assessment correlated with humans at run level [V] (Kendall tau above 0.79 for the support judge) | MS MARCO V2.1 segments | Evaluation campaign (closest thing to a standard) | Method for **completeness**: list the facts (nuggets) an ideal answer holds, then score recall. `expected_facts` is already a nugget list |
| **FinanceBench** (Patronus, 2023) | Questions with evidence about public-company filings. 10,231 questions in the paper, but only a 150-question subset is open [V]. The original paper found GPT-4-Turbo with retrieval wrong or refusing on 81% [V] | filings | Industry-flavoured research benchmark | The nearest public analogue to **enterprise tables and long documents**. Use the 150 as a table and numeric stress set if the product serves finance [J] |
| **tau-bench** | Agent tasks graded on end state, with pass^k as the reliability metric [V] | airline, retail | Research benchmark | Source of **pass^k**, already in `neuron-eval` |

**Enterprise-specific benchmarks.** No public benchmark reflects an organisation's own documents,
permissions and vocabulary. FinanceBench-style sets are the closest and cover one sector. For
Neuron, "enterprise" quality means: access control (a user never sees another's knowledge base),
untrusted-content handling, heterogeneous formats (PDF, DOCX, XLSX, web) and tables. Those are
tested only by Neuron's own fixtures. A golden set built from *the deployment's real documents* is
mandatory once a deployment exists.

**Contamination note.** Wikipedia-based sets (HotpotQA, KILT) and well-known standards (NIST,
RFCs) are very likely in model training data [J]. A high score there is weak evidence of retrieval
quality. This is why section 8 includes a closed-book control.

---

## 4. Evaluation frameworks compared

| Tool | What it provides | Strengths | Limits for Neuron |
| --- | --- | --- | --- |
| **Ragas** (Es et al., EACL 2024 demo) | Reference-free, LLM-judged metrics: faithfulness, answer relevancy, context precision, context recall, noise sensitivity [V] | Origin of the common metric vocabulary. Large community. Test-set generation | Judge-dependent, so scores shift with the judge model. Metric names and inputs have changed across versions (the archived page I found uses "answer relevance", newer docs "response relevancy") [V]. Reference-based metrics need a reference answer. A runtime dependency on a fast-changing library |
| **DeepEval** | pytest-native; answer relevancy, faithfulness, contextual precision, recall and relevancy [V]. Precision and recall are reference-based; relevancy is not [V] | Fits Neuron's pytest culture. Many metric types | Same judge dependence. ADR 0007 already compared it and chose the in-repo harness |
| **TruLens** | The "RAG triad": context relevance, groundedness, answer relevance, so that a low score points to retrieval, generation or the answer [V]. Snowflake's benchmark found its groundedness judge trailed the state of the art on precision [V] | Clear mental model. Feedback functions | Instrumentation-centred. Overlaps with Neuron's OpenTelemetry |
| **Arize Phoenix** (and Arize AX) | Evals library with prebuilt retrieval relevance, QA correctness and hallucination LLM judges; works on traces [V]. I did not read the current official Phoenix docs, so class names are unverified | Trace-first review UI; human annotation workflows | Hosted or self-hosted service to run and secure. Judge-dependent |
| **ARES** (Saad-Falcon et al., NAACL 2024) | Fine-tuned lightweight judges for context relevance, faithfulness and answer relevance, plus **prediction-powered inference** over a small human set, giving confidence intervals [V]. Reports a few hundred human labels sufficed in its tasks [V] | The only approach here with *statistical* guarantees on judge-based scores | Needs training data and judge fine-tuning. Use the *idea*: a human-labelled set to correct judge bias |
| **RAGChecker** (Ru et al., NeurIPS 2024 D&B) | Claim-level entailment; separates **retrieval errors** from **generator errors**; meta-evaluated against human judgments [V] | The diagnostic split that root-cause analysis needs. Open source | A new dependency. Use the *taxonomy* |
| **In-repo harness** (`neuron-eval`, `retrieval_metrics.py`, `evaluation_judge.py`) | Code graders, pass^k, per-case gates, Wilson intervals, versioned report schema, nightly CI | Runs through `AgentService` with real authorisation. No new dependency. Already gating | Gaps in section 2 |
| **LangSmith** | Datasets, experiments, online evaluators | ADR 0007 already names it as an optional upload | Hosted. `APP_ENABLE_LANGSMITH` upload still deferred |

**Judge reliability, in general.** LLM judges agree with humans above 80% on pairwise preference for
strong judges, but show position, verbosity and self-enhancement bias [V] (Zheng et al., NeurIPS
2023). Therefore: use a judge from a different model family than the answering model (the repo
already recommends it), pin the judge model and prompt, keep it binary and one dimension per call
(ADR 0007), and measure its agreement with people before gating.

**Recommendation on frameworks.** Do not add Ragas, DeepEval, TruLens or Phoenix as a gate or a
runtime dependency. Reasons: (a) ADR 0007 decided against it and nothing here changes its
reasoning; (b) judge-metric scores differ by library and judge version, so they are poor regression
signals; (c) the NVIDIA free tier is rate-limited to 30 to 40 calls a minute, and a Ragas-style run
makes several judge calls per case; (d) `CLAUDE.md` requires a justification for every dependency.
**Optional:** an offline script that exports a run to the Ragas or Phoenix input format for a
one-off cross-check. It is a dev tool, not a dependency, and a disagreement is a prompt to review
labels, not a gate. [J]

---

## 5. Evaluation dimensions, metrics and graders

**Principle.** Prefer deterministic graders. Use an LLM judge only where meaning is required, and
keep every judged metric non-gating until calibrated (section 7). "Exists" means present in the
repo today.

### 5.1 Knowledge quality (the corpus and its ingestion)

These are properties of the stored knowledge, not of the model. They are checkable without a model.

| Metric | Definition | Grader | Data | Exists? |
| --- | --- | --- | --- | --- |
| Parse fidelity | Share of known strings (the `evidence` quotes) found in the parsed text; for tables, cell accuracy against a reference | Code | Eval corpus with `evidence` | Partly: a unit test checks facts and quotes appear in parsed text |
| Chunk integrity | Share of evidence spans that sit wholly inside one chunk, or are covered by two adjacent chunks | Code | Chunks + `evidence` | No |
| Metadata completeness | Share of chunks with a resolvable locator (page or heading path), title, source and owner | Code | Stored chunks | No |
| Citation resolvability | Opening a citation returns text that contains the cited claim's evidence | Code | Citations from a run | Partly (`citations.py` validates ids) |
| Freshness / temporal correctness | After re-ingesting a changed document, the old value is never returned; after delete, nothing is returned (purge) | Code | Paired v1 / v2 document fixtures | Purge and reconcile exist; no answer-level temporal case |
| Consistency | Duplicate or conflicting documents: the answer cites the right one or flags the conflict | Code + judge | Conflict fixtures | No |
| Source reliability | Provenance recorded for every source (URL, fetch time, hash); untrusted content framed | Code | Web and upload fixtures | Injection suite covers framing |
| Coverage | Share of production queries answered "not in documents" | Production log | Production | Not possible: no production environment, and ADR 0007 section 7 is deferred |

*Accuracy of the source documents themselves* cannot be verified by software. The framework tests
that Neuron preserves and cites sources faithfully, not that the sources are true.

### 5.2 Retrieval quality

| Metric | Definition | Notes | Exists? |
| --- | --- | --- | --- |
| Recall@k (k = 1, 5, 10, 20) | Share of answerable cases with at least one correct passage in the top k | Existing definition (page range, heading or evidence quote) | Yes (@5, partly @1/@10) |
| **All-evidence recall@k** | Share of cases whose *every* required evidence item is in the top k | The honest metric for multi-source cases (HotpotQA-style [V]) | **No** |
| MRR@10 | Mean 1/rank of the first correct passage | | Yes |
| **nDCG@10** | Graded relevance (primary evidence 2, supporting 1, none 0), discounted by rank | Needs graded labels. Standard in BEIR and TREC [V] | **No** (labels are binary) |
| Precision@k / context precision | Share of top-k passages that are correct, or the DeepEval/Ragas definition [V] | Meaningful for the agent, because it reads the top results | Partly (`citation_source_precision`) |
| Stage recall | Recall of the gold passage at each stage: 80 candidates per path, fused top 40, reranked top 10 | Localises loss (embedding, fusion or rerank). The v1.2.0 rerank eval already measured two of the stages | Partly |
| Context relevance (judge) | Share of retrieved passages relevant to the question (TruLens, Phoenix [V]) | Judge. Report only | No |
| Coverage at scale | Recall and nDCG when the corpus is padded with real distractor documents (10k to 100k passages) | Neuron's scale benchmark used *synthetic* text and measured latency and ANN-versus-exact recall, not relevance at scale | **No** |

### 5.3 Generation quality

| Metric | Definition | Grader | Exists? |
| --- | --- | --- | --- |
| Answer correctness (CRAG labels) | perfect / acceptable / incorrect / missing from `expected_facts` | Code (phrase match) | Yes |
| `crag_score` | Mean of +1, +0.5, 0, -1 [V] | Code | Yes |
| Hallucination rate | Wrong answers among attempted ones | Code | Yes |
| False refusal | Abstained on an answerable case | Code | Yes |
| Completeness (nugget recall) | Vital facts stated over vital facts expected (TREC-style nuggets [V]) | Code | Yes (`vital_fact_recall`) |
| Faithfulness / adherence | Share of claims supported by cited or retrieved passages | Judge | Yes, uncalibrated |
| Citation recall and precision | ALCE definitions [V] | Judge | Yes, uncalibrated |
| `cited_correctly` | Answer cites at least one correct passage (KILT principle [V]) | Code | Yes (gate 0.9) |
| Abstention accuracy | Unanswerable cases abstained, split by `out_of_scope`, `near_miss`, `false_premise` | Code | Yes (gate: all) |
| **Phrase-match error rate** | Share of correct paraphrased answers marked wrong by phrase matching | Human audit of a sample | **No**; the docs admit strict matching |

### 5.4 Reasoning quality

| Metric | Definition | Data | Exists? |
| --- | --- | --- | --- |
| Multi-hop correctness | CRAG label on `multi_hop`, with all-evidence recall as the retrieval side | >= 40 multi-hop cases (currently 5) | Thin |
| Comparison and synthesis | Same for `comparison` | >= 30 cases (currently 8) | Thin |
| Noise robustness | Accuracy as irrelevant passages are mixed in at a set ratio (RGB [V]) | Controlled-context testbed | No |
| Counterfactual robustness | Detects or corrects a planted wrong fact in a retrieved document (RGB [V]) | Conflict fixtures | No |
| Numeric / table reasoning | Exact numeric match on `query_table` cases | `table_cases.json` (8) | Yes (8 cases) |
| Search behaviour | Searches per answer, repeated searches, step-limit endings | Run traces | Partly |

### 5.5 Operational quality

| Metric | Definition | Exists? |
| --- | --- | --- |
| Latency | p50, p95 of search and of a whole run | `loadtest/`, scale benchmark; **not in the knowledge eval report** |
| Tokens and cost per answer | By kind (input, output, cache, reasoning) | Tokens yes in agent report; cost no |
| Reliability | Infrastructure-error rate; pass^k | Yes |
| Scalability | Search latency and recall versus corpus size | Yes (synthetic) |
| Regression performance | Gate outcome per run, history trend | Gate yes; **trend no** |
| Security invariants | ACL leaks, obeyed injections, forged citations | Yes (100% gates) |

---

## 6. Dataset selection and the consolidated suite

Four tiers, from most to least authoritative for gating:

| Tier | Contents | Role | Gate? | Frequency |
| --- | --- | --- | --- | --- |
| **T1. Golden, held-out** | A frozen 30% of the golden cases, never used while tuning | Release verdict; detects overfitting | **Yes**, release only | Per release |
| **T2. Golden, development** | The remaining 70%, plus every fixed defect | Daily iteration; PR and nightly gates | **Yes** | PR (cached vectors), nightly (live) |
| **T3. Controlled stress sets** | Noise ratios, conflicts, versions, distractor padding, paraphrases, a small multilingual set (the repo already tests German FTS) | Isolates one ability | Reported, then gated per ability once stable | Weekly or pre-release |
| **T4. Public benchmarks** | BEIR subsets, a HotpotQA distractor subset, the RGB testbeds, the RAGBench subset for the judge, optionally FinanceBench-150 | Wiring sanity, judge calibration, external reference | **No** (non-gating by design) | Quarterly and on model swaps |

**Mapping: dimension → data.**

| Dimension | T2 / T1 golden | T3 stress | T4 public |
| --- | --- | --- | --- |
| Knowledge quality | evidence quotes, fixture documents | versioned and conflicting document pairs | none (no public set matches Neuron's formats) |
| Retrieval | 188 answerable, graded labels added | distractor padding; stage recall | BEIR subsets (nDCG@10 vs paper's BM25 row) |
| Generation | answerable, unanswerable | noise ratio sweep | RAGBench (judge calibration); CRAG scoring rule |
| Reasoning | multi_hop, comparison, tables | counterfactual, noise | HotpotQA distractor, RGB integration, FinanceBench-150 |
| Operations | load and SLO scenarios | corpus-size sweep | none |
| Security | ACL (5), injection (4) and the 12-case suite | mutants | none |

**Golden-set requirements** (goals to reach, not claims about today). Each case has: the user it runs
as, the question, expected sources with *grade* (primary or supporting), `evidence` quote, nuggets
(`expected_facts`), question type, and a `grading_note` when graded by hand. Sizes needed so that a
per-slice 95% interval is not meaningless: for a rate near 0.7, about 36 cases give a half-width of
±0.15 and about 80 give ±0.10 [J, normal approximation]. So multi-hop and comparison need roughly
40 and 30 cases to say anything, and slices below that are reported without an interval label of
"significant".

**Rules to keep the set honest** (a procedure, [J]):

1. Split once, by document and question type, with a fixed seed. Record the split in the dataset.
   The held-out split is run at release only, and a failing held-out case is analysed but the case is
   not edited to pass.
2. Never change a case's expected answer after seeing a model's failure, except for a documented
   dataset error (as `unanswerable-005` in v1.1.0), and bump the dataset version with a reason.
3. Every fixed production defect becomes a case in T2 (existing regression policy).
4. Two annotators label a 10% sample; report agreement. Disagreements decide the rubric, not the model.
5. Version everything. A result is meaningful only with `(dataset version, split, code SHA, prompt
   version, models, settings hash)`.

**Licences.** Redistributing a public dataset inside this repository needs a licence check per
dataset. HotpotQA and BEIR sub-datasets carry different licences [K]; download at run time and
cache outside the repository instead of committing them, as the project already does for its
public eval documents (`scripts/build_knowledge_eval.py`).

---

## 7. Scoring methodology and thresholds

### 7.1 No composite score

A single weighted "RAG quality score" would hide trade-offs (an agent that refuses everything
abstains perfectly) and its weights would be arbitrary. Instead report a **scorecard of the
dimensions in section 5**, each with a value, a 95% interval and its gate class.

### 7.2 Three gate classes

| Class | Rule | Applies to |
| --- | --- | --- |
| **Invariant** | 100% in every trial; zero tolerance | ACL leaks, obeyed injection, citations to passages not retrieved, system-prompt leaks |
| **No-regression** | The lower bound of the paired difference (candidate minus baseline) must exceed -δ, where δ is the measured noise floor of the metric (below) | Recall@k, MRR, nDCG@10, correctness, hallucination, false refusal, `cited_correctly`, latency |
| **Absolute floor** | The candidate's lower interval bound must exceed an **owner-set floor** | `cited_correctly` >= 0.9 and abstention (existing owner decisions); proposed floors for new metrics after the first baseline |

**Where thresholds come from.** There is no source that says faithfulness should be 0.9 or
recall@5 should be 0.95, and a number copied from a blog would be arbitrary. Derive them:

1. **Noise floor δ.** Run the *unchanged* code at least 5 times at k = 3 trials on the development
   split. Take the range (or 2 standard deviations) of each metric. Existing evidence: `cited_correctly`
   moved 0.891 to 0.952 over one-trial runs, so δ is about 0.06 for that metric at 64 cases; it will
   shrink with 188 cases and k = 3.
2. **Minimum detectable effect.** With n cases and a paired design, the detectable change depends on
   how many cases flip. Report it with each comparison so that "no change" is not read as "no effect".
3. **Product floors** are a business decision. Propose them from the baseline (for example "no worse
   than the best release minus δ") and have the owner approve each, recorded in the ADR 0007 addendum.
   They are policy, not science.

### 7.3 Statistics

- **Intervals:** Wilson 95% for single rates (already used). Treat trials of the same case as
  correlated: bootstrap over *cases*, not trials.
- **Comparing two configurations:** a paired test on the same cases and trials: McNemar's test for
  pass or fail per case, or a paired bootstrap of the metric difference [K]. Both use the information
  that most cases do not change between runs, so they detect smaller effects than comparing two
  separate intervals.
- **Multiple metrics:** many comparisons produce false alarms. Designate 3 to 5 **primary metrics**
  before the experiment; the rest are diagnostic. [J]
- **Consistency:** pass^k, as in the existing harness [V], reported beside the pass rate.
- **Judge-based scores:** report the judge's measured agreement with humans next to every score
  (ARES's principle of correcting judge error with a small labelled set [V]). Until agreement is
  measured, label the score "uncalibrated".

### 7.4 Prioritisation of weaknesses

Rank each failure cluster by `severity × share of cases ÷ effort` [J]. Severity classes, from
the project's own security model and the CRAG scoring preference [V]:

| Severity | Description | Weight (proposed) |
| --- | --- | --- |
| S0 | Security or privacy invariant broken | blocks release |
| S1 | Confident wrong answer, or a citation that does not support the claim | 3 |
| S2 | False refusal, incomplete answer, wrong ranking that the agent recovers from | 2 |
| S3 | Latency, cost, formatting | 1 |

The weights are a proposal for the owner to confirm; CRAG's scoring supports only the ordering
(wrong is worse than missing), not the numbers.

---

## 8. Baseline evaluation methodology

Run once, on a frozen configuration, before any improvement. Everything is a controlled comparison
on the same cases.

**Freeze:** git SHA, dataset version and split, system prompt version, chat, embedding and reranker
model identifiers, `Settings` hash, Postgres and pgvector versions, judge model and prompt version.

**Seven runs** (the first four need no chat model):

| # | Run | Question it answers | Existing tooling |
| --- | --- | --- | --- |
| B1 | **Retrieval, deterministic**: cached vectors, RRF, 188 cases, stage recall, all-evidence recall, nDCG@10 once graded | Is the retriever sound, and where does gold get lost? | `test_postgres_knowledge_retrieval.py` (extend) |
| B2 | **Retrieval, live**: live query embedding and reranker | Does the production path match B1? | `test_live_knowledge_retrieval.py` (refresh baseline for 2.0.0) |
| B3 | **Retrieval at scale**: B1 with real distractor padding | Does relevance survive 10x to 50x more passages? | New (`scripts/knowledge_scale_bench.py` as a base) |
| B4 | **Public sanity**: BEIR subsets through the same chunk, embed and rerank path | Is the stack within the range of published results? | New, non-gating |
| B5 | **Closed-book control**: same questions, chat model, no tools | How much of the "answered correctly" comes from memory? | `neuron-eval` with the knowledge tools off |
| B6 | **Oracle-context control**: gold passages given directly to the model | Upper bound for generation; any miss here is a generation or grading problem | New small runner |
| B7 | **Full pipeline**: `AgentService`, k = 3, dev and held-out splits | Real behaviour | `test_live_knowledge_answers.py` (extend to k = 3, 224 cases) |

Plus: **judge calibration** (200 labelled claims, human label, kappa and TPR/TNR; cross-checked on
the RAGBench subset) and **operational** (latency p50 and p95, tokens, cost per answer, error rate).

**Interpreting B5 to B7 together** (a standard ablation design, [J]):

| Closed-book | Oracle | Full | Reading |
| --- | --- | --- | --- |
| high | high | high | The set is too easy or memorised. Replace with private or paraphrased facts |
| low | high | low | **Retrieval or agent-search problem**: fix retrieval |
| low | high | high | System works and adds value over memory |
| low | low | low | **Generation, grading or label problem**: audit cases and prompts |

**Failure attribution** for each failing case, in order, stopping at the first "no" (this is
RAGChecker's retrieval-versus-generator split [V] refined to Neuron's stages [J]):

1. Is the evidence in the **parsed text**? (ingestion)
2. Is it in a **chunk** whole? (chunking)
3. Is it among the **candidates** of dense or full-text search? (embedding, query)
4. Is it in the **top 10 after fusion and rerank**? (ranking)
5. Did the **agent search** with a useful query and read the result? (search behaviour)
6. Did the answer **state the nuggets**? (generation)
7. Did it **cite** the right passage and **abstain** correctly? (citation, abstention)

The output is a table of counts per stage, which tells where to spend effort. Add a short human
review of a sample of 30 failures to catch grader errors (strict phrase matching can mark a correct
paraphrase wrong; the docs already say so).

**Benchmark comparison.** Compare Neuron's B1/B2 against (a) its own history, (b) the published
BM25 and dense rows of BEIR [K] for B4, and (c) closed-book and oracle for B5 and B6. Do not compare
absolute Neuron numbers with a paper's numbers on a different corpus.

---

## 9. The iterative improvement loop and regression prevention

```
Baseline → Compare → Weakness → Root cause → Change → Re-evaluate → Compare → Decide
   B1..B7   history     stage table  attribution   one hypothesis   dev k=3   paired test   keep / revert
                                                                     then held-out once
```

**Experiment protocol** (one record per experiment, `docs/evals/experiments/EXP-nnn.md`, [J]):

1. **Hypothesis**, written first: "Changing X will raise metric M by at least d on slice S, and will
   not worsen metrics R by more than δ."
2. **One change** per experiment (a chunk size, a prompt rule, a reranker, a query rewrite).
3. **Run** on the development split, k = 3, with the same frozen configuration otherwise.
4. **Decide** with the paired test and the pre-registered primary metrics. Success on a metric that
   was not the hypothesis is a lead for a new experiment, not a result.
5. **Confirm once** on the held-out split. If it fails there, the change is rejected, and the
   dev-split gain is treated as overfit.
6. **Record** the outcome, including reverted changes. Negative results prevent repeating them.
7. If kept, **refresh the baseline** by the existing reviewed-PR rule (`EVALUATION.md`, "Refreshing a
   baseline").

**Evaluation history.** An append-only record, in the repository (no new infrastructure, consistent
with ADR 0001 and 0002):

```
evals/history/knowledge/
  index.jsonl                       one line per run: run_id, date, sha, dataset, split, metrics{}, gate
  runs/<run_id>.json                full report (report schema versioned, as now)
  experiments/EXP-nnn.md            hypothesis, change, result, decision
```

Each line carries `(dataset_version, split, sha, prompt_version, models, settings_hash, trials)`.
A tool prints a trend table for any metric over runs *with the same dataset version*, and refuses to
chart across dataset versions without a "re-baselined" marker. This fixes G4. If an external store
is wanted later, the same records upload to LangSmith experiments (already planned, ADR 0007).

**Regression-prevention tiers:**

| Tier | Trigger | Content | Needs live model | Blocks |
| --- | --- | --- | --- | --- |
| 0 | every PR (`make test`) | dataset-shape tests, grader unit tests, metric unit tests, invariants with the fake model | No | Yes |
| 1 | every PR touching `knowledge/` | deterministic retrieval B1 with cached vectors; paired comparison with baseline | No | Yes |
| 2 | nightly | live retrieval B2, agent regression, security pass^k >= 3 | Yes | Yes (red only on a real gate failure; infrastructure errors are "inconclusive") |
| 3 | pre-release | B1 to B7 on dev and held-out, judge, closed-book and oracle, scale | Yes | Yes |
| 4 | quarterly, or on any model swap | B4 public sanity, judge recalibration, dataset refresh and reseed | Yes | Informational, but a drift triggers an issue |

**Preventing silent regressions**: the *gate* for retrieval changes lives at Tier 1, because it
needs no provider and is deterministic. Provider-side drift (a retired model, a changed embedding)
is what Tier 2 catches; the v1.4.0 reranker retirement is the example (searches fell back to the
hybrid order without a test failing, only `knowledge_rerank_skipped` logs). Add an invariant that a
nightly run fails if the reranker or embedding *fell back* during the eval (the test already refuses
to score such a run; make it a named gate).

---

## 10. Recommended architecture

```
                 ┌──────────────────────── Datasets (versioned, split, seeded) ───────────────────────┐
                 │ T2 golden-dev   T1 golden-held-out   T3 stress sets   T4 public subsets (cached)   │
                 └───────────┬──────────────────────────────────────────────────────────┬─────────────┘
                             │                                                          │
        ┌────────────────────▼────────────────────┐                        ┌────────────▼───────────┐
        │ Runners                                  │                        │ Controls               │
        │ retrieval (det / live / scale)           │                        │ closed-book, oracle    │
        │ agent (AgentService, k trials)           │                        └────────────┬───────────┘
        └───────────────┬──────────────────────────┘                                     │
                        │ raw traces: passages, citations, answer, latency, tokens, errors
        ┌───────────────▼────────────────────────────────────────────────────────────────▼───────┐
        │ Graders:  code (retrieval, nuggets, CRAG labels, invariants)  |  judge (pinned, calibrated, report-only until agreement measured) │
        └───────────────┬───────────────────────────────────────────────────────────────────────┘
                        │
        ┌───────────────▼────────────────┐   ┌────────────────────────────┐   ┌─────────────────────┐
        │ Report (versioned schema)      │──▶│ Compare: paired test,      │──▶│ History (jsonl +    │
        │ scorecard by dimension, CI,    │   │ gate classes, stage table, │   │ experiments/*.md)   │
        │ failure attribution            │   │ inconclusive on infra err  │   │ trend per dataset   │
        └────────────────────────────────┘   └────────────────────────────┘   └─────────────────────┘
```

Everything above already exists in outline in `neuron-eval`, `retrieval_metrics.py`,
`evaluation_judge.py` and the nightly workflow; the new parts are the held-out split, the controls,
stage and all-evidence metrics, the paired compare, and the history.

**Boundaries.** Keep the code under `src/neuron_agent/evaluation*.py` and `retrieval_metrics.py` as
now; the Knowledge Engine imports nothing from evaluation. Public-benchmark loaders live in
`scripts/`, not in `src/`, so the product has no dependency on them. A new judge prompt goes in
`prompts/eval/` with a pinned version (existing practice). Per `AGENTS.md` this needs an addendum to
ADR 0007, not a new ADR, unless an external service is introduced.

---

## 11. Implementation roadmap

Each phase fits the project's rules: PRs under 400 changed lines, tests that fail without the
change, and a tracker update. Effort is an estimate [J]. IDs are proposals; the backlog and ADR are
the owner's to approve.

| Phase | Deliverable | Depends on | Effort | Exit evidence |
| --- | --- | --- | --- | --- |
| **P0. Re-baseline** | Refresh `knowledge_retrieval_live.json` for dataset 2.0.0 with the reranker; run the full-pipeline answer eval on 188 + 36 cases at k = 3; record the noise floor (5 repeats); first `index.jsonl` entry | NVIDIA key, Postgres | 2 to 3 days (mostly run time: about 35 min per single-trial pass at 30 calls a minute, so about 2 h per k = 3 pass) | Baseline run records, δ per metric |
| **P1. Metrics** | All-evidence recall@k, stage recall, nDCG@10 (graded labels for multi-source cases), per-`question_type` report with sample-size warnings | P0 | 1 PR | Unit tests on hand-computed examples |
| **P2. Controls and split** | Closed-book and oracle runners; frozen dev and held-out split with seed and a test that the split is stable | P0 | 2 PRs | Table of closed-book / oracle / full (section 8) |
| **P3. Compare** | Paired bootstrap or McNemar in the compare step; MDE reported; gate classes of section 7 | P0, P1 | 1 PR | Compare output with intervals; test of a seeded known regression |
| **P4. History** | `evals/history/knowledge/` schema, writer, trend printer, experiment template | P0 | 1 PR | Two runs appear in a trend table |
| **P5. Dataset v3** | 40 multi-hop, 30 comparison, conflict and versioned-document fixtures, noise-ratio testbed, paraphrase variants, small multilingual set; graded labels | P2 | 2 to 3 PRs, mostly annotation | Two-annotator agreement on a 10% sample |
| **P6. Judge calibration** | 200 human-labelled claims, kappa and TPR/TNR; RAGBench cross-check; promote faithfulness and citation precision to no-regression gates if the repo's bar is met | P2 | 1 PR + about 200 labels | `cohen_kappa` >= 0.6 on >= 200 claims, TPR and TNR >= 0.9 |
| **P7. Scale relevance** | Real-distractor padding run; relevance versus corpus size | P1 | 1 PR | Recall and nDCG curve at 2k, 20k, 100k |
| **P8. Public sanity** | BEIR subsets, HotpotQA distractor subset, RGB testbeds, loaders in `scripts/`, run quarterly | P1 | 1 to 2 PRs | Non-gating report; licence notes |
| **P9. Operations in the report** | Latency p50/p95, tokens and cost per answer in the knowledge report; link to load-test SLOs | P0 | 1 PR | Report fields; schema bump |
| **P10. Production feedback** | Convert real failures to cases; coverage metric from "not in documents" rate | A production deployment (does not exist) | later | Needs ADR 0007 section 7 |

**Sequence.** P0 first (it costs only time and is the evidence everything else needs), then P1, P3
and P4 in parallel with P2, then P5 and P6 (the slow, human-labelling work). P7 to P9 follow. Do not
start improvement experiments before P0, P2 and P3 exist, or their results will not be trustworthy.

**What an improvement cycle looks like once P0 to P4 exist** (example, [J]): the stage table shows
most misses at stage 4 (rerank) for `comparison` cases → hypothesis: sending two sub-queries and
merging raises all-evidence recall@10 by at least 0.05 without lowering MRR by more than δ → one
change behind a setting → dev split k = 3, paired test → one held-out confirmation → record EXP-nnn
and refresh the baseline by the reviewed-PR rule.

---

## 12. Risks, limits and decisions needed

**Limits of this document.**
- No measurement was run; all Neuron figures are from the repository's records. The proposed
  numeric targets are placeholders until P0 produces a noise floor.
- Several external facts are [K] or came from secondary pages (MultiHop-RAG size, FinanceBench subset,
  the Ragas and Phoenix current API). Verify against the papers before quoting.
- LLM-judge metrics are an active research area. Treat any single score as an estimate with a
  measured error, not a fact.

**Risks and mitigations.**
- *Annotation cost* (P5, P6) is the real expense. Mitigate: label only the 10% sample twice, reuse
  RAGBench for early judge checks, and prioritise multi-hop and conflict cases.
- *Free-tier rate limits* stretch runs (about 35 minutes for 76 runs at 30 calls a minute). Mitigate:
  Tier 1 needs no provider; run Tier 3 off-hours; keep the existing "inconclusive" handling.
- *Goodhart:* optimising to the dev split. Mitigate: the held-out split, spot human review, and
  refreshing the golden set when it saturates.
- *Single-model dependence:* the reference model is a free-tier catalog model. Re-run the baseline on
  any production-model change; the release gate on the production model is still an open known issue.

**Decisions for the owner.**
1. Accept the held-out split (30%) and the rule that it runs at release only?
2. Accept "no composite score" and the three gate classes?
3. Who labels the 200 claims, and is a second annotator available for agreement?
4. Is the dev/held-out data allowed to include real deployment documents once a deployment exists?
5. Approve an ADR 0007 addendum (judge gating, history, gate classes) and a tracker epic for P0 to P9?

---

## 13. Sources

Verified in this session ([V]):

- BEIR: Thakur et al., [arXiv 2104.08663](https://arxiv.org/abs/2104.08663), NeurIPS 2021 [poster](https://neurips.cc/virtual/2021/poster/29903)
- RAGBench: Friel et al., [arXiv 2407.11005](https://arxiv.org/abs/2407.11005)
- RGB: Chen et al., [arXiv 2309.01431](https://arxiv.org/abs/2309.01431), AAAI 2024
- Ragas: Es et al., [arXiv 2309.15217](https://arxiv.org/abs/2309.15217), EACL 2024 [demo](https://aclanthology.org/2024.eacl-demo.16); metric names via [archived v0.1.21 docs](https://docs.ragas.io/en/v0.1.21/concepts/metrics/) and [NVIDIA's summary](https://docs.nvidia.com/nemo-platform/latest/documentation/evaluate-models/metrics/rag-metrics)
- HotpotQA: Yang et al., [ACL Anthology D18-1259](https://aclanthology.org/D18-1259/)
- KILT: Petroni et al., [arXiv 2009.02252](https://arxiv.org/abs/2009.02252)
- CRAG: [arXiv 2406.04744](https://arxiv.org/abs/2406.04744); [KDD Cup 2024 page](https://aicrowd.com/challenges/meta-comprehensive-rag-benchmark-kdd-cup-2024)
- MultiHop-RAG: Tang and Yang, [arXiv 2401.15391](https://arxiv.org/abs/2401.15391) (figures unverified); critique in [arXiv 2510.11956](https://arxiv.org/abs/2510.11956)
- ARES: Saad-Falcon et al., [NAACL 2024](https://aclanthology.org/2024.naacl-long.20), [arXiv 2311.09476](https://arxiv.org/abs/2311.09476)
- DeepEval: [RAG triad guide](https://www.deepeval.com/guides/guides-rag-triad) (metric details from a docs mirror)
- TruLens: [RAG triad](https://trulens.org/getting_started/core_concepts/rag_triad); [Snowflake judge benchmark](https://www.snowflake.com/en/blog/engineering/eval-guided-optimization-llm-judges-rag-triad/)
- Phoenix / Arize: [retrieval evaluation docs](https://arize.com/docs/ax/learn/evaluation-concepts/retrieval-evaluation), [Haystack cookbook](https://haystack.deepset.ai/cookbook/arize_phoenix_evaluate_haystack_rag/) (official Phoenix docs not read)
- MS MARCO and TREC DL: [Craswell et al., "MS MARCO: Benchmarking Ranking Models in the Large-Data Regime"](https://arxiv.org/abs/2105.04021)
- ALCE: Gao et al., [arXiv 2305.14627](https://arxiv.org/abs/2305.14627), EMNLP 2023
- FinanceBench: Islam et al., [arXiv 2311.11944](https://arxiv.org/abs/2311.11944)
- LLM-as-judge: Zheng et al., [arXiv 2306.05685](https://arxiv.org/abs/2306.05685), NeurIPS 2023
- TREC 2024 RAG: [AutoNuggetizer initial results, arXiv 2411.09607](https://arxiv.org/abs/2411.09607); [The Great Nugget Recall, arXiv 2504.15068](https://arxiv.org/abs/2504.15068); [Support evaluation, arXiv 2504.15205](https://arxiv.org/abs/2504.15205)
- RAGChecker: Ru et al., [arXiv 2408.08067](https://arxiv.org/abs/2408.08067), NeurIPS 2024 D&B
- tau-bench: Yao et al., [arXiv 2406.12045](https://arxiv.org/abs/2406.12045); MTEB: [arXiv 2210.07316](https://arxiv.org/abs/2210.07316); MMTEB: [arXiv 2502.13595](https://arxiv.org/abs/2502.13595)

Repository evidence: `EVALUATION.md`; `docs/decisions/0007-evaluation-and-observability.md`;
`docs/releases/v1.1.0-retrieval-eval.md`, `v1.2.0-rerank-eval.md`, `v1.4.0-release-verification.md`;
`tests/fixtures/knowledge/README.md`; `tests/fixtures/knowledge_cases.json`;
`qa/retrieval_scale_benchmark.md`; `docs/product/RAG_IMPLEMENTATION_TRACKER.md`.
