# Structured Data Questions: Auto Ontology, MCP Toolbox and the Data Gateway

| | |
| --- | --- |
| Date | 2026-11-12 |
| Status | Research proposal and handoff brief. Nothing here is decided until the ADRs in part C are accepted. |
| Question | Should Neuron adopt NVIDIA Auto Ontology for question answering over structured databases, and what happens to Google's MCP Toolbox? |
| Method | Neuron was read from this repository at `db1e9b9`. The NVIDIA and Google repositories, their docs and four independent write-ups were fetched on 2026-11-12. Nothing was installed or run. |

## Evidence labels

- **VERIFIED**: read in the primary source during this session (the source is named).
- **INFERRED**: my reasoning, or a claim that rests only on a secondary source (the source is named).
- **UNKNOWN**: looked for and not found.

Limits of the reading: external pages were fetched through a page-reading tool, and parts of long pages were summarised by it. Auto Ontology's `docs/authentication.md`, its OpenAPI spec (so the MCP tool parameters) and its Helm values were not read. Every number in part B that is a threshold or an effort size is my judgement, not a measurement.

---

# Part A. Executive summary

1. **Auto Ontology: CONDITIONAL GO as one optional engine behind Neuron's own gateway. NO-GO as a foundation or a required dependency.** Confidence: high (about 85%) on "not a foundation"; medium (about 55%) that it passes the proof in B8 this quarter.
2. **Why:** it is Apache-2.0 and architecturally relevant, but it has no tagged release, no published accuracy numbers, no external pull requests, no documented database-level read-only or per-user enforcement, and the only executed third-party test scored 0 of 12.
3. **Strategy: own the contract, the guardrails and the evaluation. Rent the engine.** The durable asset is the customer's certified semantic content and question set, kept in an open format (Apache Ossie YAML), not any engine.
4. **Architecture: your Data Gateway hypothesis is right, with three corrections.** It must execute and enforce policy itself (not proxy), it needs a new "first-party MCP server" class in Neuron, and it needs a signed identity assertion because Neuron's MCP client sends one static token and never the user's.
5. **MCP Toolbox: not required now. Keep it as a later source adapter inside the gateway.** Trigger: the first real need for a database the gateway cannot reach (BigQuery, SQL Server, Oracle), or for a large catalogue of curated parameterised queries.
6. **Sequencing:** a one to two week proof first (no product code), then a gateway MVP with a small built-in baseline engine, then governed metrics and explanations, then Auto Ontology and Toolbox adapters only when their triggers fire.
7. **Where your brief is wrong:** v1.1.0 is released, not in development. Neuron has no admin UI, so "enable by UI" does not exist yet. Neuron's MCP client refuses private addresses in production, so a sidecar gateway is unreachable today. Read MCP tools need human approval after a knowledge search, which blocks combined answers. Your own strategy research says "never free-form SQL from the model".
8. **Do not promise "comparable to Cortex Analyst".** Accuracy there comes from a curated semantic model and verified queries per customer. Promise a measured accuracy on the customer's own question set.

**Top three risks**

1. **Wrong but confident numbers.** No engine here has independent accuracy evidence. Mitigation: the evaluation in B8 gates every release, and answers always show their SQL.
2. **Data exposure through a shared database credential.** Auto Ontology runs SQL under one connection string. Mitigation: the gateway executes every query itself, read-only, under a role mapped from the user.
3. **Building on a moving target.** No releases, no external PRs, defaults that pointed at a retired model. Mitigation: pin a commit, keep it optional, keep semantic content in Ossie YAML so the engine can be dropped.

---

# Part B. Detail

## B0. What the sources say

### Neuron today (corrections to the brief)

| Claim in the brief | Finding | Label |
| --- | --- | --- |
| v1.1.0 is in development | Released 2026-11-10 as "Knowledge Engine". v1.2.0 (RAG-E09, sharing) is a proposal. | VERIFIED (`docs/ROADMAP.md`) |
| MCP is read-only | MCP tools default to `mutating`; the operator marks a tool `read`. | VERIFIED (`tools/mcp/config.py`) |
| Streamable HTTP only, SHA-256 pins, tools loaded at start-up, one static bearer per server, scopes `tools:mcp.<server>.<tool>` | Correct. | VERIFIED (`tools/mcp/client.py`, ADR 0009) |
| Enabled or disabled by UI | No admin UI exists. `web/src/features` holds chat, data, knowledge and threads only. An admin console is roadmap item F5.1. | VERIFIED (repository) |
| Without restart | Tools are fixed at start-up. An unreachable server contributes nothing until restart. | VERIFIED (`NEURON_CURRENT_ARCHITECTURE_ASSESSMENT.md`) |
| Per-user data access | No per-user delegation to MCP servers. The client "sends the configured bearer secret for that server, never the user's token". | VERIFIED (ADR 0009 decision 5) |

Four more facts decide the architecture:

- **The MCP client refuses private addresses outside development and test.** Every connection goes through `PublicOnlyBackend`. A gateway on a Docker or Kubernetes private network cannot be reached in staging or production. VERIFIED (`tools/mcp/client.py`).
- **MCP results are text only, capped at 16,384 bytes by default (`APP_MCP_MAX_OUTPUT_BYTES`), and taint the run.** VERIFIED (`config/settings.py`, `tools/mcp/client.py`).
- **After a run has read untrusted or private data, any `read` MCP tool needs human approval.** A knowledge search taints the run, so "search the documents, then query the database" pauses for approval every time. VERIFIED (ADR 0009 amendment R2, `tools/registry.py`).
- **The runtime context carries the verified principal (issuer, subject, scopes).** It holds no groups or organisation. VERIFIED (`security/auth.py`, `security/authorization.py`).

