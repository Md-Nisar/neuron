# Data Analytics Agents — Landscape and Prior Art for Neuron

Oct 28, 2026 · @Md Nisar Ahmed

## Summary

**This is Neuron's reference on open-source data-analytics agents: what each one is, how it is licensed, what its vendor keeps behind a paid tier, and what Neuron's Data Agent should learn from it.** It covers nao, Wren AI, Cube, Vanna, DB-GPT, PandasAI, Lightdash, Metabase, Chat2DB, Dataherald and MindsDB, plus three closed-source products studied as design references: Omni (section 5), Snowflake Cortex (section 6) and Databricks Genie (section 7). nao, which started this review, keeps its detailed write-up in Appendix A.

**Decision it supports (28 Oct 2026): Neuron builds its own Data Agent, including row-level security, column masking and the other enterprise data controls, and adopts none of these products as a backend.** They are reference designs and benchmarks. Open (Apache, MIT, BSD) parts may be studied and adapted under the clean-room rules; commercially licensed parts are off-limits. The build plan and the clean-room rules are in the [Neuron Data Agent assessment](../proposals/NEURON_DATA_AGENT_ARCHITECTURE_ASSESSMENT.md), sections 5 and 6.

**The pattern across the market:** almost every product here is open core. The agent and the connectors are open; per-user data security, SSO and often the AI agent itself are paid. Two projects worth singling out: Vanna (MIT) offers per-user query rewriting as an open hook, and Cube Core (Apache 2.0) has open row-level access policies.

**Labels.** **\[F\]** verified in the project's repository (license files fetched 28 Oct 2026) or official docs · **\[A\]** assumption needing validation · **\[R\]** recommendation. License readings are technical, not legal advice.

## 1. Landscape at a glance

**Most relevant to Neuron: Cube Core (open access policies), Vanna (Python, open per-user hook), Wren AI (semantic context layer) and nao (complete reference product).** The rest are useful for single ideas or are a poor fit.

