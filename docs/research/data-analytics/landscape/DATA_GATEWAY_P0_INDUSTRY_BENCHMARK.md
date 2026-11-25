# Data Gateway P0: how others close the gaps the spike found

Nov 24, 2026 · research follow-up to the DG-E00 design spike ([decision record](../../../releases/data-gateway-p0/decision-record.md), [spike log](../../../releases/data-gateway-p0/design-spike-log.md))

## 1. Summary

**The spike's binding problem, correct refusal (best arm 80% against 90%), is an industry-wide problem, not a Neuron one. The products that handle it best do not ask one model to both write SQL and decide whether to answer. They put a separate triage step in front, keep a human-curated "known good" answer set, and treat unanswered questions as a work queue for authors.** That maps almost exactly onto what our measurements already say: arm B is the best judge of *whether* to answer, arm A2 the best writer of *how*.

What this study adds to the existing research (which already covers Cortex Analyst's and Genie's pipelines, verified queries, value matching, leak-proof evals and row security):

| Spike gap (from the decision record) | What others do | Strongest lesson for us |
| --- | --- | --- |
| G1. Correct refusal 46.7–80.0%, threshold 90% | Separate answerability triage before generation (Cortex, TriageSQL, TrustSQL "pipeline" methods, schema-relevance detectors) | Split *decide* from *write*; measure the split offline on data we already have |
| G2. Wrong answers without refusal 16.6–24.9% in the accurate arms | Calibrated confidence and reject option; multi-provider agreement beats self-consistency | Our single-provider setup blocks the strongest signal; S1's non-NVIDIA endpoint matters for accuracy, not only for portability |
| G3. Auto Ontology never asks back (F13) | Clarification as a first-class outcome with author-defined triggers (Genie, Cortex suggestions) | Author-written clarification rules per ambiguous pattern, tested like verified queries |
| G4. A1/A2 p95 70–80 s | Fast path for known questions; parallel candidates; small specialised SQL models | A verified-query hit should never enter the slow pipeline |
| G5. Certification lost in the round trip (S4, F11, F12) | Nobody makes certification portable; each vendor keeps it in its own catalog | Our loss is a documented upstream limit; certification must live in Neuron's catalog |
| G6. Arm B (semantic model) did not beat schema-only on accuracy | Looker: the model selects fields through an API, it does not write SQL | The semantic model's win comes from *constraining output*, not from *more context* |

**Evidence labels** (as in the other studies here). **\[F\]** official docs, specs, papers or primary posts. **\[E\]** practitioner or self-reported, including vendor-internal numbers. **\[I\]** this study's inference. **\[R\]** recommendation. Vendor accuracy claims are not independently replicated. Papers marked *preprint* are not peer-reviewed.

## 2. What the spike left open

Numbers are D3 from the [decision record](../../../releases/data-gateway-p0/decision-record.md); not restated in detail here.

- **Refusal is the binding constraint.** Every arm's upper bound is below 90%. Gate 2 fails on this threshold alone.
- **The accuracy and the caution live in different engines.** A2 is 89.5% accurate and 95.2% correct when it writes SQL, but refuses 46.7% and never clarifies. B refuses 80.0% and keeps wrong answers to 3.7%, but is 71.0% accurate.
- **Latency is an Auto Ontology problem** (several model calls per question), not a gateway problem: B and C sit at 25–34 s.
- **Certification does not travel** between Auto Ontology and Ossie, and dataset-scoped metrics are lost.
- **One model, one provider** in every arm; no non-NVIDIA endpoint was available.

## 3. Industry benchmark, gap by gap

### 3.1 G1: deciding whether to answer