Two rules in the repository bear on the decision:

- `DOMAIN_AGNOSTIC_INTEGRATION_ARCHITECTURE.md` says of database integration: "Parameterised, pre-approved queries against a read replica or view. Never free-form SQL from the model." VERIFIED. Text-to-SQL contradicts this as written. ADR 0016 below resolves it.
- The 18-month roadmap's scope rule says nothing enters the plan because a competitor advertises it, and analytics is not among the first three use cases. VERIFIED. This work therefore needs a recorded product requirement first.

### NVIDIA Auto Ontology

| Topic | Finding | Label |
| --- | --- | --- |
| Licence | Apache-2.0. Third-party notices include `mysql-connector-python` (GPL-2.0 with FOSS exception) and `psycopg` (LGPL-3.0). | VERIFIED (README, `THIRD_PARTY_NOTICES.md`) |
| Maturity | 12.0k stars, 64 open issues, 1,368 commits, **no GitHub releases**. | VERIFIED (repository pages) |
| Age | Repository created 2026-04-27; public write-ups date the release to 2026-11-01, not October. | INFERRED (Silver Owl, ontologyrepository.com) |
| Contributions | "This project does not accept external pull requests." Issues are welcome. | VERIFIED (`CONTRIBUTING.md`) |
| Shape | Not only a library: Next.js frontend, FastAPI backend, ingestion service, FastMCP server, Postgres 17 with pgvector, optional Vault. Docker Compose and a Helm chart on NGC. | VERIFIED (README, `DEPLOYMENT.md`) |
| Databases | PostgreSQL, MySQL, Databricks, Snowflake, ClickHouse, Trino, Apache Kyuubi, HeavyDB, DuckDB, SQLite. BigQuery, Redshift and Oracle are open requests. SQL Server is absent. | VERIFIED (README, `docs/connections.md`, issues) |
| Models | Four roles (reasoning, non-reasoning, embed, rerank). Defaults are Nemotron on NVIDIA endpoints with an `nvapi-` key. "Any OpenAI-compatible endpoint" is supported; models must support structured output. | VERIFIED (README) |
| GPU | No requirement stated. | UNKNOWN |
| Semantic format | Imports and exports Apache Ossie YAML. | VERIFIED (README) |
| Ossie is the Open Semantic Interchange work donated to Apache | Likely, from search results linking the two. | INFERRED |
| MCP tools | Nine, all read-only: `ask_question`, `check_answerable`, `check_readiness`, `search_terms`, `get_term`, `get_term_columns`, `get_term_sql_attributes`, `get_sql_attribute`, `describe_table`. | VERIFIED (`docs/mcp.md`) |
| `ask_question` | Generates and **executes** SQL; returns answer, SQL and rows; capped at 100 rows; "typically tens of seconds". | VERIFIED (`docs/mcp.md`, README) |
| MCP auth | OAuth with Auto Ontology as the authorization server; "every call runs as the person who signed in". | VERIFIED (`docs/mcp.md`) |
| Per-user access at the database | One connection string per catalogue, so SQL runs under one shared database credential. Its RBAC is its own account system. | INFERRED (from `docs/connections.md`) |
| Read-only enforcement, row-level security, audit log, prompt-injection defence | Not documented. A "SQL validator" exists; its guarantees are not stated. | UNKNOWN |
| Internal hardening | The backend trusts an `x-auto-ontology-user-id` header; the ingestion endpoints "have no authentication of their own"; without Vault, connection passwords are "stored unencrypted" in Postgres. | VERIFIED (README) |
| Data leaving the deployment | With `KUMO_RFM_API_KEY` set, the agent "uploads the connected tables" to a hosted service. | VERIFIED (README) |
| Accuracy | No numbers published in the product or the evaluation repository. | VERIFIED (both READMEs) |
| Evaluation harness | `NVIDIA/ontology-sql-eval` serves the same page as `NVIDIA/auto-ontology-eval`: a schema-only control against an ontology arm on BIRD, BEAVER, FDABench-Lite, Wide World Importers and BIRD-Interact, scored deterministically. No Spider 2.0. | VERIFIED (README) |
| Model the maintainers test on | An internal endpoint with a frontier model (`claude-opus-5-5`), not the Nemotron default. | VERIFIED (eval README) |
| Independent run | `arananet/auto-ontology-eval`, 12 synthetic questions, one model. Default configuration: 0 of 12, no SQL, because `.env.example` named a model retired on 2026-09-01. Reconfigured: SQL for 11 of 12, still 0 of 12 marked correct, against 8 of 12 for schema-only. | VERIFIED (that repository) |
| Weight of that run | Small, synthetic, single run; two answers matched the expected value and were still marked wrong. It shows fragile defaults, not the ceiling. | INFERRED |

### Google MCP Toolbox for Databases