| Product | What it is | License (verified 28 Oct 2026) | Stack | Relevance to Neuron |
| --- | --- | --- | --- | --- |
| [nao](https://github.com/getnao/nao) | Full analytics agent: context builder, chat UI, bots, MCP server | Apache 2.0 + MIT CLI; 63 files under a commercial license | TypeScript + Python CLI | High: reference product and benchmark (Appendix A) |
| [Wren AI](https://github.com/Canner/WrenAI) | GenBI engine: governed semantic layer and context layer for agents, CLI and MCP, 22+ sources | Apache 2.0 (`core/`, `sdk/`, `skills/`), docs CC BY 4.0; AGPL modules announced for the future | Python CLI + engine | High: semantic and context modelling (MDL) |
| [Cube](https://github.com/cube-js/cube) Core | Semantic layer with access policies, query rewrite, caching, APIs | Apache 2.0 / MIT, whole repository | Node + Rust | High: open row-level policy model; possible dependency |
| [Vanna](https://github.com/vanna-ai/vanna) 2.x | Python agent framework for text-to-SQL with user resolver, group-gated tools, audit, web component | MIT | Python, FastAPI | High: closest stack to Neuron; open per-user rewrite hook |
| [DB-GPT](https://github.com/eosphoros-ai/DB-GPT) | Agentic data assistant: autonomous SQL, Python analysis, skills, sandboxes, reports, AWEL workflows | MIT | Python | Medium: skills and sandboxed analysis ideas |
| [PandasAI](https://github.com/sinaptik-ai/pandas-ai) | Library for natural-language questions over dataframes and SQL | MIT, except `pandasai/ee/` (skills) under an enterprise license | Python | Low: dataframe-centric; last commit Oct 2025 |
| [Lightdash](https://github.com/lightdash/lightdash) | dbt-native BI with AI agents and MCP | MIT, except `packages/backend/src/ee/` (source-available, subscription for production) | TypeScript | Low as code; AI agents and MCP are Enterprise features |
| [Metabase](https://github.com/metabase/metabase) | BI tool | AGPL outside `enterprise/`; Metabase Commercial License inside it | Clojure + JS | Avoid code: AGPL; concepts only |
| [Chat2DB](https://github.com/CodePhiliaX/Chat2DB) | AI SQL client | From v5.3.0, a modified Apache 2.0 limited to internal use (no external product, embedding or OEM without a commercial licence); earlier releases Apache 2.0 | Java + JS | Avoid: not free for product use |
| [Dataherald](https://github.com/Dataherald/dataherald) | NL-to-SQL engine with an "enterprise" API layer | Apache 2.0 | Python | Low: last commit 11 Jul 2024; read-only reference |
| [MindsDB](https://github.com/mindsdb/mindsdb) | Now "MindsHub", a general agent workspace with a data engine | MIT | Python + app | Low: no longer analytics-focused |
| [Omni](https://omni.co/blog/building-omnis-architecture-for-agentic-analytics) | Commercial BI platform with an analytics agent on a semantic layer; MCP connector for Claude | Proprietary; agent-skills repository Apache 2.0 | SaaS (AWS or Azure hosting) | Very high as a design reference: the closest production match to the Data Agent (section 5) |

&#91;A\] Star counts, adoption and production accuracy were not compared; the nao pilot is the only planned benchmark.

## 2. What vendors keep behind paid tiers

**Per-user data security is the feature most often held back. That is why Neuron builds it in-house (Data Agent assessment, section 5) rather than buying it.** Only Cube Core ships a working row-level policy engine in the open, and Vanna ships an open hook where you write your own.

| Product | Row-level security | Column hiding or masking | Corporate SSO | The AI agent itself | Source |
| --- | --- | --- | --- | --- | --- |
| nao | Paid | Paid | Paid (OIDC, Entra ID); Google, GitHub, GitLab login free | Open | `LICENSE-ENTERPRISE`, `types/license.ts`, Enterprise docs |
| Wren AI | Paid | Paid | Not stated | Open engine; GenBI UI and agentic mode paid | Open-core page |
| Cube | Open: `access_policy` row filters in Core | Open: member-level access | Core uses JWT security context; UI SSO is Cloud \[A\] | D3 agents not described as open \[A: Cloud\] | Repo license; RLS docs; D3 announcement |
| Vanna | Open hook (`transform_args`); default no-op, you implement | Same hook | Bring your own (`UserResolver`) | Open | Source: `core/registry.py` |
| Lightdash | Not stated on the Enterprise page | Not stated | Paid except Google Workspace | Paid (AI agents, MCP) | Enterprise features docs |
| PandasAI | None found | None found | None found | Open; `ee/` holds skills | Repo `pandasai/ee/` |
| Metabase | In `enterprise/` \[A\] | In `enterprise/` \[A\] | In `enterprise/` \[A\] | Not reviewed | Repo license |
| Chat2DB | — | — | — | Whole product restricted for external use | Root `LICENSE` |

**Takeaways for Neuron:**

- Every product puts identity-aware enforcement after SQL generation, never in the prompt: Vanna's hook, Cube's query rewrite, nao's sqlglot guards. This confirms the Data Agent's rewrite layer.
- Vendors charge for policy administration, SSO and audit, not for hard algorithms. Neuron already has SSO, roles and audit (Data Agent assessment, section 5.1).

## 3. Product profiles

**Each profile says what the product does well, what is open, and what Neuron should take or leave.** nao's profile is Appendix A.

### 3.1 Wren AI

- **What it is.** \[F\] An open-source GenBI engine that gives existing agents (Claude Code, Cursor, MCP clients, LangChain) a governed semantic layer and an AI context layer: approved metric definitions, enums, units, joins, worked examples, and knowledge from docs. Definitions live in Git. Installed as `pip install wrenai`, with agent skills via `npx skills add Canner/WrenAI`.
- **Open vs paid.** \[F\] Open: the context engine (MDL modelling, text-to-SQL pipeline, 20+ connectors, CLI and MCP server), described as free for individuals. Paid: user and group access control, row- and column-level security, audit, GenBI UI, dashboards, embedded APIs, agentic mode.
- **Take.** MDL as a model for the Data Agent's catalog format; "business definitions in Git" plus worked examples; the agent-skills packaging.
- **Leave.** Commercial-tier features; any future AGPL path.

### 3.2 Cube (Cube Core)

- **What it is.** \[F\] A universal semantic layer. Every file in the repository is Apache 2.0 or MIT. Its access policies give each group row-level filters built from user attributes (for example a manager sees rows where `country` equals their own), plus member-level access. User attributes come from the security context.
- **Open vs paid.** \[F\] Data Access Policies were announced for "Cube and Cube Cloud"; the visual policy editor is Cloud. \[A\] D3, Cube's agentic analytics product (announced 2 June 2025), is not described as open source.
- **Take.** The access-policy model (group → row filters → member access) as the shape of Neuron's policy files; the query-rewrite hook as the enforcement point.
- **Decide in Phase 0.** Whether to run Cube Core itself in front of MySQL instead of building the catalog and row-security engine (a one-week spike).

### 3.3 Vanna 2.x

- **What it is.** \[F\] An MIT Python framework for text-to-SQL agents. A `UserResolver` turns the request (JWT, cookie) into a `User` with group memberships. The `ToolRegistry` hides tools from users outside their `access_groups`. A `transform_args` hook rewrites tool arguments per user before execution; its docstring names "applying row-level security (RLS) to SQL queries" and "redacting sensitive fields". The default does nothing. It also has audit logs, per-user rate limits and a `<vanna-chat>` web component. Last commit seen: 2 Feb 2026.
- **Take.** The cleanest open example of where per-user enforcement belongs: between the model's tool call and execution, keyed on a resolved user. It is the same place as Neuron's rewrite layer, and it is Python, so it is the most direct code reference.
- **Leave.** Its RLS is a hook, not an implementation; Neuron still writes the rewriter.

### 3.4 DB-GPT

- **What it is.** \[F\] An MIT agentic data assistant. It connects to databases, files, warehouses and knowledge bases; writes SQL autonomously; runs Python analysis and reusable skills in sandboxes; and produces charts, dashboards and HTML reports. It also offers agents, AWEL workflows and RAG.
- **Take.** Ideas for a later phase: sandboxed Python for analysis beyond SQL, report generation, reusable analysis skills.
- **Leave.** Autonomous SQL without a spec-first gate.

### 3.5 Lightdash

- **What it is.** \[F\] dbt-native BI. MIT outside `packages/backend/src/ee/`, which is source-available and needs a subscription in production. AI agents, MCP, multi-agent Slack channels, custom roles, SCIM and most SSO providers need a license key; Google Workspace SSO is on all plans.
- **Take.** Its use of dbt metrics as the semantic layer is a reference if entomo's data team adopts dbt. **Leave** the `ee/` code.

### 3.6 Others

- **PandasAI** \[F\]: MIT library for questions over dataframes; only `ee/` (skills) is commercial; last commit 28 Oct 2025. Low relevance.
- **Metabase** \[F\]: AGPL core and a commercial `enterprise/` directory. Read its docs for ideas, but do not copy code: AGPL obligations would reach Neuron.
- **Chat2DB** \[F\]: from v5.3.0 the license forbids external products, embedding and OEM without commercial authorization. Do not use.
- **Dataherald** \[F\]: Apache 2.0 NL-to-SQL engine with a separate "enterprise" API layer; inactive since July 2024. Safe to read; do not depend on it.
- **MindsDB** \[F\]: the repository now presents MindsHub, a general agent workspace. No longer an analytics-agent reference.

## 4. Patterns to adopt, by Data Agent component

**\[R\] Each Data Agent component has at least one open reference; none needs a commercially licensed source.** Section numbers refer to the [Data Agent assessment](../proposals/NEURON_DATA_AGENT_ARCHITECTURE_ASSESSMENT.md).

| Data Agent component | Pattern to adopt | Open reference | How to use it |
| --- | --- | --- | --- |
| Semantic layer and catalog (§4.3) | Business definitions, enums, joins and worked examples as files in Git | Wren AI MDL; nao context files and `RULES.md`; Cube data model | Concepts; design our own YAML |
| Context quality (§4.3, §7.3) | Tests that grade context changes before release | nao `nao test`; Wren worked examples | Concepts |
| Governed-only access (§4.3) | A mode where the warehouse is reachable only through approved metrics | nao semantic-layer "exclusive" mode | Concept |
| User resolution (§5.2) | Resolve the request into a user with groups before any tool runs | Vanna `UserResolver` | Concept; Neuron's JWT path already does this |
| Tool gating (§4.4) | Hide tools from users without the group | Vanna `access_groups`; Neuron scopes | Already in Neuron |
| Row filters and masks (§5.3, §5.4) | Policies per object: group + user attributes → row filters and column access | Cube `access_policy`; Trino OPA plugin interface; Apache Ranger masks | Concepts and interface shape |
| Enforcement point (§5.4) | Rewrite between the tool call and execution, keyed on the user | Vanna `transform_args`; Cube query rewrite | Concept |
| SQL guards (§5.4) | sqlglot checks for allow-listed tables, excluded columns and row predicates | nao `cli/nao_core/config/databases/*_guard.py` (MIT) | Code may be adapted, keeping the MIT notice |
| Long analyses (§4.2) | Ask, then poll for a running job | nao `ask_nao` / `get_nao_answer` | Concept |
| Seeding the catalog | Import metric definitions from existing BI tools | nao Metabase and Tableau skills; Lightdash dbt metrics | Concepts |
| Later phases | Sandboxed Python analysis, report generation, reusable analysis skills | DB-GPT | Concepts |
| Charts (§4.2) | Spec-first charts rendered by the client | Microsoft Flint (MIT) | Use directly |

**Reuse rules** are in Data Agent assessment section 6.2. In short: Apache, MIT and BSD code may be adapted with notices and recorded provenance. Commercial, source-available and AGPL code is not read by implementers or copied.

## 5. Omni (commercial reference)

**\[F\] Omni is a closed-source BI platform whose analytics agent sits on a semantic layer. The agent never writes SQL: it writes an abstract query over curated "topics", and the semantic layer compiles that to SQL under the user's own permissions.** It is the strongest validation found so far of the Data Agent's spec-first design. It also adds concrete practice on context budgets, value grounding, multi-step analysis and evals. Omni is not open source, so it is a source of concepts only. Its [agent-skills repository](https://github.com/exploreomni/omni-agent-skills) is Apache 2.0 and is the most detailed public description of how the agent is fed and graded.

**Source note.** The linked video is the Code with Claude London session "Building the best agentic analytics harness: Powered by Claude, built with Claude Code" (20 May 2026, given by Omni's co-founder and CTO). \[A\] Its recording could not be read here (YouTube rate-limited the fetch). The session page says only that the talk covers the multi-agent design, tool design and sizing, and how Omni measures the harness, and that Claude Code wrote 99% of the platform's code. The details below come from Omni's own engineering blog, docs and Apache-licensed skills.

&#91;embedded content: Omni agent architecture · coordinator, 3 tools, semantic layer\]

The agent sees metadata, not data, while it builds a query. Results reach a model only in the summarization step, in that subagent's own context.

### 5.1 The agent

- **Coordinator loop.** \[F\] It decides the next tool from the question, earlier results and what has already been tried, so it can retry a failed step or stop when it has a useful answer. For open questions ("How's my sales org doing?") it first writes a visible task list and ticks steps off, then runs several queries and returns a narrative with evidence.
- **Small, sharp tools.** \[F\] A topic picker and query tool choose the curated dataset before building a query. A field-values tool fetches valid values so a filter for "New York" becomes the stored "NYC" instead of returning nothing. A summarization subagent reads results in its own context window so large results do not crowd the coordinator.
- **Reliability before autonomy.** \[F\] Omni's rule is that each tool must "do exactly what it says it does" before the agent gets more freedom. The supports are strict validation of tool inputs and outputs, detectors for malformed state, and integration tests across steps ("after summarizing, don't re-query unless filters changed").
- **Conversation handling.** \[F\] The full conversation (turns, tool calls, data returned) is rebuilt every request. Prior messages are rendered identically each time to keep prompt caching effective, and full result sets are never put into context.
- **Several agents share one context system.** \[F\] The Omni Agent, the Workbook, Dashboard and Modeling agents, AI summaries and AI filters all read the same model context.
- **Skills.** \[F\] Saved slash-command workflows (`/lookup-opportunity`, period-over-period GL variance) that can call MCP servers. "The skill controls the workflow. The semantic layer controls the data."

### 5.2 The semantic and context layer

- **Topics.** \[F\] Curated datasets with a base view, governed joins and a field list. The query tool targets a topic. Queries not built on a topic are not available to restricted users. Raw SQL exists but is for privileged ad-hoc use.
- **Abstract query shape.** \[F\] `fields` (`view.field`, with time grains such as `created_at[month]`), typed `filters` (`{type, kind, values}`), `sorts`, `limit`, `pivots`, table `calculations` as an AST, and the `topic`. This is a close match to the Data Agent's `AnalysisSpec`.
- **Layered AI context.** \[F\] `ai_context` at the model, topic, view and field levels; `synonyms`; `sample_values` and `all_values` for categories; `sample_queries` with the user prompt and the correct query; `ai_fields` to curate what the AI sees; `ai_chat_topics` to allow-list topics; topic `extends` for AI-specific variants; reusable `constants`. Context can be scoped to a model tier (`smartest`, `standard`, `fastest`) or to a specific agent, and personalised with user attributes (`{{omni_attributes.region}}`).
- **Context budgets and pruning.** \[F\] About 75K characters per topic's field definitions and about 100K for topic-selection summaries. When over budget, field properties are dropped in a fixed order (`all_values` → `sql` → `sample_values` → `description` → `group_label` → `label` → `aggregate_type` → `data_type` → `synonyms`). `ai_context` is never pruned, so bloated context can starve field metadata and fail the request. Omni's guidance: few, short, non-conflicting instructions. Context is "guidance, not instruction", and model-level context does not reliably override topic context.
- **Feedback loops.** \[F\] An AI usage dashboard shows what people ask; "AI model suggestions" propose context improvements; dbt metadata (including `accepted_values`) can be imported. Model changes are made on branches.

### 5.3 Access and data handling

- **Access grants** \[F\]: attribute-based visibility for topics, views and individual fields (`user_attribute` + `allowed_values`), composable with `|` and `&`, with model-wide defaults. Composite topics can only restrict further.
- **Access filters (row level)** \[F\]: per topic, `field` + `user_attribute`, with `values_for_unfiltered` for bypass roles; `default_topic_access_filters` model-wide. A user with no value for the attribute gets an error, not all rows.
- **What the model sees** \[F\]: for query generation, metadata only (prompt, query metadata, `ai_context`, the selected topic's field metadata). For summarization, query metadata plus a CSV of the results. Data is not used for training.
- **Models** \[F\]: by default hosted on Amazon Bedrock (AWS deployments) or Microsoft Foundry (Azure deployments); bring-your-own-key for Anthropic, Vertex AI (Claude), Snowflake Cortex (Claude), OpenAI, Grok and Databricks.
- **MCP connector** \[F\]: Claude can query Omni through MCP with OAuth, so each user is bound to their own Omni permissions.

### 5.4 Evals

- &#91;F\] **Prompt sets** of up to 25 natural-language prompts per model, each with an optional `expectation` that only the judge sees.
- &#91;F\] **Eval runs** execute each prompt as a full agentic job, against `main` or a model branch.
- &#91;F\] **The accuracy judge** reads the whole conversation (topic choice, queries, results, final answer) and returns pass or fail with a rationale. It targets high-impact errors: hallucination, date and time filtering, row-limit handling, mental math, period-over-period mistakes and wrong topic. It ignores wording.
- &#91;F\] **Each result records** cost, judging cost and AI time.
- &#91;F\] **The workflow:** A/B runs of `main` against a branch, listing regressions as well as net gain; add a regression prompt for every wrong answer; draw prompts from real usage.

### 5.5 What this means for Neuron

Omni confirms three Data Agent choices: an abstract query instead of SQL, permissions applied in the semantic layer rather than in prompts, and rows kept out of the main model's context. It also adds practices the Data Agent should adopt: value grounding, a bounded multi-step analysis loop, explicit context budgets, layered context, and trajectory-level judged evals. The changes are listed in the [Data Agent assessment](../proposals/NEURON_DATA_AGENT_ARCHITECTURE_ASSESSMENT.md), section 4.7. Licensing: Omni's product is proprietary, so take concepts only. The Apache 2.0 skills repository may be quoted or adapted with notice.

## 6. Snowflake Cortex (commercial reference)

**\[F\] Snowflake splits the problem in two. Cortex Analyst turns a question into SQL over a semantic view through a multi-stage, multi-model pipeline. Cortex Agents is the plan, use tools, reflect loop on top, and Snowflake now recommends it over calling Analyst directly.** Everything runs inside the customer's Snowflake account under the caller's role. Row access and masking policies set on the underlying tables carry through.

&#91;embedded content: Cortex Analyst pipeline · 6 stages, 3 parallel generators\]

Snowflake claims over 90% SQL accuracy on real-world use cases and close to 2× the accuracy of single-shot generation with GPT-4o. These are vendor figures on an undisclosed internal benchmark.

### 6.1 Cortex Analyst: how a question becomes SQL

- **Classification first.** \[F\] Questions that are ambiguous ("best product last year" when several metrics could mean "best") or not answerable with SQL are rejected rather than guessed, and the user gets similar questions that can be answered.
- **Feature extraction.** \[F\] Traits such as time series, period-over-period or ranking select smaller, question-specific prompts for the generators, "to reduce the chance the model forgets instructions".
- **Context enrichment.** \[F\] Verified queries are retrieved by semantic similarity. Matching literals come from a Cortex Search service attached to a column ("USA" → "United States of America").
- **Ensemble generation.** \[F\] Several generators, each on a different model, write SQL against a simplified logical schema. Post-processing maps it to physical tables. The engineering blog names Llama and Mistral models; the current docs list Claude Sonnet 4.6 and 4.5, GPT 4.1, Arctic Text2SQL R1.5 and Mistral Large 2 + Llama 3.1 70B, choosing the best model the role may use.
- **Compiler-checked correction, then synthesis.** \[F\] Candidates are checked with Snowflake's own SQL compiler (catching hallucinated tables, columns and functions) and looped back for fixes. A synthesizer picks or merges the final query.
- **Stateless multi-turn.** \[F\] The REST API takes the whole `messages` history each call, so cost grows with conversation length. It cannot see results of earlier queries.

### 6.2 The semantic view

- **A first-class database object.** \[F\] It holds logical `tables` (with `base_table`, `primary_key`), `relationships`, `dimensions`, `time_dimensions`, `facts`, `metrics`, and filters marked `labels: [filter]`. Columns carry `synonyms`, `description`, `sample_values`, `is_enum` and an optional `cortex_search_service` for literal lookup.
- **Additivity is explicit.** \[F\] Metrics can declare `non_additive_dimensions`, for example a balance or headcount that must not be summed across dates. Facts and metrics can be `private_access` (helpers hidden from queries).
- **Guidance and verified answers.** \[F\] `module_custom_instructions` are split into `sql_generation` and `question_categorization`. `verified_queries` hold question, SQL, `verified_by`, `verified_at`, and `use_as_onboarding_question` (suggested starter questions).
- **Managed as code.** \[F\] Snowflake recommends YAML or DDL in Git, CI/CD that runs accuracy checks before deploying, rollback by redeploying a known-good file, and one schema per business domain.

### 6.3 Cortex Agents

- **Loop.** \[F\] Plan (clarify, split into subtasks, choose tools) → use tools → reflect (ask, call another tool, or answer) → monitor.
- **Tools.** \[F\] Cortex Analyst, Cortex Search (unstructured), analytical search over documents, sandboxed Python, data-to-chart, stored procedures and UDFs as custom tools, agent skills, MCP connectors, other agents' toolsets, web search.
- **State and spend.** \[F\] Server-side threads hold conversation state. Each run streams its reasoning, tool calls and reflections as events. An orchestration budget caps one run, with resource budgets and per-user quotas on top. Orchestration and Analyst are billed by tokens.
- **Exposure.** \[F\] A Snowflake-managed MCP server exposes agents and tools to outside clients.

### 6.4 Security and governance

- **Roles.** \[F\] Callers need `SNOWFLAKE.CORTEX_USER` or a narrower role (`CORTEX_ANALYST_USER`, `CORTEX_AGENT_USER`), privileges on the agent object, and privileges on every object its tools touch. A caller who lacks a tool's privileges still gets a run, using only the tools they can access.
- **Row and column security.** \[F\] Row access and masking policies cannot be set on a semantic view itself. Set them on the underlying tables and columns; they then propagate and are enforced. Cortex Agents need the executing role to have `SELECT` on both the semantic view and its base tables.
- **A metadata leak to avoid.** \[F\] Sample values in a semantic view are stored as metadata and are not masked; anyone who can run `GET_DDL` sees them. Snowflake's advice: use representative, non-sensitive sample values.
- **What the model sees.** \[F\] The docs say semantic-model metadata (names, types, descriptions) is used for SQL generation and the SQL runs in the customer's warehouse. \[A\] Whether results ever reach a model is not stated for Analyst.
- **Model control.** \[F\] Admins can restrict which models are allowed per role (this applies across all Cortex features) and can switch Analyst off account-wide.

### 6.5 Evals

- **Ground truth.** \[F\] Verified queries are the ground truth. During an eval run, the selected ones are removed from a temporary copy of the semantic view, so they cannot leak into generation.
- **Scoring.** \[F\] Generated SQL is executed and compared with the expected results by a versioned LLM judge (`sql_correctness` v1–v3). Each major version pins a judge model, prompt, rubric and thresholds, so scores across versions are not comparable.
- **Reporting and fixes.** \[F\] Reports cover accuracy, regressions (previously correct, now failing) and latency per query. An "Improve" step proposes semantic-view changes from the failures.
- **Advice.** \[F\] Use absolute dates in verified queries; "last quarter" drifts.

## 7. Databricks Genie (commercial reference)

**\[F\] A Genie Agent (formerly "Genie space") is a curated, author-owned workspace over at most 50 Unity Catalog tables, views or metric views. A per-agent knowledge store teaches it the business, and it writes read-only SQL that runs on a SQL warehouse. Data access is always checked against the end user's own Unity Catalog identity.** Chat mode answers with a single query; Agent mode (formerly Research Agent) plans several queries and returns a cited report.

### 7.1 How Genie answers

- **Inputs to SQL generation.** \[F\] Unity Catalog metadata (table names, descriptions, primary and foreign keys); the relevant columns; knowledge-store context; the most relevant example SQL; all attached SQL functions; general instructions; and chat history, trimmed from the oldest message when tokens run short.
- **Inspect.** \[F\] In public preview, a second pass reviews a generated query's filters, date ranges, joins and aggregations, and proposes an improved version.
- **Agent mode.** \[F\] Breaks a question into steps, runs several queries, and can also read files in Unity Catalog volumes and call MCP connectors. A "Flash" option trades depth for speed. A Conversation API exposes Genie to applications.

### 7.2 The knowledge store

| Component | What it does | Limit |
| --- | --- | --- |
| Table and column descriptions, synonyms, hidden columns | Business vocabulary; hide duplicate or noisy columns (hiding changes nothing in the data or permissions) | Shares the 200-snippet limit |
| Join relationships | Declared cardinality (many-to-one, one-to-many, one-to-one); primary and foreign keys are saved automatically | Shares the 200-snippet limit |
| SQL expressions | KPIs, filters and fields applied exactly as written, "more consistent than text instructions" | Shares the 200-snippet limit |
| Prompt and entity matching | Maps user words to stored values for string columns | 120 columns × 1,024 distinct values, each ≤ 127 characters |
| General instructions | Global rules only (fiscal calendar, formats) | Counts as 1 of 100 instructions |
| Example SQL | Reference answers titled with the typical phrasing, plus usage guidance | Each counts as 1 of 100 instructions |
| Trusted assets | Parameterized queries and Unity Catalog SQL functions. Answers that use them are marked as verified; functions keep their logic hidden from Genie | Each counts as 1 of 100 instructions |
| Benchmarks | Test questions, never used as context | Up to 500 per agent |

&#91;F\] Databricks' tuning advice: put subset-specific guidance in example SQL, functions or column comments rather than in general instructions. Remove conflicting guidance, since Genie is non-deterministic. Review the joins and expressions Genie itself suggests from thumbs-up feedback before accepting them.

### 7.3 Metric views

- &#91;F\] A Unity Catalog object defined in YAML: `source`, `joins` (with cardinality, nestable for snowflake schemas), a global `filter`, `fields` and `measures`, each with `comment`, `display_name` and up to 10 `synonyms`.
- &#91;F\] Window measures handle running and trailing calculations, and `semiadditive: first|last` handles snapshot metrics such as headcount or balances.
- &#91;F\] Queried with `MEASURE()`. An agent's context can be exported as a metric view.
- &#91;F\] Metric-view expressions cannot use invoker-dependent functions (`current_user()`, `is_member()`), so per-user security belongs on the base tables, not in the metric definition.

### 7.4 Security and governance

- **Two identities.** \[F\] Compute runs on the author's embedded warehouse credentials, so users need no warehouse rights. Data access always uses the end user's identity: their Unity Catalog grants, row filters and column masks apply. A question about data they cannot see returns an empty response, and every query is attributed to the end user in query history.
- **Sharing levels.** \[F\] CAN MANAGE, CAN EDIT, CAN RUN and CAN VIEW, to users, groups or the whole account. Users also need `SELECT` on the underlying objects.
- **Value matching versus security.** \[F\] A row filter removes the whole table from prompt matching, and a column mask removes that column. Entity matching should be turned off for views over filtered or masked tables and for dynamic views. This is how Genie stops value dictionaries from leaking rows a user may not see.
- **What the model sees.** \[F\] The prompt, table names and descriptions, relevant values, instructions, example SQL and SQL functions. Models are Databricks-hosted open models, or (if the admin enables "partner-powered AI") Azure OpenAI, OpenAI on Databricks or Anthropic on Databricks, through zero-data-retention endpoints. Data is not used to train foundation models, and processing can be pinned to the workspace's region.
- **Storage.** \[F\] Responses are stored in the control plane, encrypted with AES-256. Conversations are either reviewable by agent managers or private (managers see only prompts).

### 7.5 Benchmarks and feedback

- **Chat-mode scoring.** \[F\] Each benchmark question may carry a SQL answer, and the generated query's result set is compared with it. Row order is ignored and numbers match at 4 significant digits, comparing up to 5,000 rows. Empty results, errors, extra columns, or a different single value count as Bad; anything uncertain goes to manual review.
- **Agent-mode scoring.** \[F\] An LLM judge grades against a per-question "evaluation note".
- **Practice.** \[F\] Write two to four phrasings of each common question with the same SQL answer. Each benchmark runs as a fresh conversation. Detailed results are kept for one week.
- **Feedback loop.** \[F\] Users answer "Is this correct?" with Yes, Fix it or Request review. Managers review flagged answers and correct them. A weekly digest reports volume, active users and thumbs up or down.

### 7.6 Three commercial references compared

|  | Omni | Snowflake Cortex | Databricks Genie |
| --- | --- | --- | --- |
| What the model writes | Abstract query over a topic | SQL against a logical schema, mapped to physical tables | SQL, guided by knowledge store and trusted assets |
| Scope unit | Topic (curated dataset) | Semantic view (one per domain schema) | Genie Agent (≤ 50 tables or metric views) |
| Getting values right | Field-values tool | Cortex Search on a column | Entity matching (120 columns × 1,024 values) |
| Verified answers | Sample queries | Verified queries (also starter questions) | Trusted assets: parameterized queries, SQL functions |
| Ambiguity | Clarify or retry | Classify and reject, suggest answerable questions | Ask a follow-up |
| Per-user security | Access grants and row access filters in the model | Row access and masking policies on base tables | Unity Catalog row filters and column masks; end-user identity |
| Model sees rows? | Only in the summarization step | Not stated for Analyst | Not listed for Genie Agents |
| Multi-step mode | Coordinator with task list | Cortex Agents: plan, tools, reflect; budgets | Agent mode with cited reports |
| Eval method | LLM judge over the full trajectory, branch A/B | Verified queries hidden from context, versioned LLM judge on results | Result-set match (4 significant digits), LLM judge in Agent mode |

### 7.7 What Neuron should learn from Cortex and Genie

**\[R\] Both platforms confirm the Data Agent's direction (governed semantic layer, permissions from the user's identity on base data, metadata-first prompts). They add eight specific practices:**

1. **Reject or clarify before generating.** Classify questions first. For ambiguous ones, return answerable alternatives from the catalog (Cortex), not just a clarifying question.
2. **Question-type prompts.** Detect trend, period-over-period and ranking questions and use small, type-specific prompt sections (Cortex feature extraction).
3. **Compiler in the loop.** Validate every candidate with the database's own parser or `EXPLAIN` before execution and feed errors back once (Cortex). An ensemble of generators is a later option, worth testing only if evals show a gap.
4. **Snapshot metrics are not summable.** Declare semi-additive or non-additive measures in the catalog (Cortex `non_additive_dimensions`, Genie `semiadditive`). This is critical for HR data such as headcount.
5. **Value matching must respect security.** Never build value dictionaries over row-filtered tables or masked columns (Genie). Never store real sensitive values as sample values, since they bypass masking (Cortex).
6. **Trusted, verified answers.** Let authors mark parameterized queries as verified and label answers that used them. Reuse the best ones as starter questions.
7. **Leak-proof evals.** Remove a test question's own verified query from context while it is being evaluated (Cortex). Use absolute dates. Compare result sets order-insensitively with numeric tolerance (Genie). Pin judge versions so scores stay comparable. Write two to four phrasings per question.
8. **Separate compute identity from data identity.** One service connection for compute, with data rights still evaluated per user. Neuron's design reaches the same end through query rewriting and secure views, because MySQL lacks native row security.

These are recorded for study only; adopting any of them into the Data Agent plan is a separate decision.

## Update, 31 Oct 2026: components for an assemble-first build

**\[R\] The Data Agent now assembles open-source components and writes only the gaps** ([Final Design, revision 3](https://claude.ai/artifact/Krtk2Bxg7LnkRXHHmfpFFk)). These are the components checked for that, with licences read from each repository on 31 Oct 2026.

| Component | Licence | What it gives us | Limits found |
| --- | --- | --- | --- |
| [Cube Core](https://github.com/cube-js/cube) | Apache 2.0 (some packages MIT) | Semantic layer with joins, fan-out handling via primary keys, multi-stage and rolling measures; access policies with `row_level`, `member_level` and masking; `context_to_groups` and `query_rewrite` in Core | Cube Cloud maps users to groups automatically; in Core we map the security context ourselves. Semi-additive "last value" needs a snapshot model \[A: confirm in the bake-off\] |
| [Wren core](https://github.com/Canner/WrenAI) | Apache 2.0 by path (`core/`, `sdk/`, `skills/`); `legacy/v1` branch excluded | MDL semantic layer, governed text-to-SQL with plan validation and value profiling, MCP server, 22+ connectors, Rust engine with Python bindings | Row- and column-level security, users and groups, and advanced audit are Enterprise Plus |
| [NVIDIA auto-ontology](https://github.com/NVIDIA/auto-ontology) | Apache 2.0 | Context layer built from metadata: declared and suggested foreign keys, bridge tables, glossary terms, rule-first PII detection, structural SQL comparison; MCP, CLI and API | First commit April 2026, no releases, not accepting contributions; app-level roles only, no row security; PII fallback sends samples to a model |
| [MetricFlow](https://github.com/dbt-labs/metricflow) | Apache 2.0 | Metric engine with semi-additive measures and join resolution | No MySQL adapter, so it is out for the first connector |
| [Presidio](https://github.com/microsoft/presidio) | MIT | Detecting identifiers in text; reversible anonymisation | Detection quality on names in other languages to be tested |
| [OpenDP](https://github.com/opendp/opendp) | MIT | Calibrated noise for aggregates | Needed only if counsel asks for noise |

**Pattern confirmed.** Every engine above that offers governance keeps per-user row and column security, user groups and audit in its paid tier. Neuron writes those parts itself, using these projects and the research in sections 5–7 as references.

## 8. Open questions

- [ ] Does Cube Core's access-policy engine meet the HR row-security needs well enough to run it instead of building one? (one-week spike in Data Agent Phase 0)
- [ ] Is Cube D3 or any part of Wren's agentic mode open source? Not confirmed; treat both as commercial until verified.
- [ ] Does entomo's data team use dbt? If so, dbt metrics (as used by nao and Lightdash) can seed the catalog.
- [ ] For the nao benchmark pilot only: does nao Labs confirm that the default build may run unlicensed, given that Enterprise-marked license-check files execute in every deployment?
- [ ] How does nao score on the golden question set, as a benchmark for the native Data Agent's accuracy and cost per answer?

## Appendix A — nao in depth

The original review of nao (commit `c72f46e`), kept for reference. Its build-or-buy recommendation is superseded by the decision in the summary; the license findings, architecture notes and ideas still apply.

### A.1 License

**\[F\] nao is open core: three licenses in one repository.** Commercial use, modification and self-hosting of the open part are allowed; the enterprise part needs a subscription in production.

| Part | License | Commercial use | Conditions |
| --- | --- | --- | --- |
| Most of the repo (`apps/`, backend, frontend) | Apache 2.0 (`LICENSE`) | Yes, including modifying it and running it inside a paid product | Keep the license and notices; mark changed files; no trademark rights to the name "nao" (Apache §6) |
| `cli/` (`nao-core` on PyPI) | MIT (`cli/LICENSE`) | Yes | Keep the copyright notice |
| 63 source files marked `/* @license Enterprise */` | nao Labs Commercial License (`LICENSE-ENTERPRISE`) | Production use only with a valid Enterprise subscription and acceptance of nao's terms | Development and testing use is free; changes you make to these files belong to nao Labs; no redistribution |

#### A.1.1 What is Enterprise-only

&#91;F\] The signed license key (`NAO_LICENSE`) unlocks seven features, defined in `apps/backend/src/types/license.ts`: `sso`, `row-level-security`, `exclude-columns`, `user-groups` (beyond three), `multi-project`, `white-label`, `user-budget`. \[F\] The docs add per-user identity passthrough to Redshift. Verification is offline; an expired or missing key turns these features off and the rest keeps running as open source.

&#91;F\] The open-source edition includes: the agent and chat UI with every LLM provider; Slack, Teams, WhatsApp, Telegram and Mattermost bots; Google, GitHub and GitLab login; Admin, Context Admin, User and Viewer roles; up to three user groups; and the MCP server.

#### A.1.2 What this means for entomo

- **Fine for:** an internal pilot, a data-team tool with Google/GitHub login, or a deployment where every user may see all the connected data.
- **Needs a subscription:** corporate SSO (OIDC, Entra ID), per-user row filters, hiding sensitive columns, more than three user groups. These are exactly the controls an HR-data product would need, so production use for business users realistically means buying Enterprise or keeping those controls outside nao.
- **Do not** remove or bypass the license checks. Apache 2.0 lets you edit the Apache files, but the checks call into Enterprise files, and working around a vendor's commercial gate creates legal and relationship risk.

#### A.1.3 Points for legal review

1. &#91;A\] The license verifier itself (`license.service.ts`, `license-startup.ts`) is an Enterprise-marked file that runs in every deployment, even unlicensed. The docs clearly intend unlicensed production use as "OSS mode", but the text of `LICENSE-ENTERPRISE` does not carve this out. Get written confirmation from nao Labs.
2. &#91;A\] The terms at `getnao.io/security/terms-and-conditions` could not be fetched from this environment and were not reviewed.
3. &#91;F\] Product analytics go to PostHog by default (`POSTHOG_DISABLED=false` in `.env.example`, EU host). Set `POSTHOG_DISABLED=true` for any deployment that touches company data.
4. &#91;R\] Pricing is quote-based (per company, yearly, by user count and features). Ask for a quote early, as it decides build versus buy.

### A.2 What nao is

**\[F\] nao is a complete analytics-agent product, not a library: a TypeScript server and chat UI, a Python CLI that builds the agent's context from your warehouse and repos, and a single tool-calling agent that writes and runs SQL.** It is built by nao Labs (Y Combinator X25).

#### A.2.1 Architecture

| Layer | What it is | Where |
| --- | --- | --- |
| Context builder | `nao-core` CLI (`init`, `sync`, `test`, `chat`): writes a file tree of table metadata, docs, `RULES.md` and repos that the agent reads | `cli/nao_core/` (Python, MIT) |
| Agent | One tool-calling loop on the Vercel AI SDK (`ai` v6), with subagents, memory, skills and context compaction | `apps/backend/src/agents/` |
| Agent tools | `execute_sql`, `execute_semantic_query`, `read`/`grep`/`list`/`search` over context, `display_chart`, `display_map`, `clarification`, `execute_python` and sandboxed code, `web_search`, `mcp_call`, `story`, `suggest_follow_ups` | `apps/backend/src/agents/tools/` |
| SQL safety | App-level checks: read-only parse (`isReadOnlySqlQuery`), blocked passthrough functions; sqlglot guards in the CLI for allow-listed tables, excluded columns and row-security predicates. Writes possible if an admin turns on "dangerous write permissions" | `apps/backend/src/utils/sql-filter.ts`, `cli/nao_core/config/databases/*_guard.py` |
| Semantic layer | Optional; dbt Semantic Layer (MetricFlow) is the only engine. Modes include "exclusive", where the warehouse is reachable only through the layer | `services/semantic-layer.service.ts` |
| Server and UI | Fastify + tRPC + Drizzle (SQLite or Postgres), React UI, a Python FastAPI helper; Better Auth for login | `apps/backend`, `apps/frontend` |
| Channels | Web chat, Slack, Teams, WhatsApp, Telegram, Mattermost, Discord; scheduled reports; "stories" (shareable dashboards) | `services/` |
| MCP server | Exposes nao to other agents (section 4) | `apps/backend/src/mcp/` |
| Evals | `nao test`: questions with expected SQL in YAML, results panel, context versioning | `cli/`, `services/test-agent.service.ts` |
| Observability | OpenTelemetry traces with optional Langfuse export; PostHog product analytics | `instrumentation.ts`, `.env.example` |

#### A.2.2 Data sources

&#91;F\] 18 warehouse connectors in the CLI, including **MySQL**, Postgres, Snowflake, BigQuery, Databricks, Redshift, ClickHouse, Trino, Athena, MSSQL, Fabric, StarRocks, DuckDB and MotherDuck. LLM providers: OpenAI, Anthropic, Google, Azure, Bedrock, Vertex, Mistral, OpenRouter, Ollama and any OpenAI-compatible endpoint.

#### A.2.3 Maturity

- &#91;F\] About 2.0k GitHub stars, 294 forks and 1,068 commits on `main`; last commit 28 Oct 2026. Very active.
- &#91;F\] Fast-moving surface: the MCP server reports itself as version `0.1.0`, and features ship behind beta flags (for example `BETA_STORY_FILTERS_ENABLED`).
- &#91;F\] Ships skills for migrating from Metabase and Tableau, and for building and auditing context.
- &#91;A\] No independent evidence of production accuracy at enterprise scale was found; the pilot should measure it.

### A.3 nao vs the planned Data Agent

**They overlap on the core job: answering business questions with SQL over the same data. So a second "Analytics Agent" would duplicate the Data Agent rather than add a capability.** nao is broader and ready today. The Data Agent design is narrower, but it is safer by construction and native to Neuron.

| Dimension | nao | Planned Data Agent ([assessment](../proposals/NEURON_DATA_AGENT_ARCHITECTURE_ASSESSMENT.md)) | Better |
| --- | --- | --- | --- |
| Time to first answer | Days (Docker + `nao sync`) | \~8–10 weeks after Neuron v1.0 | nao |
| How SQL is produced | The model writes SQL; the app checks it is read-only | The model writes a typed analysis spec; code compiles SQL from a governed catalog | Data Agent (safer, more consistent) |
| Write protection | App-level parse plus an admin toggle that can allow writes | Read-only DB user plus validator; no write path | Data Agent |
| Semantic layer | dbt MetricFlow, optional | Neuron-owned catalog, required for Tier 1 | Depends on whether dbt is already in use |
| Warehouses | 18 connectors | MySQL via Toolbox (Toolbox supports more) | nao |
| Context engineering | Strong: file-tree context, rules, repos, Metabase/Tableau import, context audit skills | Catalog only | nao |
| Evals | `nao test` with expected SQL | Reference-result accuracy in Neuron's eval harness | Tie; Data Agent's grades results, not SQL text |
| Per-user data permissions | Row-level security and column exclusion are Enterprise-only | `security/data_access.py` mapped from Neuron's verified identity | Data Agent (no extra license) |
| SSO | Enterprise-only (OIDC, Entra ID) | Neuron's JWT verification | Data Agent |
| Charts and dashboards | Built-in charts, maps, "stories", scheduled reports | Flint spec rendered in Neuron's client | nao |
| Channels | Web, Slack, Teams, WhatsApp, Telegram, Mattermost | Neuron's channels | nao |
| Combined with other Neuron skills in one turn | Only through MCP from Neuron | Native tool of the main agent | Data Agent |
| Audit, erase, telemetry policy | Its own chat store, logs and PostHog analytics | Neuron's audit, data-rights routes and no-content telemetry | Data Agent |
| Stack and operations | TypeScript/Bun + Python helper + its own database and auth | Python/LangGraph in Neuron | Data Agent (one stack) |
| Vendor dependence | nao Labs roadmap and Enterprise pricing | None | Data Agent |

**Reading the table.** nao wins on breadth, UX and speed. The Data Agent wins on governance, safety and fit with Neuron. Which matters more depends on the product requirement, still the first open question in the Data Agent assessment.

#### A.3.1 Ideas to borrow from nao

- **Context as reviewable files** (`RULES.md`, per-table docs, synced metadata), versioned in git and tested.
- **A test command for context changes**, so a catalog edit is graded before it ships.
- **Semantic-layer modes**, especially "exclusive": the warehouse is reachable only through governed metrics.
- **sqlglot-based guards** for allow-listed tables, excluded columns and row predicates; the same parser was proposed for the Data Agent's validator.
- **Async ask-and-poll** for long analyses (`ask_nao` returns `running` after 45 s, then `get_nao_answer`).
- **Importing existing BI definitions** (Metabase, Tableau) to seed the catalog.

### A.4 Integration options considered (superseded)

**\[R\] The only integration worth building is option B: nao as a remote backend behind Neuron's `ask_data_agent` tool, through nao's MCP server. It is technically straightforward but carries an identity gap that only nao Enterprise closes.**

&#91;embedded content: option B · nao behind Neuron's data tool, and where identity stops\]

The tool contract is the same for both backends, so the pilot can swap nao for the native agent without changing the main agent.

#### A.4.1 Options

| Option | How | Feasibility | Verdict |
| --- | --- | --- | --- |
| A. Standalone beside Neuron | Data team runs nao with its own UI and Slack bot; no Neuron link | High; days | Good for the pilot; two products for users |
| B. nao behind `ask_data_agent` | A `RemoteDataAgent` adapter calls nao's `ask_nao` / `get_nao_answer` over MCP and maps the reply to `DataResult` | Medium; 2–3 weeks after Neuron's MCP client | **Recommended if nao is chosen** |
| C. nao context-layer tools in Neuron | Neuron's model calls nao's `execute_sql`, `read_nao_context` and others directly | Medium | Reject: model-written SQL inside Neuron, defeating the spec-first design |
| D. Fork or embed nao's code | Vendor the TypeScript into Neuron | Low; Python vs TypeScript, Enterprise files not reusable | Reject |
| E. Borrow ideas only | Adopt section 3.1 in the native Data Agent | High | Do this regardless |

#### A.4.2 What option B would have needed

&#91;F\] nao's MCP endpoint is `https://<host>/mcp` (or `/mcp/<projectId>`), streams over SSE, and accepts a bearer token or MCP OAuth. Calls run as the token's nao user, who must hold a non-viewer role. `ask_nao` takes `question`, an optional `chatId` to continue, and an optional `model`. It returns `status` (`complete`, `running`, `needs_clarification`), `text`, `clarification`, `queries`, `chatUrl` and any stories. It waits up to 45 seconds, then returns `running` for polling.

| Concern | Gap | Mitigation |
| --- | --- | --- |
| Identity | Neuron sends a per-server secret (ADR 0009 forbids passing the user's token), so every Neuron user becomes one nao user: no per-user audit or permissions | Either accept "all scope holders see all data", or buy Enterprise and map each Neuron user to a nao user by OAuth client credentials |
| Row and column security | Enterprise-only in nao | Enterprise license, or restrict nao's DB user to non-sensitive views |
| Long runs | 45 s budget, then polling; Neuron's tool timeout is ≤ 60 s | Adapter polls `get_nao_answer` within the run timeout; return `running` as a clarification if exceeded |
| Output shape | `text` + `queries` + chart embeds (MCP Apps UI) or chart data (`?chart_output=data`, ≤ 500 rows / 80k chars) | Map `queries` and chart data to Neuron artifacts; link `chatUrl` for anything larger |
| Pinning | `ask_nao`'s description lists the project's models, so it changes when models change | Pin the input/output schema hash, not the description, in Neuron's MCP config |
| Data rights | nao keeps its own chats and 7-day query result tables | Neuron's erase route must call nao's chat deletion; document retention |
| Telemetry | PostHog on by default | `POSTHOG_DISABLED=true`; point OTel at Neuron's Collector |
| Operations | A second stack: Bun/Node, Python helper, its own Postgres, auth and upgrades | Own it as a separate service with its own SLOs |
| Security posture | Writes possible if an admin enables them | Read-only DB user at the database, whatever nao's settings say |

### A.5 Recommendation at the time (superseded)

**\[R\] One data capability in Neuron, two candidate backends, one measured choice.** Do not plan a separate Analytics Agent. Run nao as a bounded pilot now. Make the build-or-buy decision at Data Agent Phase 0, after Neuron v1.0, on evidence.

1. **Legal (now, about a week).** Confirm section 1.3 with legal and with nao Labs in writing: unlicensed production use, the terms page, and an Enterprise quote for the expected user count with SSO and row-level security.
2. **Pilot (2–3 weeks, before Neuron v1.0).** Self-host nao's open-source edition with PostHog off, a read-only MySQL user on the reporting replica, and Google or GitHub login for a small data-team cohort. Build its context with `nao sync` and import any existing BI definitions.
3. **Benchmark.** Write the golden question set planned for Data Agent Phase 0 now, with reference results, and run it on nao (`nao test` plus result comparison). Record accuracy, latency and cost per answer.
4. **Decide at Phase 0** using these rules:
   - nao meets the accuracy target, and the requirement needs no per-user data permissions or the Enterprise price is acceptable → adopt nao behind `ask_data_agent` (option B) and skip the native build.
   - Per-user permissions are required and Enterprise is not bought, or nao misses the target → build the native Data Agent and borrow section 3.1's ideas.
5. **Keep the seam either way.** `DataAgentPort` with `InProcessDataAgent` and `RemoteDataAgent` stays in the Data Agent design, so the choice can be reversed later without touching the main agent.

**What not to do:** run nao and the native Data Agent side by side for the same users and data. Two agents would give different answers to the same question, with two sets of definitions to maintain.

## Sources

**License files and READMEs** (fetched 28 Oct 2026): [Wren AI](https://github.com/Canner/WrenAI) (`LICENSE` path map, README), [Cube](https://github.com/cube-js/cube) (`LICENSE`), [Vanna](https://github.com/vanna-ai/vanna) (`LICENSE`, README, `src/vanna/core/registry.py`), [DB-GPT](https://github.com/eosphoros-ai/DB-GPT), [PandasAI](https://github.com/sinaptik-ai/pandas-ai) (`LICENSE`, `pandasai/ee/LICENSE`), [Lightdash](https://github.com/lightdash/lightdash) (`LICENSE`, `packages/backend/src/ee/LICENSE`), [Metabase](https://github.com/metabase/metabase), [Chat2DB](https://github.com/CodePhiliaX/Chat2DB), [Dataherald](https://github.com/Dataherald/dataherald) (last commit date), [MindsDB](https://github.com/mindsdb/mindsdb).

**Docs and pages:** [Wren AI open-core page](https://www.getwren.ai/oss) · [Cube row-level security](https://docs.cube.dev/docs/data-modeling/access-control/row-level-security) · [Cube data access policies announcement](https://cube.dev/blog/introducing-data-access-policies-in-cube-cloud) · [Cube D3 announcement](https://cube.dev/blog/announcing-cube-d3) · [Lightdash Enterprise features](https://docs.lightdash.com/self-host/enterprise-features.md) · [Trino OPA access control](https://trino.io/docs/current/security/opa-access-control.html)

**Omni (section 5, opened 30 Oct 2026):** [Code with Claude session page](https://claude.com/code-with-claude/session/ldn-ext-building-the-best-agentic-analytics-harness-powered-by-claude-built-with-claude-code) (the [video](https://youtu.be/K4-flzsPraE) itself could not be fetched) · [Building Omni's architecture for agentic analytics](https://omni.co/blog/building-omnis-architecture-for-agentic-analytics) · [Moving beyond simple questions with agentic AI](https://omni.co/blog/moving-beyond-simple-questions-with-agentic-ai) · [Improving AI quality with context](https://omni.co/blog/improving-ai-quality-with-context) · [Introducing Omni's Agent Skills](https://omni.co/blog/introducing-omnis-agent-skills) · [Claude connector and Claude skills](https://omni.co/blog/announcing-claude-connector-and-claude-skills) · [Controlling data access](https://docs.omni.co/modeling/develop/data-access-control) · [AI data security](https://docs.omni.co/ai/security.md) · [Model providers](https://docs.omni.co/ai/settings/model-providers) · [omni-agent-skills repository](https://github.com/exploreomni/omni-agent-skills) (Apache 2.0; `omni-ai-optimizer`, `omni-ai-eval`, `omni-query` skills read at the 30 Oct 2026 commit)

**Snowflake Cortex (section 6, opened 30 Oct 2026):** [Cortex Analyst: behind the scenes](https://www.snowflake.com/en/engineering-blog/snowflake-cortex-analyst-behind-the-scenes/) · [Cortex Analyst](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst) · [Semantic view YAML specification](https://docs.snowflake.com/en/user-guide/views-semantic/semantic-view-yaml-spec) · [Semantic view best practices](https://docs.snowflake.com/en/user-guide/views-semantic/best-practices-dev) · [Cortex Analyst evaluations](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst-evaluations) · [Cortex Agents](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents)

**Databricks Genie (section 7, opened 30 Oct 2026):** [Genie Agents concepts](https://docs.databricks.com/aws/en/genie-agents/concepts) · [Create and manage a Genie Agent](https://docs.databricks.com/aws/en/genie-agents/set-up) · [Tune Genie Agent quality](https://docs.databricks.com/aws/en/genie-agents/tune-quality) · [Test and monitor a Genie Agent](https://docs.databricks.com/aws/en/genie/benchmarks) · [Metric view YAML reference](https://docs.databricks.com/aws/en/uc-semantics/metric-views/yaml-reference) · [Databricks AI trust and safety](https://docs.databricks.com/aws/en/databricks-ai/databricks-ai-trust)

**nao (Appendix A):** [getnao/nao](https://github.com/getnao/nao), cloned at commit `c72f46e` (28 Oct 2026): `LICENSE`, `LICENSE-ENTERPRISE`, `cli/LICENSE`, `README.md`, `CLAUDE.md`, `.env.example`, `apps/backend/src/types/license.ts`, `apps/backend/src/mcp/server.ts`, `apps/backend/src/mcp/tools/sub-agent.ts`, `apps/backend/src/mcp/auth.ts`, `apps/backend/src/agents/tools/`, `apps/backend/src/agents/tools/execute-sql.ts`, `apps/backend/src/utils/sql-filter.ts`, `apps/backend/src/services/semantic-layer.service.ts`, `cli/nao_core/config/databases/`, `cli/nao_core/config/semantic_layer/__init__.py`; and a search for every `/* @license Enterprise */` file.

**Official documentation** (opened 28 Oct 2026):

- [nao — Enterprise overview](https://docs.getnao.io/nao-agent/enterprise/overview.md)
- [nao — MCP connector](https://docs.getnao.io/nao-agent/connectors/mcp.md)
- [nao — Self-hosting overview](https://docs.getnao.io/nao-agent/self-hosting/overview)

**Not reviewed:** nao's terms and conditions page (not reachable from this environment).

**Related:** [Neuron Data Agent — Architecture Assessment](../proposals/NEURON_DATA_AGENT_ARCHITECTURE_ASSESSMENT.md).