**Snowflake Cortex Analyst: classify first.** \[F\] A classification agent sorts each question into ambiguous, non-data, non-SQL data question, or answerable; only the last reaches SQL generation ([engineering blog](https://www.snowflake.com/en/blog/engineering/snowflake-cortex-analyst-behind-the-scenes/)). Ambiguous questions return a `suggestions` content type instead of SQL ([REST API](https://docs.snowflake.com/user-guide/snowflake-cortex/cortex-analyst/rest-api)). \[F\] Snowflake's launch post says it "proactively identifies and rejects ambiguous or unanswerable questions" ([blog](https://www.snowflake.com/en/blog/cortex-analyst-ai-self-service-analytics/)). The existing research described the generator ensemble; the point here is that the refusal decision is a *separate stage with its own model call*.

**Research converges on the same split.** \[F\] TrustSQL scores each output as SQL or abstention, penalises wrong SQL more than abstaining, and compares *pipeline* methods (answerability detector, generator, error detector) with unified single-model methods; it finds high scores under severe penalties "remain highly challenging" and no method consistently wins ([TrustSQL](https://arxiv.org/abs/2403.15879)). \[F\] A COLING 2025 paper detects unanswerable questions by predicting which schema elements a question needs, which also makes the refusal explainable ([Han et al.](https://aclanthology.org/2025.coling-main.706.pdf)). \[F\] *Preprint:* "Query Carefully" adds an explicit unanswerable-detection stage; best detection accuracy 0.8, but only 0.3 on column ambiguity ([arXiv 2512.21345](https://arxiv.org/abs/2512.21345)). TriageSQL (2020) set up the four-way triage benchmark that these build on.

**Amazon Q in QuickSight: unanswered questions are an author queue.** \[F\] Topic performance pages filter to questions Q "could not respond to", and authors answer them with *reviewed* (verified) answers ([topic performance](https://docs.aws.amazon.com/quick/latest/userguide/topics-performance.html), [verifying answers](https://docs.aws.amazon.com/en_us/quicksight/latest/user/quicksight-q-topics-verifying.html)). \[F\] ThoughtSpot does the same with "coaching": coverage gaps and down-votes become new reference questions ([after coaching](https://docs.thoughtspot.com/cloud/latest/spotter-coach-after)).

**Why it works \[I\].** A refusal decision needs a different input than SQL writing: *what the model covers and what it does not*. A generator conditioned on a rich ontology is biased towards producing something (A1/A2 refuse least). A triage stage that sees the question against the catalog's declared scope is not.

### 3.2 G2: knowing when an answer is probably wrong

\[F\] Somov and Tutubalina (AAAI 2025) add a reject option to text-to-SQL; post-hoc calibration (Platt, isotonic) helps, but calibration weakens under distribution shift, where the selective classifier has high recall and low precision ([paper](https://arxiv.org/abs/2501.09527)). \[F\] *Preprint, July 2026:* black-box self-consistency reaches only 0.61–0.68 AUROC at predicting correctness; an LLM judge does better; a **two-provider ensemble** reaches about 0.82 and is the only signal that yields a usable low-risk operating point ([Richardson](https://arxiv.org/abs/2607.06799)). \[F\] A second review finds consistency methods strongest among black-box approaches, with query execution a useful extra signal ([arXiv 2610.17256](https://arxiv.org/pdf/2610.17256)).

**Implication \[I\].** Our wrong-answer threshold (at most 5%) is a selective-prediction target. The strongest known signal needs **two independent providers**. Every P0 arm ran one NVIDIA model, so S1's non-NVIDIA endpoint is not just a portability check; it unlocks the best confidence signal.

### 3.3 G3: asking back

\[F\] Databricks Genie may answer with "a follow-up clarification question" or explain it cannot answer ([talk to Genie](https://docs.databricks.com/aws/en/genie/talk-to-genie)). Its guidance is specific: teach ambiguity with **example SQL** first, text instructions last ([best practices](https://docs.databricks.com/aws/en/genie/best-practices)); a Databricks employee advises writing each rule as *trigger condition + missing detail + the exact question to ask*, not a generic "ask for clarification" ([community answer](https://community.databricks.com/t5/generative-ai/can-genie-ask-clarifying-questions/m-p/125575)) \[E\].

**How hard it is everywhere.** \[F\] BIRD-INTERACT (ICLR 2026) gives each task an ambiguous sub-task that must be resolved by asking a simulated user; GPT-5 completes 8.67% of tasks conversationally and 17.00% agentically ([paper](https://arxiv.org/abs/2510.05318)). \[F\] PRACTIQ (NAACL 2025) and AMBROSIA (NeurIPS 2024) both report state-of-the-art systems struggle to recognise ambiguity ([PRACTIQ](https://arxiv.org/abs/2410.11076), [AMBROSIA](https://arxiv.org/abs/2406.19073)). \[F\] Oracle's CLARITY (ACL 2026 industry) adds multi-facet ambiguity ([pdf](https://aclanthology.org/2026.acl-industry.86.pdf)).

**Implication \[I\].** Expect a generic "clarify when unsure" prompt not to fix F13. Products that clarify well do it through **author-declared triggers**, i.e. the clarification is data in the semantic model, testable like a verified query.

### 3.4 G4: latency of multi-call engines

- **Known questions skip generation.** \[F\] Cortex verified queries, QuickSight reviewed answers and ThoughtSpot reference questions all return a curated answer for known questions. \[I\] A2 certifies terms and SQL attributes, not whole questions, so every question still runs the full Auto Ontology pipeline (p95 69.9 s). A whole-question verified-query hit would skip it; that is the cheapest latency fix and also the most accurate path.
- **Parallel, not sequential, candidates.** \[F\] Cortex runs several generators in parallel and then checks (existing research, section 6.1). Latency is the slowest branch, not the sum.
- **Small specialised SQL models.** \[F\] Arctic-Text2SQL-R1 (Apache-2.0): 32B reaches 71.83% on BIRD with greedy decoding, 14B 70.04%; the 7B matches earlier 70B models ([Snowflake](https://www.snowflake.com/en/blog/engineering/arctic-text2sql-r1-sql-generation-benchmark/), [paper](https://arxiv.org/abs/2505.20315)). No latency figures are published.
- **Cascades: a caution.** \[F\] Cheap-first cascades (FrugalGPT lineage) only pay off with a calibrated escalation signal ([UCCI, preprint](https://arxiv.org/abs/2605.18796), [escalation signals, preprint](https://arxiv.org/pdf/2610.07354)). \[E\] Practitioners report tail latency rises on escalated queries. For a p95 threshold, a cascade can *worsen* the metric we gate on.

### 3.5 G5: certification and semantic portability

\[F\] OSI became **Apache Ossie (incubating)**, the format our spike already uses. The core spec draft (0.3.0.dev0) has **no certified, verified or trust field**; the only vendor slot is `nonportable_extensions` (renamed from `custom_extensions`, which "is not accepted"), and "core semantics MUST NOT depend on extensions" ([spec](https://raw.githubusercontent.com/apache/ossie/main/core-spec/spec.md)). This independently explains F10 (the pinned `main` rejecting `custom_extensions`) and D13.

\[F\] The Apache converter for Auto Ontology (vendor token `NVIDIA_AUTO_ONTOLOGY`, formerly `NVIDIA_GSF`) states that "`ai_context`, dimensions, synonyms and custom extensions have no Auto Ontology equivalent and are dropped on export"; import embeds the native document in an extension so the reverse direction keeps IDs and SQL ([converter README](https://github.com/apache/ossie-converters/blob/main/nvidia/README.md)). \[F\] dbt's Ossie support likewise drops unsupported metric constructs with warning I078 rather than failing ([dbt docs](https://docs.getdbt.com/docs/build/ossie-semantic-models)). \[F\] The spec supports both dataset-scoped and model-scoped metrics; the losses we saw (every dataset-scoped metric) are converter limits, not spec limits.

**Industry pattern \[I\].** No vendor makes certification portable: Cortex keeps verified queries in the semantic view, Genie in the agent's trusted assets, QuickSight as reviewed answers, ThoughtSpot as reference questions. Certification is a **governance record owned by the serving platform**, not a property of the interchange format. S4 failing is therefore expected, and the fix is architectural, not a request upstream.

### 3.6 G6: why our semantic model did not lift accuracy

\[E\] Google reports, from internal tests only, that Looker's semantic layer cuts natural-language query errors "by as much as two thirds"; the mechanism is that the model calls the semantic layer's API and "Looker executes based on built-in SQL constructs", **it does not write SQL** ([Google Cloud blog](https://cloud.google.com/blog/products/business-intelligence/how-lookers-semantic-layer-enhances-gen-ai-trustworthiness)). \[F\] Google also advises scoping an agent to one or a few related Explores to reduce ambiguity ([best practices](https://docs.cloud.google.com/looker/docs/conversational-analytics-looker-best-practices?hl=en)).

**Implication \[I\].** Arm B gave the model the Ossie model *as context* and still let it write SQL: it gained caution (wrong answers 3.7% against C's 17.7%) but not accuracy. The industry's accuracy gain comes from **constraining the output** to metric and dimension selection. That is exactly ADR 0016's planned `query_metric` path, which P0 did not test.

## 4. Cross-industry patterns

| Pattern | Where it comes from | What it says for the gateway |
| --- | --- | --- |
| **Learned deferral as a wrapper** | Clinical AI: CoDoC (*Nature Medicine* 2023) learns per case whether to trust the model or the clinical workflow, cutting false positives 5–15% at equal false negatives in TB triage, **without rebuilding the underlying models** ([paper](https://link.springer.com/article/10.1038/s41591-023-02437-x)) \[F\] | A refusal stage can wrap any engine (B, A2, future), so it is an engine-neutral gateway feature |
| **Defer with guidance, not a bare "no"** | Guided deferral in healthcare: deferred cases come with the model's partial reasoning ([arXiv 2406.07212](https://arxiv.org/abs/2406.07212)) \[F\] | A refusal should say *what is missing* (the schema elements a triage step found absent), which turns refusals into clarifications |
| **Abstain only when the human does better** | Glaucoma-screening deferral work treats abstention as a decision about the downstream human, not a bare reject ([arXiv 2605.08024](https://arxiv.org/pdf/2605.08024)) \[F\] | Over-refusing is a cost too; tune the triage threshold on the penalty curve, not on refusal rate alone |
| **The unanswered list is the roadmap** | BI: QuickSight's unanswerable filter, ThoughtSpot coverage gaps \[F\] | Log every refusal and clarification with its reason; authors turn them into verified queries |
| **Integration beats accuracy for adoption** | LinkedIn SQL Bot: adoption rose 5–10x once embedded in their DARWIN platform ([summary](https://www.zenml.io/llmops-database/building-a-production-text-to-sql-assistant-with-multi-agent-architecture)) \[E\] | Supports ADR 0016's choice of native tools inside Neuron over a standalone app |

## 5. Design opportunities

Each one is testable on the P0 bench (D1–D3, the scorer, saved outputs) before any P1 code.

1. **Triage, then write (G1, G2).** \[R\] Run arm B's refuse-or-clarify decision as a gate, and send only questions B would answer to A2's generator. Method: an offline counterfactual from the saved per-question outputs (no new model calls), scored by the existing scorer with Wilson intervals. This tests the decision record's main observation directly. Caveat: it assumes B's decision and A2's SQL are independent of each other's context, so a live confirmation run must follow. **Result (D24, [spike log section 11](../../../releases/data-gateway-p0/design-spike-log.md)):** on D3, accuracy 86.5%, wrong answers 5.9%, refusal 83.3%, p95 35.2 s if run in parallel; still short of gate 2 on wrong answers and refusal, and on D1 the gate removes A2's gain because B over-refuses there.
2. **Schema-relevance refusal with reasons (G1, cross-industry).** \[R\] Ask the triage step to name the catalog elements a question needs; refuse when one is absent, and return that list (Han et al.; guided deferral). Limit: it catches questions about things the schema lacks, not values the data lacks. D3 has both kinds (K-U-018 to K-U-021 ask about a skill, a department and a person with zero rows), so value checks (an evidence query returning 0) must stay alongside it. **Result (D25, [spike log section 12](../../../releases/data-gateway-p0/design-spike-log.md)):** every unanswerable question that leaked past B's gate named a missing value, so this was built as a value check: the model lists the values, and the gateway looks each up under the persona. On D3, accuracy 86.5%, wrong answers 4.0% and refusal 91.7% are met together for the first time (point estimates), with no answerable question refused; the extra call puts p95 at 57.8 s even in parallel. On held-out D2, the first version falsely refused 4.6% of units (2.2% after fixing a lookup defect seen there). **Live (D26, D27, [section 14](../../../releases/data-gateway-p0/design-spike-log.md)):** with the values named in B's own call, the live run matches the offline estimate on a 199-unit D3 sample. On a fresh set written before the run, refusal is 90.0% and wrong answers 0.4%, but 19.2% of answerable units go unanswered, 14 of them because the value is outside the caller's regions, where the data's convention expects 0. The free tier's rate limits make latency unmeasurable.
3. **Two-provider agreement as the confidence signal (G2).** \[R\] Once S1 has a non-NVIDIA endpoint, compare result sets from two providers; disagreement means clarify or refuse. Measure on D3 against the 5% wrong-answer threshold.
4. **Author-declared clarification triggers (G3).** \[R\] Add a small `clarify` section to the semantic model (trigger, missing detail, question, options), following Genie's guidance, and score D3's ambiguous questions. Keep it in Neuron's catalog, since Ossie has no slot for it outside `ai_context`.
5. **Verified-query fast path (G4).** \[R\] Match certified questions before the engine runs. Report p95 separately for the fast path and the generated path, as QuickSight separates reviewed answers.
6. **Certification as a Neuron catalog record (G5).** \[R\] Key certification by stable metric or query ID in Neuron's catalog; mirror it into Ossie as `nonportable_extensions` with `vendor_name: neuron` for Ossie-to-Ossie exchange; accept that Auto Ontology export drops it. Feeds the pending ADR 0016 correction on certification (D13, F11).
7. **Penalty-based reliability score as a diagnostic (evaluation).** \[R\] Report TrustSQL-style penalty scores alongside B8, never instead of it, so engine comparisons weigh a wrong answer against a refusal in one number.
8. **`query_metric` arm (G6).** \[R\] Add a fifth arm where the model selects metrics, dimensions and filters only, and the gateway compiles SQL. It is the industry's main accuracy lever and the one ADR 0016 path P0 never measured.

## 6. Key takeaways

**Adopt.**
- Triage as a separate stage (Cortex; TrustSQL pipelines).
- Unanswered and clarified questions as an author work queue (QuickSight, ThoughtSpot).
- Verified answers as the fast and most accurate path (all four vendors).

**Improve.**
- Refusals that explain what is missing (Han et al.; guided deferral).
- Clarification as authored, tested data, not a prompt instruction (Genie).
- Certification owned by Neuron's catalog, not the interchange format (Ossie).

**Explore.**
- Two-provider agreement for confidence, which needs S1's endpoint.
- Small specialised SQL models (Arctic-Text2SQL-R1) for the latency of a generated path.
- A `query_metric` arm.

**Avoid \[I\].**
- Expecting a better prompt alone to close refusal or clarification. The benchmarks show the best frontier models struggle (BIRD-INTERACT 8.67%).
- Self-consistency on one provider as the confidence signal (AUROC 0.61–0.68).
- Cheap-first cascades while p95 is a gate.

**Limits of this study.**
- Each vendor claim is documented behaviour, not an audited outcome.
- Google's two-thirds figure is internal.
- The selective-prediction and cascade papers from 2026 are preprints.
- No source reports a production refusal rate comparable to our 90% threshold, so we cannot say where industry products actually sit on it.

## Sources

- **Products.**
  - Snowflake Cortex Analyst: [behind the scenes](https://www.snowflake.com/en/blog/engineering/snowflake-cortex-analyst-behind-the-scenes/), [REST API](https://docs.snowflake.com/user-guide/snowflake-cortex/cortex-analyst/rest-api), [launch](https://www.snowflake.com/en/blog/cortex-analyst-ai-self-service-analytics/).
  - Databricks Genie: [talk to Genie](https://docs.databricks.com/aws/en/genie/talk-to-genie), [best practices](https://docs.databricks.com/aws/en/genie/best-practices), [community answer](https://community.databricks.com/t5/generative-ai/can-genie-ask-clarifying-questions/m-p/125575).
  - Amazon Quick Sight: [topic performance](https://docs.aws.amazon.com/quick/latest/userguide/topics-performance.html), [verifying answers](https://docs.aws.amazon.com/en_us/quicksight/latest/user/quicksight-q-topics-verifying.html).
  - ThoughtSpot: [coaching](https://docs.thoughtspot.com/cloud/latest/spotter-coaching-options), [after coaching](https://docs.thoughtspot.com/cloud/latest/spotter-coach-after).
  - Looker: [semantic layer blog](https://cloud.google.com/blog/products/business-intelligence/how-lookers-semantic-layer-enhances-gen-ai-trustworthiness), [best practices](https://docs.cloud.google.com/looker/docs/conversational-analytics-looker-best-practices?hl=en).
  - Microsoft Fabric: [evaluate a data agent](https://learn.microsoft.com/en-us/fabric/data-science/evaluate-data-agent).
  - LinkedIn SQL Bot: [summary](https://www.zenml.io/llmops-database/building-a-production-text-to-sql-assistant-with-multi-agent-architecture).
  - Uber: [QueryGPT](https://www.uber.com/blog/query-gpt/).
- **Interchange.**
  - Apache Ossie: [spec 0.3.0.dev0](https://raw.githubusercontent.com/apache/ossie/main/core-spec/spec.md), [converters](https://github.com/apache/ossie-converters), [Auto Ontology converter](https://github.com/apache/ossie-converters/blob/main/nvidia/README.md).
  - [OSI announcement](https://www.snowflake.com/en/blog/open-semantic-interchanges-specs-finalized/).
  - [dbt Ossie models](https://docs.getdbt.com/docs/build/ossie-semantic-models).
- **Research.**
  - Refusal and triage: [TrustSQL](https://arxiv.org/abs/2403.15879), [Han et al. COLING 2025](https://aclanthology.org/2025.coling-main.706.pdf), [Query Carefully](https://arxiv.org/abs/2512.21345).
  - Clarification and ambiguity: [PRACTIQ](https://arxiv.org/abs/2410.11076), [AMBROSIA](https://arxiv.org/abs/2406.19073), [BIRD-INTERACT](https://arxiv.org/abs/2510.05318), [CLARITY](https://aclanthology.org/2026.acl-industry.86.pdf).
  - Confidence: [Somov and Tutubalina](https://arxiv.org/abs/2501.09527), [Richardson](https://arxiv.org/abs/2607.06799), [governed confidence](https://arxiv.org/pdf/2610.17256).
  - Small SQL models: [Arctic-Text2SQL-R1](https://arxiv.org/abs/2505.20315).
  - Cascades: [UCCI](https://arxiv.org/abs/2605.18796), [escalation signals](https://arxiv.org/pdf/2610.07354).
- **Cross-industry.**
  - Healthcare deferral: [CoDoC](https://link.springer.com/article/10.1038/s41591-023-02437-x), [guided deferral](https://arxiv.org/abs/2406.07212), [glaucoma deferral](https://arxiv.org/pdf/2605.08024).