| Topic | Finding | Label |
| --- | --- | --- |
| Status | v1.16.0 on 2026-11-05; 1.0.0 was the first stable release (2026-04-10). Apache-2.0. 16.8k stars. Accepts contributions. | VERIFIED (README, CHANGELOG) |
| What it is | An MCP server that connects agents to databases. Tools are declared in `tools.yaml` as sources, parameterised SQL tools and toolsets. | VERIFIED (README) |
| Reach | Postgres, MySQL, SQL Server, Oracle, Snowflake, BigQuery, Trino, ClickHouse and many more. | VERIFIED (README) |
| Identity | "Authenticated parameters" fill a tool parameter from a claim in the caller's OIDC ID token. Mapping a user to a database role was not found. | VERIFIED / UNKNOWN (docs) |
| Operations | Dynamic reload on by default; OpenTelemetry; source-level read-only for some sources. | VERIFIED (README, CLI reference) |
| Text-to-SQL | Not a semantic layer. Free-form `execute-sql` tools exist, and Google-specific conversational analytics tools. | VERIFIED (docs navigation) |

### Competing approaches

| Product | Finding | Label |
| --- | --- | --- |
| Snowflake Cortex Analyst | Claims 90%+ accuracy on a 150-question internal set with a semantic model. Evaluates by executing SQL against the customer's verified queries. | INFERRED (search excerpts of Snowflake docs and Atlan) |
| Databricks Genie | Claims 84.5% first-try accuracy on 28 internal questions. No independent replication found. | INFERRED (search excerpts) |
| dbt Semantic Layer and MetricFlow | MetricFlow is described as the Apache-2.0 reference implementation for the interchange spec. The dbt MCP server's `query_metrics` takes metrics, group-by and filters, not SQL. | INFERRED (search excerpts) |
| Wren AI | Apache-2.0 core with a semantic model and MCP server; one engine repository is marked archived and future modules may be AGPL. | INFERRED (search excerpts) |
| Research | A September 2026 ablation (arXiv 2609.22259) reports that semantic content, not retrieval scaffolding, carries most of the gain, and that governed arms issued no mutating statements where ungoverned arms issued 166. | VERIFIED (abstract only) |

The pattern across all of them: **accuracy comes from curated semantic content and verified queries, and every published number is self-reported on a small private set.**

## B1. Verdict on Auto Ontology

**CONDITIONAL GO as an optional, swappable engine behind the Data Gateway. NO-GO as a required dependency, as the executor of SQL, or as something Neuron's core talks to directly.**

Reasons:

1. **It cannot meet the security non-negotiables alone.** Shared database credential, no documented read-only guarantee, no audit. The gateway must execute.
2. **It cannot connect to Neuron as shipped.** Its MCP server wants an interactive OAuth sign-in; Neuron sends a static bearer and has no OAuth client for MCP.
3. **It is not a stable target.** No releases means Neuron's tool pins would break on any upstream change, with no version to pin to.
4. **Its value is unproven.** No published numbers; the one executed test was negative.
5. **It is still worth a controlled test.** The licence is permissive, the design matches the research direction, it reads and writes an open format, and automatic ontology drafting is a real time saver if it works.

**What flips it to a full GO (all four):**

- A tagged, versioned release, with the MCP package installable from a registry.
- It beats Neuron's baseline engine by at least 5 points of execution accuracy on the B8 evaluation, with a model Neuron can actually use.
- A supported way to generate SQL without executing it, or to execute under a caller-supplied identity.
- It runs against a non-NVIDIA OpenAI-compatible endpoint with no NVIDIA key.

**What flips it to NO-GO (any one):**

- It fails the B8 uplift threshold over schema-only on two datasets.
- A licence change, or a required hosted service.
- No commits for 60 days, or two breaking changes inside one quarter without a release.
- The grounding tools cannot be used without the full four-service stack and that stack fails a security review.

## B2. Strategic fit: adopt, integrate or build

| Option | What it means | Lock-in | Differentiation | Maintenance | Credibility |
| --- | --- | --- | --- | --- | --- |
| **Adopt** Auto Ontology as the semantic layer | Neuron's data feature is Auto Ontology | High: no releases, no PRs, NVIDIA model defaults | None: anyone can point an agent at its MCP server | Low code, high operations (four services) | Borrowed, and at risk if its accuracy disappoints |
| **Build** a full semantic layer | Own modelling language, compiler, metric engine | None | Low: dbt, Cube and Snowflake are years ahead | Very high | Poor: a new semantic format nobody asked for |
| **Integrate** behind an owned contract | Own the gateway, policy, identity, evaluation and a thin baseline engine; read Ossie YAML; plug engines in | Low | High where Neuron is already strong: enforcement in code, audit, measured quality | Medium | Strong: it extends what Neuron is known for |

**Recommendation: integrate.** A semantic layer is the right bet for accuracy; owning one is the wrong bet for Neuron. Neuron's position is the governed, self-hosted agent layer. The parts of this problem that match that position are per-user enforcement, read-only execution, audit, explanation and evaluation. The modelling language is infrastructure, so consume the open one.

The thin baseline engine is part of the plan, not scope creep. It is the control arm of the evaluation anyway, it makes the feature work with no NVIDIA dependency, and the research cited above suggests content does most of the work.

## B3. Toolbox decision

**Not required now. A separate, later integration, as a source adapter inside the gateway. Never alongside Auto Ontology in the same phase.**

- It solves a different problem. Toolbox is connectivity and curated SQL tools. Auto Ontology is semantics and text-to-SQL. Neither replaces the other, and neither is the gateway.
- Its identity model passes the caller's ID token through, which Neuron forbids.
- Postgres first means the gateway needs one driver that Neuron already ships.
- Integrating both at once doubles the unverified surface for no user-visible gain.

**Triggers that change this (any one):**

1. A design partner needs a source the gateway cannot reach natively, and Toolbox covers it.
2. More than about 20 curated parameterised queries are wanted as tools, with reload.
3. A customer on Google Cloud wants BigQuery or Looker conversational analytics.

Toolbox fits the "parameterised, pre-approved queries" rule in Neuron's own research better than any text-to-SQL engine does. That is its natural role.

## B4. Integration architecture

```
Neuron API (agent, policy, approvals, taint)
   │  MCP over Streamable HTTP, 4 pinned tools, service bearer + signed identity assertion
   ▼
Data Gateway  (separate process, same repository; holds DB credentials; no model-facing prompt)
   ├─ policy: source and scope check, SQL validation, masking, limits, audit
   ├─ executor: read-only transaction under a role mapped from the caller
   ├─ semantic store: Ossie YAML files, certified terms only
   └─ engine adapters (generate SQL, never execute)
        ├─ baseline (built in)
        ├─ auto_ontology (optional, pinned commit)
        └─ toolbox source adapter (later)
   ▼
Customer databases (read replica or views, read-only roles, row-level security)
```

**Why a separate process and not a module:** the agent process handles untrusted model output, so warehouse credentials and database drivers do not belong in it. This is a security boundary, not a scaling choice, so the "modular monolith first" rule does not apply. It lives in this repository as a second entry point, like `neuron-worker`.

**Three corrections to your hypothesis:**

1. **The gateway is a policy enforcement point, not a protocol adapter.** Engines propose SQL. The gateway validates and runs it. No engine holds a production database credential with more than metadata access.
2. **Neuron needs a "first-party" MCP server class** (ADR 0017): a private address from an explicit allow-list, an identity assertion per call, and a stated rule for the after-taint approval gate.
3. **Hot enable and disable belongs in the gateway.** Neuron always registers the same four pinned tools. Sources and engines are switched in gateway configuration, which reloads without a Neuron restart. Scopes already hide the tools from users who lack them. This meets "without restart" without building dynamic tool registration.

**Why the alternatives lose:**

| Alternative | Why it loses |
| --- | --- |
| Neuron connects straight to Auto Ontology's MCP server | OAuth mismatch, shared database credential, provider tool names leak into scopes, prompts and evals, pins break without releases |
| Toolbox as the gateway | No policy hooks, token passthrough, no result envelope, a Go binary Neuron cannot extend without forking |
| In-process `data/` module | Database credentials and drivers inside the agent process; a GPL MySQL driver in Neuron's dependency tree if MySQL is ever added |
| Build a full semantic layer | See B2 |
| Give the agent a `run_sql` tool | Breaks the "never free-form SQL from the model" rule with no gain; the agent model is the wrong place to write SQL |

## B5. Roadmap

Sizes: S about a week, M two to four weeks, L more than a month.

| Phase | Content | Size | Exit criteria | Kill criteria |
| --- | --- | --- | --- | --- |
| **P0 Proof** | Spikes S1 to S4 in B8. No product code. | S | A recorded result for every arm and every threshold | Baseline engine below 60% on the curated set with the best available model: stop, the feature is not ready on any engine |
| **P1 Gateway MVP** | Contract v1, Postgres source, baseline engine, validator, identity assertion, audit, the ADR 0017 changes in Neuron, evaluation suite. Off by default, marked experimental. | M | B8 release thresholds met; security suite green; `make format lint typecheck test security` green | Per-user isolation cannot be shown with zero leaks: do not ship |
| **P2 Trust** | `query_metric` from the Ossie model, verified queries, the explanation card in the web client, data citations checked in code, combined document and data answers | M | Governed metric answers are deterministic; every numeric answer links to a `query_id` | none |
| **P3 Reach** (each item only on its trigger) | Auto Ontology adapter; Toolbox source adapter; Snowflake or Databricks source | M each | The adapter passes the same evaluation with no contract change | Any adapter that needs a contract change is rejected |

**Sequencing.** v1.1.0 is done, so nothing waits on knowledge work. P0 starts now because it is cheap and decides everything else. P1 should follow roadmap item F0.2 (one hosted deployment), because Neuron's own principle is evidence before claims. P1 does not depend on RAG-E09. Whether P1 goes before or after RAG-E09 is your call (open question 1); my recommendation is before, because it exercises "the user's permissions are the ceiling" on a real external system for the first time.

**Deliberately not built:**

- A semantic modelling language, a metric compiler beyond simple aggregates, or a BI front end.
- Charts, dashboards, scheduled reports, forecasting (no KumoRFM).
- Any write path to a customer database.
- A `run_sql` tool for the agent.
- Cross-source joins.
- An admin console for the gateway (configuration files until F5.1).
- Dynamic tool registration in Neuron.
- OAuth client support for third-party MCP servers (that is F2.6).

## B6. Product value

Ranked by user value first. "Needs Auto Ontology" means the feature cannot reasonably exist without it.

| # | Feature | User value | Differentiation | Effort | Needs Auto Ontology |
| --- | --- | --- | --- | --- | --- |
| 1 | Ask a question of a database in plain language, within the user's own permissions | High | Medium | M | No |
| 2 | Explainable answers: the SQL, the tables, the business terms used, who it ran as | High | High | S | No |
| 3 | Governed metrics: "revenue" always means the certified definition | High | Medium | M | No |
| 4 | Combined answers: a policy document and the numbers it governs, in one cited reply | High | High | M | No |
| 5 | Honest refusal: "the data does not hold this" instead of a guess | High | High | S | No |
| 6 | Verified queries: questions an owner has approved return the approved SQL | Medium | Medium | S | No |
| 7 | Audit trail per data question, exportable | Medium | High | S | No |
| 8 | Measured accuracy on the customer's own question set, reported per release | Medium | High | S | No |
| 9 | Automatic first draft of the semantic model from schema and query history | Medium | Low | S to integrate | **Yes** (this is its real contribution) |
| 10 | Reconciling definitions across several systems | Medium | Low | M | Mostly yes |
| 11 | Reach to Snowflake, Databricks, Trino without writing connectors | Medium | Low | M | No (Toolbox also covers this) |

Nothing a user sees truly requires Auto Ontology. It shortens the path to a semantic model (rows 9 and 10) and may raise accuracy (unproven). That is why it is an adapter and not a foundation.

## B7. Risks

| Risk | Evidence | Mitigation |
| --- | --- | --- |
| Wrong but plausible numbers | No independent accuracy data for any engine | Evaluation gates; SQL always shown; verified queries; refusal path; experimental label until thresholds hold |
| Shared credential exposes data | Auto Ontology uses one connection string | Gateway-only execution under a mapped role; engines get metadata access at most |
| Prompt injection through rows, column comments or ontology text | Documented attack class (Pedro et al.) | Typed cells, string truncation, framing, run taint, no engine-written prose in results, certified terms only |
| PII in results and logs | Auto Ontology's PII detector has an open bug | Views and allow-listed schemas; column tags mask or deny; unclassified text columns denied by default; no SQL literals or rows in telemetry |
| Immature upstream | No releases; defaults named a retired model; 64 open issues | Pin a commit; optional adapter; own evaluation; Ossie YAML keeps content portable |
| No external PRs | `CONTRIBUTING.md` | Never depend on a fix landing; anything Neuron needs lives in the adapter |
| Model dependence | Nemotron defaults; maintainers test on a frontier model | Require an OpenAI-compatible endpoint; test with Neuron's own configured model; record accuracy per model |
| Operational weight | Four services plus Postgres 17 | Optional; the baseline engine needs none of them |
| Weakening the after-taint approval rule | ADR 0009 amendment R2 | Exemption only for a first-party gateway, with a capped question length and an owner sign-off (open question 3) |
| Neuron signs identity assertions | New signing key in the API process | Short lifetime (60 seconds), audience-bound, single use, key rotation through JWKS; replaceable by IdP token exchange with no contract change |
| Scope drift | Analytics is not in the first three use cases | ADR 0016 records the product requirement and the list of things not built |
| Licence contamination | GPL MySQL connector in Auto Ontology's tree | It stays in its own containers; the gateway does not import it |

## B8. Proof required before commitment

**Datasets**

- D1: Wide World Importers, 41 questions, Postgres (from NVIDIA's harness).
- D2: BIRD Mini-Dev, 500 questions, SQLite (from NVIDIA's harness).
- D3: a Neuron set of 40 questions over a seeded Postgres mart with row-level security: 25 answerable, 8 unanswerable, 7 ambiguous. Plus 30 adversarial cases (planted instructions in rows and column comments, cross-user probes, write attempts).

**Arms** (same model in every arm; run on Neuron's development model and on one stronger model if a key exists)

- C: schema only.
- B: baseline engine with a hand-written Ossie model (at most four hours of authoring).
- A1: Auto Ontology, generated ontology, uncertified.
- A2: Auto Ontology after at most four hours of human certification.

**Spikes**

| Spike | Question | Pass |
| --- | --- | --- |
| S1 | Does Auto Ontology run from a pinned commit on a non-NVIDIA endpoint, and can its grounding tools be called with a service credential? | Runs end to end from written steps; `search_terms` and `describe_table` callable without an interactive sign-in |
| S2 | Accuracy | A2 beats C by at least 10 points on D1 and D3, and beats B by at least 5 points on D3 |
| S3 | Safety through the gateway prototype | Zero mutating statements executed; zero rows from another user's scope across the 30 adversarial cases; zero injected instructions followed |
| S4 | Does Ossie YAML round-trip between the hand-written model and Auto Ontology? | Export, import and re-export keep every metric and dimension |

**Release thresholds for the feature, on any engine**

- Execution accuracy on D3 answerable questions: at least 85%.
- Wrong answers presented without a refusal or clarification: at most 5% of D3.
- Correct refusal on unanswerable questions: at least 90%.
- p95 latency for `ask`: at most 45 seconds.
- Safety results in S3: all zero. These are hard gates, not averages.

If arm B meets the release thresholds and A2 does not clear S2, ship on the baseline engine and close the Auto Ontology question until its next release.

---

# Part C. Handoff to the build model

Rules for the build model: follow `CLAUDE.md` and `AGENTS.md`. Each task is one PR under 400 changed lines with tests that fail without the change. Do not re-decide anything below. ADR numbers assume 0015 stays reserved for the product-direction ADR (roadmap F0.1); renumber if the owner says otherwise.

## C1. ADR drafts

### ADR 0016: Structured data questions through a Data Gateway

**Context.** Users want answers from databases as well as documents. ADR 0001 and `CLAUDE.md` forbid new retrieval and services without a product requirement and an ADR. Existing research says "never free-form SQL from the model". No engine examined has independent accuracy evidence.

**Product requirement.** A signed-in user asks a question in plain language about a database their organisation has connected. They receive an answer computed by a read-only query that ran with their own data permissions, with the SQL and the business terms shown, or an explicit statement that the data does not hold the answer.

**Decision.**

1. A separate process, `neuron-data-gateway`, in this repository, exposes one Neuron-owned MCP contract (C2). Neuron core never imports a provider.
2. The gateway alone executes SQL: one validated `SELECT`, in a read-only transaction, under a role mapped from the caller, with a statement timeout and a row cap.
3. The agent model never writes SQL. Engines inside the gateway propose SQL; the gateway validates it. This refines the earlier rule to: no SQL reaches a database without passing gateway validation.
4. The first source type is PostgreSQL only.
5. The feature is off by default and marked experimental until the B8 release thresholds are met and recorded.

**Consequences.** A second deployable to secure and operate. A new package boundary: `data_gateway/` imports nothing from `api/`, `services/`, `graphs/`, `agents/`, `models/` or `knowledge/`, enforced by a test like `test_knowledge_boundaries.py`. The list under "Deliberately not built" in B5 is part of this ADR.

**Alternatives rejected.** See B4.

### ADR 0017: First-party MCP servers and the identity assertion (amends ADR 0009)

**Context.** ADR 0009 treats every MCP server as third party: public https only, one static bearer, approval after taint. A gateway the operator runs is inside the trust boundary, sits on a private network and needs to know the user.

**Decision.**

1. `McpServerConfig` gains `trust: "third_party" | "first_party"` (default `third_party`). Everything in ADR 0009 is unchanged for third-party servers.
2. A first-party server may use a private address only if its host is listed in a new setting `APP_MCP_FIRST_PARTY_HOSTS`. https is still required outside development and test. Pins, schema validation, text-only results and the size cap all still apply.
3. For a first-party server, each call carries, in addition to the service bearer, a signed assertion in the header `Neuron-Identity` (C2). It is minted from the runtime `AuthorizationContext`, never from graph state, the request body or the model.
4. Results from a first-party server still taint the run.
5. A `read` tool on a first-party server does not need approval after taint, provided its arguments pass the caps in C2. This is the one relaxation of amendment R2 and needs the owner's sign-off (open question 3). If refused, combined answers pause for approval and the rest stands.
6. The user's bearer token is still never forwarded.

**Consequences.** Neuron holds a signing key (`APP_IDENTITY_ASSERTION_KEY`, ES256, published as JWKS at a new unauthenticated route). Staging and production start-up refuse a first-party server without the key or the host allow-list.

**Alternatives rejected.** Token passthrough (forbidden by the MCP security guidance and ADR 0009). RFC 8693 token exchange now (needs the raw user token in the tool path and IdP support; the gateway verifies by issuer and JWKS, so it can replace the assertion later with no contract change).

### ADR 0018: Semantic content and engine policy

**Context.** Accuracy depends on curated semantic content. Engines are immature and replaceable.

**Decision.**

1. Semantic content is stored as Apache Ossie YAML files, in version control, owned by the customer. Only terms marked certified are served to engines or users.
2. Engines implement one interface: given a question, a source and semantic context, return a SQL proposal and the semantic references used, or a refusal code. Engines never execute against the governed source and never return prose to the caller.
3. The gateway ships a built-in `baseline` engine.
4. NVIDIA Auto Ontology is an optional adapter, pinned to a commit, added only if spike S2 passes. It runs in its own containers with a metadata-only database role.
5. Google MCP Toolbox is deferred until a trigger in B3 fires, and then only as a source adapter.
6. No engine may be required by the contract, the evaluation or the default configuration.

**Consequences.** Neuron maintains a small engine. Feature claims are tied to recorded evaluation results per engine and per model.

## C2. The Data Gateway contract, version 1.0

**Server.** Name `data` in `APP_MCP_SERVERS`, `trust: first_party`, Streamable HTTP at `/mcp`. Tool names seen by the model: `mcp_data_<tool>`. Scopes: `tools:mcp.data.<tool>`. All four tools are `risk: read`.

**Tools**

| Tool | Arguments | Purpose |
| --- | --- | --- |
| `list_sources` | none | Sources the caller may use: `source_id`, title, description, capabilities (`ask`, `metrics`) |
| `search_semantics` | `source_id`, `query` (max 200 chars), `limit` (1 to 10) | Certified terms, metrics and dimensions: name, kind, definition, synonyms. No raw column browsing. |
| `ask` | `source_id`, `question` (max 1,000 chars), `max_rows` (1 to 50, default 20) | Plain-language question to result envelope |
| `query_metric` | `source_id`, `metric`, `dimensions[]` (max 4), `filters[]` of `{dimension, op, value}` (max 6), `time_grain`, `time_range`, `limit` (1 to 50) | Governed metric, compiled without a model. Defined in 1.0, implemented in P2. |

**Result envelope** (one JSON object as a single text block, at most 12,000 bytes so it fits Neuron's default 16,384-byte cap; Neuron frames it with `tools/framing.frame`)

```json
{
  "contract_version": "1.0",
  "status": "ok | no_answer | needs_clarification | denied | disabled | error",
  "reason_code": "fixed enumeration, for example not_in_data, ambiguous_metric, source_forbidden, validation_failed, timeout",
  "query_id": "dq_<ulid>",
  "source_id": "sales",
  "engine": {"adapter": "baseline", "version": "1.0.0"},
  "result": {
    "columns": [{"name": "region", "type": "string", "semantic_ref": "dim.region", "masked": false}],
    "rows": [["EMEA", 1200.5]],
    "row_count": 1,
    "truncated": false
  },
  "explain": {
    "sql": "SELECT ...",
    "dialect": "postgres",
    "tables": ["mart.orders"],
    "semantic_refs": [{"id": "metric.net_sales", "name": "Net sales", "kind": "metric", "certified": true}],
    "verified_query": false
  },
  "clarify": {"options": [{"semantic_ref": "metric.net_sales"}, {"semantic_ref": "metric.gross_sales"}]},
  "governance": {"executed_as": "role:analyst_emea", "read_only": true, "masked_columns": []},
  "timing_ms": 8421
}
```

Envelope rules:

- No free text written by an engine or a model appears anywhere in the envelope. `reason_code` is an enumeration. `clarify.options` are references into the semantic model.
- String cells are truncated to 256 characters. Cell types are `string`, `number`, `boolean`, `date`, `timestamp`, `null`.
- `explain.sql` is the exact statement that ran.
- A disabled source or engine returns `status: disabled`; it is not a transport error.

**Identity model**

- Header `Authorization: Bearer <service token>` authenticates Neuron to the gateway.
- Header `Neuron-Identity: <JWS>` identifies the user. ES256. Claims: `iss` (Neuron's configured public URL), `aud` (`neuron-data-gateway`), `sub` (the principal's subject), `idp` (the principal's issuer), `scp` (the caller's scopes that start with `tools:mcp.data.` or `data:`), `run` (run id), `iat`, `exp` (60 seconds after `iat`), `jti`.
- The gateway verifies signature against the configured JWKS, audience, expiry, and rejects a repeated `jti`.
- Source access: the caller needs scope `data:source.<source_id>`.
- Database role: gateway configuration maps scopes of the form `data:role.<name>` to a database role per source. No mapping means `denied`. There is no default role.
- Execution on Postgres: `BEGIN READ ONLY`; `SET LOCAL ROLE <mapped role>`; `SET LOCAL neuron.user_sub = <sub>`; `SET LOCAL statement_timeout`; run; `ROLLBACK`. Row-level security policies in the customer's database may read `neuron.user_sub`.
- The connection role must itself hold no write privilege and no access outside the allow-listed schemas.

**Validation before execution** (parse with a SQL parser; reject on any failure)

- Exactly one statement, a `SELECT` (CTEs allowed), no data-modifying CTE, no `INTO`, no locking clause.
- Every referenced relation is in the source's allow-listed schemas.
- No function outside an allow-list (blocks file, network, sleep and administrative functions).
- A `LIMIT` is enforced at `max_rows + 1` to detect truncation.
- Columns tagged `pii` are masked or the query is denied, per source policy. Untagged free-text columns are denied by default.

**Audit record per call** (gateway table, also a structured log event with no SQL text and no row data): `query_id`, time, `sub` hash, source, tool, engine and version, `status`, `reason_code`, SQL SHA-256, tables, row count, mapped role, duration.

## C3. Work breakdown

### P0 Proof (no product code; work in a scratch branch; results recorded in `docs/releases/`)

| Task | Acceptance |
| --- | --- |
| P0.1 Seed D3: Postgres mart with two roles, row-level security, 40 questions with reference SQL, 30 adversarial cases | Reference SQL returns the expected values under each role; the files load with one command |
| P0.2 Hand-write the Ossie model for D3 and D1 | Validates against the Ossie schema; authoring time recorded |
| P0.3 Prototype arms C and B as a script | Deterministic scoring by executed result comparison, no model judge |
| P0.4 Stand up Auto Ontology at a pinned commit (S1) | Written steps reproduce it; endpoint, models and commit recorded; whether a non-NVIDIA endpoint worked is recorded |
| P0.5 Run all arms on D1, D2, D3 (S2) and the Ossie round trip (S4) | A table of execution accuracy, refusal accuracy, latency and model calls per arm and model |
| P0.6 Safety prototype (S3) | The three zero-counts in B8, with the cases listed |
| P0.7 Decision record | One page: thresholds met or not, per arm; the go or no-go for P1 and for the Auto Ontology adapter |

### P1 Gateway MVP

| Task | Acceptance |
| --- | --- |
| P1.1 ADRs 0016 to 0018 merged; `CLAUDE.md`, `AGENTS.md`, `ARCHITECTURE.md`, `SECURITY.md` updated | Boundary rules stated; a boundaries test exists and fails on a forbidden import |
| P1.2 `McpServerConfig.trust` and `APP_MCP_FIRST_PARTY_HOSTS` | A first-party private address connects only when allow-listed; a third-party private address is still refused; production refuses plain http |
| P1.3 Identity assertion: key setting, JWKS route, minting from `AuthorizationContext` | Assertion present only for first-party servers; claims as in C2; never minted without a verified principal; no assertion or subject in logs |
| P1.4 Taint rule for first-party read tools (only if open question 3 is approved) | After a knowledge search, `mcp_data_ask` runs without approval; a third-party read tool still pauses; arguments over the caps are refused |
| P1.5 Gateway skeleton: `neuron-data-gateway` entry point, settings, health, MCP server with the four tool definitions, Dockerfile and Compose service | Tool definitions are byte-stable; pins are generated and committed; `query_metric` returns `disabled` |
| P1.6 Assertion verification and scope checks in the gateway | Expired, wrong-audience, unsigned and replayed assertions are refused; a missing source scope returns `denied` |
| P1.7 Source registry and Postgres executor | Read-only transaction, mapped role, timeout and row cap proven by tests; a write attempt fails at the database as well as the validator |
| P1.8 SQL validator | Each rule in C2 has a failing-input test; a fuzz corpus of at least 100 hostile statements is refused |
| P1.9 Semantic store: load and validate Ossie YAML, serve certified terms, reload on change | An uncertified term is never returned; an invalid file keeps the previous version and logs |
| P1.10 Baseline engine adapter and the engine interface | Returns SQL plus semantic references or a refusal code; never receives a database connection |
| P1.11 Envelope builder, masking, truncation, size cap | Envelope never exceeds 12,000 bytes; no engine text can reach it (test with a hostile engine stub) |
| P1.12 Audit table and log event | One record per call; no SQL text or row data in logs (leak scan extended) |
| P1.13 Evaluation: D3 as a marker-gated suite and security dataset additions | `make eval` reports the B8 metrics; cross-user and injection cases are in the security dataset |
| P1.14 Operations and user docs; release verification record | Thresholds recorded per model; feature stays experimental if any is missed |

### P2 Trust

| Task | Acceptance |
| --- | --- |
| P2.1 `query_metric` compiled from the Ossie model without a model | Same input gives byte-identical SQL; an unknown metric returns `needs_clarification` |
| P2.2 Verified queries per source | A matching question returns the stored SQL with `verified_query: true` |
| P2.3 `data_citations` on `AgentAnswer`, validated in code like knowledge citations | An answer citing an unknown `query_id` loses the citation; a run with no valid data citation is not marked grounded |
| P2.4 Explanation card in the web client | SQL, tables, terms and "ran as" rendered outside the Markdown renderer, from the validated event only |
| P2.5 Combined answer evaluation | Cases needing a document and a query pass with both citation kinds |

### P3 Reach (start a task only when its trigger has fired)

| Task | Trigger | Acceptance |
| --- | --- | --- |
| P3.1 Auto Ontology adapter | S2 passed | Uses grounding tools or SQL proposals only; metadata-only role; passes D3 with no contract change |
| P3.2 Toolbox source adapter | A trigger in B3 | Curated parameterised queries exposed through `ask` or `query_metric`; no token passthrough |
| P3.3 Second source type | A named design partner | Executor tests pass for the new dialect; the validator covers its dialect |

## C4. Open questions only you can answer

1. **Priority.** Does the gateway MVP go before or after RAG-E09 (sharing)? I recommend before, after the hosted deployment.
2. **Product requirement.** Do you accept the requirement as worded in ADR 0016, including "experimental until thresholds are met"? Is there a real first user or database, or is this still speculative?
3. **Security relaxation.** Do you approve exempting first-party gateway read tools from the after-taint approval (ADR 0017 decision 5)? Without it, combined answers pause for approval.
4. **Models and keys.** Which model will the gateway's engine use, and is there a key for one stronger model for the proof? Is sending question text and column names to that provider acceptable?
5. **Target databases.** Is PostgreSQL first acceptable, and which database comes second? This decides whether Toolbox's trigger fires early.
6. **Identity granularity.** Is role-level mapping enough for the first release, or do you need per-user row-level security from day one? The second depends on customers keying policies on the IdP subject.
7. **ADR numbering.** Is 0015 still reserved for the product-direction ADR?
8. **Positioning.** Are you willing to drop "comparable to Cortex Analyst" in favour of "measured accuracy on your own questions"?

## Sources

Primary, read on 2026-11-12:

- NVIDIA Auto Ontology: https://github.com/NVIDIA/auto-ontology (README, `DEPLOYMENT.md`, `CONTRIBUTING.md`, `LICENSE`, `SECURITY.md`, `THIRD_PARTY_NOTICES.md`, `docs/mcp.md`, `docs/connections.md`, issues, releases)
- NVIDIA evaluation harness: https://github.com/NVIDIA/ontology-sql-eval and https://github.com/NVIDIA/auto-ontology-eval
- Google MCP Toolbox: https://github.com/googleapis/mcp-toolbox and https://mcp-toolbox.dev/
- Independent run: https://github.com/arananet/auto-ontology-eval
- Research: https://arxiv.org/abs/2609.22259 (abstract only)

Secondary, used only for claims marked INFERRED:

- https://silverowl.si/blog/daily-2026-11-02-nvidia-auto-ontology
- https://thaink2.com/blog/nvidia-auto-ontology-semantic-layer-data-agents
- https://www.ontologyrepository.com/blog/news-nvidia-auto-ontology-semantic-layer-ai-agents
- https://atlan.com/know/snowflake/cortex-analyst-vs-text-to-sql/
- https://www.atscale.com/?p=29945
- https://www.getdbt.com/blog/the-osi-spec-updates
- https://ossie.apache.org/updates/
- https://www.getwren.ai/en/oss
- https://glama.ai/mcp/servers/dbt-labs/dbt-mcp/tools/query_metrics
- https://arxiv.org/pdf/2308.01990.pdf (Pedro et al., prompt-to-SQL injection)

Not reachable: the MarkTechPost article (HTTP 403).
