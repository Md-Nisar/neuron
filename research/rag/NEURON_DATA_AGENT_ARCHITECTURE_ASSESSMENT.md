# Neuron Data Agent — Architecture Assessment

Oct 28, 2026 · @Md Nisar Ahmed

## Summary and recommendation

**Recommendation: build Data Agent as a specialist subagent that Neuron's main agent calls through one typed tool, `ask_data_agent`.** Inside, it is a custom LangGraph workflow in which the model writes a structured *analysis spec*, never free SQL; code resolves it against a governed semantic layer, compiles and validates the SQL, runs it read-only through MCP Toolbox, and returns a typed `DataResult`. The main agent stays the only voice to the user. Charts are Flint specs rendered by the Neuron web client.

**Timing assumption.** Data Agent is built after Neuron reaches v1.0.0, so this design assumes the roadmap has landed: the tool registry, MCP client, approvals and memory (v0.7.0), the web client (v0.8.0) and production hardening (v0.9.0–v1.0.0). Section 1 describes the code as it stands today (commit `29638c5`); sections 4–8 target the finished platform and name what to re-verify at that point.

The proposal is sound in intent (isolation, read-only access, validation outside the model, graceful degradation). Today's code lacks four things it assumes; the roadmap supplies three of them, and the fourth, data entitlements, is on no roadmap yet:

| Proposal assumes | What the repository actually has (commit `29638c5`, 27 Oct 2026) |
| --- | --- |
| A root graph with a capability registry / router | One node: `START → agent → END` (`graphs/main_graph.py::build_graph`); no router, no registry yet. `AGENTS.md` forbids new subgraphs without a requirement and an ADR. |
| A feature-flag mechanism with tenant/user scope | Plain `APP_*` booleans in `config/settings.py` (e.g. ADR 0009's `APP_MEMORY_ENABLED`); per-user gating already exists as **scopes** (`tools:<name>`, `auth_role_permissions`). No tenant concept anywhere in `src/`. |
| A frontend that renders Flint charts | No frontend in the repo; web UX is v0.8.0 on `docs/ROADMAP.md`. Flint's library is JS/TS only and its Python package is unreleased. |
| A response layer that carries tables and charts | `AgentAnswer` / `AgentResponse` (`schemas/agent.py`) and SSE protocol v1 carry text only; tool results are never persisted to thread history. |

**Why a subagent behind a tool, and not a root-graph router.** The main agent already decides when to use a capability, and it can combine a data answer with memory, other tools and approvals in one turn; a router cannot. The tool path brings scope checks, timeouts, failure isolation, tracing and the token budget for free. The subagent keeps schema, SQL and rows out of the main context. Because the Data Agent writes no prose, a one-shot question costs three model calls (main → spec → main), the same as a router. The typed contract is also the seam for moving Data Agent to its own service later.

**Decision (28 Oct 2026): build natively, including the enterprise data controls.** Neuron will not adopt nao, Cube Cloud or Wren's commercial tier. Row-level security, column masking, minimum group sizes and policy audit become first-class parts of the Data Agent (section 5). The team studies and adapts open products for ideas, architecture and permissively licensed code, under clean-room rules (section 6). Neuron's identity holds only an opaque owner key and scopes today, so the data-entitlement model is now an in-scope work item, not an external dependency.

**Labels used below.** **\[F\]** verified in the repository or official docs · **\[A\]** assumption needing validation · **\[R\]** this assessment's recommendation.

## 1. Current architecture

&#91;F\] Neuron is a deliberately narrow, heavily hardened single-agent service: FastAPI → `AgentService` → a one-node LangGraph `StateGraph` → LangChain `create_agent` → model + two read-only tools. Version 0.6.0 is on `main` (untagged); v0.5.0 is the last tag; v0.7.0 "Extensible Agent Platform" is designed in ADR 0009 (Proposed) and filed as issues #231–#253 on 27 Oct 2026.

### 1.1 Components that matter for Data Agent

| Area | Where | What it does today | Implication for Data Agent |
| --- | --- | --- | --- |
| API | `api/main.py` | `/v1/agent/invoke`, `/v1/agent/stream` (SSE), thread history, `/v1/me/*` data-rights routes; every `/v1` route takes `require_permission(<scope>)` | No new route needed for v1; structured results must ride the existing responses |
| Service | `services/agent_service.py` | `prepare` validates input, resolves an owned thread, claims a run lease and a token-budget reservation before any model call; `invoke`/`stream` share it | Reuse unchanged: leases, budgets and timeouts already bound an analytics run |
| Graph | `graphs/main_graph.py` | `START → agent → END`; `call_agent` commits only the user turn and final `AIMessage`; `_final_answer` derives `used_tools` from the run's `ToolMessage`s | `_final_answer` already reads tool messages, so tool **artifacts** can be lifted into the response there |
| State | `state/main.py` | `MainGraphState`: `messages`, IDs, `owner_key`, `user_message`, `answer`, `error` | No analytics fields should enter thread state |
| Agent harness | `models/factory.py::create_main_agent` | `create_agent(..., response_format=AgentAnswer, checkpointer=False, context_schema=AuthorizationContext)` with six middlewares: empty-reply retry, tracing, tool authorization, failure isolation, tool timeout, provider retry | The harness is the policy seam; a data tool inherits all six |
| Tools | `agents/factory.py`, `tools/` | `utc_now`, `calculator`; permissions in `_TOOL_PERMISSIONS`; `HIGH_RISK_TOOL_NAMES` deny-list in `security/input_policy.py` | Tool metadata is spread over four files; ADR 0009 #237 consolidates it into `tools/registry.py` |
| AuthN/Z | `security/auth.py`, `security/authorization.py` | JWT → frozen `Principal` (issuer, subject, scopes, token ID) → per-run `AuthorizationContext` passed as runtime `context`, never in state | Scopes give per-user rollout; there are **no data-entitlement claims** |
| Persistence | `persistence/` | `AsyncPostgresSaver` on a psycopg pool; versioned migrations (`neuron_migrations`) and an app role with per-table grants (`_APP_PRIVILEGES`); Postgres-backed leases, token ledger, rate buckets | New metadata tables must go through `migrations.py` and the grant table and its tests |
| Observability | `observability/` | OTel GenAI spans (`invoke_agent`, `chat`, `execute_tool`); names only in `semconv.py` (test-enforced); audit logger; no prompts, args or results in telemetry | SQL text and result rows must never enter logs or spans |
| Evals | `evaluation.py`, `tests/fixtures/eval_*.json` | Versioned datasets, repeated trials, baselines, a `compare` gate, nightly run on the NVIDIA model | An analytics dataset with reference results slots in as a new suite |
| Deployment | `langgraph.json`, `render.yaml` | Same graph served by FastAPI and by Agent Server (`graph` compiled without a checkpointer) | Data Agent should start FastAPI-only, as ADR 0009 does for memory |

### 1.2 Constraints the proposal must respect

- &#91;F\] `AGENTS.md` and `CLAUDE.md`: no retrieval, queues, custom persistence, **subgraphs** or multi-agent orchestration without a concrete product requirement **and** an ADR.
- &#91;F\] No mutating tools without authorization, idempotency and tests; no prompt-only security controls; no environment reads outside `config/`.
- &#91;F\] PRs under \~400 changed lines; every new dependency justified and at least 90 days old on PyPI (`scripts/check_new_dependencies.py`).
- &#91;F\] Production is not exercised before v1.0.0 (owner decision, ADR 0009); all v0.7.0 checks run locally on the NVIDIA development model.
- &#91;F\] `create_agent` runs as a nested graph with `checkpointer=False`; ADR 0009 decision 6 changes that to `None` for approvals.

### 1.3 Extensibility, as it stands

Neuron is extensible at the **tool** boundary, not the graph boundary. ADR 0009 makes that explicit: one `ToolSpec` per tool (name, scope, risk class, source), MCP servers admitted only from `APP_MCP_SERVERS` over Streamable HTTP with per-tool SHA-256 pins, and approvals for any `mutating` tool. That is already most of a capability registry.

## 2. Feasibility and value

**Technically feasible with moderate effort; business value is plausible but unproven, because no product requirement names the users, the data or the questions.** That gap is the same one ADR 0009 had to close for memory, and the same rule applies: no ADR without a requirement.

### 2.1 Value

- &#91;R\] The value is self-service answers to recurring business questions without an analyst in the loop. It is real only if three things hold: a curated analytical store exists, metric definitions are agreed, and the questions repeat.
- &#91;A\] Analytics is not among the Wave 1 use cases in this project's evidence review (agent assist, IT service desk, alert triage). It should be justified on its own requirement, not on platform completeness.
- &#91;R\] Neuron gains a second, very different workload that stress-tests the v0.7.0 registry, MCP client and evals. That is useful platform validation, but a side benefit, not a reason to build.

### 2.2 Feasibility by concern

| Concern | Verdict | Reason |
| --- | --- | --- |
| Fits the request path | High | A tool call runs inside the existing lease, run timeout (`APP_RUN_TIMEOUT_SECONDS`, ≤ 900 s), token budget and SSE stream |
| Security controls | High, once v0.7.0 lands | Scope checks, timeout, isolation and audit exist; SQL validation and a read-only DB principal are new but contained |
| Answer correctness | Medium to low | Valid SQL can still join wrongly or pick the wrong metric; curated metric tools avoid most of this, free NL2SQL does not |
| Per-user data access | Low today | No entitlement claims beyond scopes; no tenant model; owner key is an opaque HMAC |
| Structured output and charts | Medium | Needs an additive response and SSE change; charts render in the v0.8.0+ web client |
| Operational cost | Medium | Toolbox adds a Go sidecar; Flint adds a Node runtime if validated server-side; MySQL adds a second database to run |

### 2.3 Should it be a pluggable capability within Neuron?

**Yes, within Neuron, but as a tool capability rather than a graph capability.** \[R\] The reuse argument in the proposal is correct: auth, leases, budgets, tracing, evals and data-rights routes would all be duplicated by a separate service. A separate service is justified only if analytics needs its own scaling, network zone (e.g. direct access to a data warehouse) or ownership, and the tool boundary keeps that option open: the tool's implementation can later call a remote analytics service without changing the agent.

## 3. Assessment of the proposed design

**Keep the workflow, the read-only posture and the response fields; turn the subgraph into a subagent behind a tool, drop the router, simplify the flags, narrow Toolbox's role, and render Flint in the web client.**

### 3.1 Component verdicts

| Proposal element | Verdict | Assessment |
| --- | --- | --- |
| Dedicated LangGraph subgraph (§7) | Keep, as a subagent | \[F\] LangGraph supports a subgraph as a node or called inside a node; `checkpointer=None` inherits the parent's checkpointer and supports interrupts. \[R\] Run the analytics workflow as a subagent inside the `ask_data_agent` tool, with the inherited checkpointer, not as a branch of the root graph. It still needs an ADR under `AGENTS.md`. |
| Capability registry / router at the root graph (§4, §7.2) | Replace | \[F\] Today the root graph has one node. \[R\] A router adds a classification call per request, a second authorization path, and cannot combine a data answer with memory or other tools in one turn. Use the v0.7.0 `ToolSpec` registry as the registry and let the main agent choose. |
| Feature flags (§6) | Simplify | \[F\] Neuron's pattern is a deploy-level `APP_*` boolean plus scopes. \[R\] `APP_DATA_AGENT_ENABLED` (default false) registers the tool; the scope `tools:data_agent` rolls it out per user or role. Drop the five sub-flags except `APP_DATA_AGENT_TIER2_ENABLED`. Tenant flags need a tenant model first. |
| PostgreSQL (§8.1) | Keep, narrowly | \[R\] Semantic-layer catalog through versioned migrations and explicit grants; analysis specs in the LangGraph Store; no result rows. |
| MySQL (§8.2) | Keep, with stronger isolation | \[A\] Topology unknown. \[R\] Replica or reporting schema, a user with `SELECT` on approved views only, `max_execution_time`, TLS. \[F\] Toolbox enforces read-only for Cloud SQL for MySQL, not documented for a plain `mysql` source, and `queryTimeout` defaults to none, so the database grant is the boundary. |
| Google MCP Toolbox (§9) | Keep for execution; validation stays in Neuron | See 3.2. |
| Microsoft Flint (§12) | Keep; render in the web client | See 3.3. |
| Structured response (§13) | Keep, make it additive | \[R\] Optional `artifacts` on `AgentAnswer`, `AgentResponse` and the SSE `final` event; raw SQL only with a separate scope. |
| Security (§14), evals (§15) | Keep, make concrete | \[R\] Each bullet becomes a test or an eval case (sections 5.5 and 7.3). |

### 3.2 Google MCP Toolbox for Databases

&#91;F\] Toolbox (repository renamed from `genai-toolbox` to `mcp-toolbox`; Go module v1.15.0 published 23 Oct 2026) is a server that exposes tools declared in `tools.yaml` over MCP (`/mcp`, or `/mcp/{toolset}`) and through SDKs (`toolbox-core`, `toolbox-langchain`). For MySQL it offers fixed-statement `mysql-sql` tools with typed, positional parameters, the free-form `mysql-execute-sql`, and catalog tools such as `mysql-list-tables`. It exports OpenTelemetry.

What it does well: curated, parameterised queries with `allowedValues`, `minValue`/`maxValue`, credentials held outside the app, and a declarative catalog people can review.

What it does not do: \[F\] it does not parse or validate free-form SQL; `templateParameters` are documented as prone to SQL injection. So for NL2SQL, Toolbox is a pass-through and every safety check stays in Neuron.

Two conflicts with ADR 0009 need a decision:

- **Token passthrough.** \[F\] Toolbox's per-user features (authenticated parameters, `authRequired`) expect the client to forward an OIDC ID token (Google or generic OIDC). \[F\] ADR 0009 decision 5 says the MCP client sends a per-server bearer secret, *never the user's token*. \[R\] Keep ADR 0009's rule; pass any user filter as an ordinary parameter set by trusted code, not by the model.
- **Model-visible tools.** ADR 0009 exposes MCP tools to the model. \[R\] For analytics, the main model should see one `ask_data_agent` tool; Toolbox tools are called by the Data Agent's code, not chosen by any model. That means using `toolbox-core` (or the MCP client with Toolbox flagged not model-visible) from inside the subagent, not registering Toolbox's tools in the agent.

### 3.3 Microsoft Flint

&#91;F\] Flint is an MIT-licensed visualization language from Microsoft. A compact chart spec with semantic field types compiles to Vega-Lite, ECharts, Chart.js, Plotly or Excel. The library and the `flint-chart-mcp` server are npm packages needing Node 18+; the Python port is a source-only preview. The release page lists 1.0 ("Interactivity") on 21 Oct, while the README still describes 0.5.1 (August 2026).

Risks for Neuron:

- &#91;F\] Neuron's backend is Python and Flint's library is JS/TS, so rendering belongs in the web client; a server-side Node runtime or the Flint MCP server adds a second runtime for no gain.
- &#91;F\] Flint specs can reference data by `data.url` (local files), and its MCP server trusts file access by default since 0.2.1 (`--disable-file-reference` turns it off). \[R\] Never accept a `data.url`; the client inlines only the rows the query returned.
- &#91;R\] Never call the hosted endpoint (`flint.data-formulator.ai/mcp`): it would send query results outside the trust boundary.
- &#91;A\] 0.x to 1.0 in four months suggests a moving API; pin the npm version in the client.

&#91;R\] The Data Agent's shaping step emits a Flint chart spec without data (chart type, encodings, semantic types), chosen by rules from the spec and the result shape, and validated in Python against a pinned schema of Flint's input. The web client inlines the artifact rows and compiles the spec with the `flint-chart` npm library. If compilation fails, the client shows the table.

### 3.4 Gaps the proposal does not address

1. **Data entitlements.** Who may see which tables, columns and rows, derived from which token claims. Today `Principal` holds issuer, subject and scopes only.
2. **Result persistence and data rights.** Tool output is not saved to threads. If tables are saved later, the `/v1/me/export` and erase routes must cover them.
3. **Context window and cost.** Rows go to the model only as a bounded summary; the full rows travel as an artifact the model never sees.
4. **Prompt injection from data.** Values in result rows and schema comments are untrusted content and must be delimited as such (ADR 0009 does this for memory).
5. **Agent Server path.** Artifacts and the new tool must not break `langgraph.json`'s graph; start FastAPI-only.
6. **Telemetry policy.** SQL text and rows count as tool arguments and results, which `ARCHITECTURE.md` bans from logs and spans. Log a statement hash, row count and tables touched only.
7. **Evaluation of correctness.** Needs reference answers computed on a frozen dataset, not keyword matching.

### 3.5 Alternatives considered

| Option | Who talks to the user | Strengths | Weaknesses | Verdict |
| --- | --- | --- | --- | --- |
| A. Root router + analytics subgraph (proposal) | Whichever branch ran | Clear isolation | A routing call on every request; cannot mix data with memory or other tools in one turn; second authorization path | Reject |
| B. Handoff to a Data Agent | Data Agent, directly | Cheap follow-ups | Two voices: output guard, memory and approvals must be duplicated; thread history split | Reject |
| C. Skill: main agent loads data instructions and calls SQL tools itself | Main agent | Fewest calls | Schema, SQL and rows enter the main context; the model picks SQL tools | Reject |
| D. Subagent behind one tool, custom workflow inside | Main agent | Isolation, one voice, reuses the tool path, three calls per question | Each follow-up is a full call; artifact plumbing needed | **Recommend** |
| E. Separate service over A2A | Main agent (remote subagent) | Own scaling and network zone | Duplicates operations; premature | Later, through `DataAgentPort` |
| F. Direct read-only driver instead of Toolbox | n/a | One fewer service | Credentials and query catalog in app code | Fallback if Toolbox's cost is not justified |

## 4. Recommended architecture

**\[R\] For the finished Neuron, Data Agent is a subagent called as a tool (LangChain's *subagents* pattern), and inside it is a *custom workflow*: one model step writes an analysis spec, and deterministic code does everything that touches data.** The root graph, `MainGraphState` and thread history stay as they are.

&#91;embedded content: integration · main agent, Data Agent subagent, three stores\]

The main agent decides *whether* to ask a data question and writes the answer; the Data Agent decides *what* the question means; code decides *what SQL runs*.

### 4.1 Why this integration pattern

&#91;F\] LangChain documents five multi-agent patterns (subagents, handoffs, skills, router, custom workflow) and advises justifying any of them over a single agent with good tools. \[R\] Data Agent justifies one on context isolation (schema, catalog, SQL and rows are large and sensitive) and on distributed ownership (a data team can own it). Section 3.5 compares the options; the deciding points:

- **One voice.** Only the main agent talks to the user, so Neuron's output guard, memory, approvals and other tools apply to every answer, and mixed questions ("compare Q3 revenue with the target I asked you to remember") resolve in one loop.
- **Isolation.** The main agent sees a short summary and a list of key figures; rows travel as an artifact the model never reads.
- **Cost.** \[F\] LangChain's generic subagent costs four model calls for a one-shot request. \[R\] Here it is three, because the Data Agent writes no prose: the main agent narrates from the `DataResult`.
- **Reuse.** The call rides Neuron's tool path: scope check, timeout, failure isolation, tracing, token budget.
- **Evolution.** The typed contract is the seam: in-process first, a remote service over A2A later, with no change to the main agent.

### 4.2 The contract between the two agents

**Tool input (`DataRequest`), filled by the main agent's model:**

| Field | Type | Purpose |
| --- | --- | --- |
| `question` | text, ≤ 2,000 chars | The user's data question, restated self-contained |
| `follow_up_of` | analysis ID, optional | Refine an earlier analysis in this thread ("same, but by region") |
| `want` | `answer` \| `table` \| `chart` | What the user asked to see |

**Runtime context, never model-supplied:** the `AuthorizationContext` (principal, scopes, usage accumulator), the owner key and thread ID, the user's resolved data entitlements, and recalled preferences (fiscal calendar, currency, default region) from Neuron memory.

**Tool output (`DataResult`):**

| Part | Seen by | Contents |
| --- | --- | --- |
| `status` | main model | `answered`, `needs_clarification`, `no_data`, `refused`, `failed` |
| `summary` | main model | ≤ \~300 tokens, delimited as untrusted data |
| `key_figures` | main model | name, value, unit, period: the only numbers the answer may state |
| `clarification` | main model | one question plus up to five options from the catalog |
| `caveats` | main model | freshness, truncation, definitions applied |
| `analysis_id` | main model | handle for follow-ups |
| artifact `table` | client only | columns, bounded rows, `truncated` |
| artifact `chart` | client only | Flint chart spec without data; the client inlines the rows |
| artifact `provenance` | client only | metric IDs, catalog version, query hash, data freshness; SQL only with a separate scope |

&#91;R\] `needs_clarification` maps to Neuron's existing `AgentAnswer.clarification_needed`, so the main agent asks the user and no nested interrupt is needed. \[R\] A code check after the answer (beside the system-prompt guard in `security/output_policy.py`) flags any figure in the answer that is absent from `key_figures`.

### 4.3 Inside the Data Agent

&#91;embedded content: inside the Data Agent · 8 steps, 3 exits, 1 repair loop\]

A wrong guess about meaning ends in a clarifying question, a policy violation ends in a refusal, and a suspicious result earns one repair attempt before it fails.

- **Analysis spec, not SQL.** The planning step returns a typed `AnalysisSpec`: metric IDs, dimensions, filters, time range, comparison, sort, limit. Every field must resolve to a catalog entry, so the model cannot name a table it was not given.
- **Semantic layer.** A versioned catalog in Postgres: metrics with their SQL definition, dimensions, approved joins, synonyms, sample questions, owner, and an entitlement tag per object. People review changes like code. The planning step sees only the catalog slice matched to the question.
- **Two tiers.** Tier 1 compiles SQL deterministically from the spec. Tier 2, for questions the catalog cannot express, lets the model draft SQL against an allow-listed schema; it is off by default and opened only after its own eval gate.
- **Validation and entitlements.** Code parses the SQL, allows one `SELECT` over approved objects, injects row filters from the user's entitlements, caps `LIMIT`, and rejects plans whose `EXPLAIN` estimate exceeds a cost ceiling.
- **Verification.** Code checks row shape against the spec, null and duplicate rates, and that parts sum to totals where the metric says they should.
- **Model use.** One structured-output call in Tier 1; one more in Tier 2; at most one repair. A smaller, cheaper model is allowed for the planning step if the evals show no loss.
- **State.** A private `DataAgentState`, compiled with the inherited checkpointer (`checkpointer=None`, per invocation, as ADR 0009 sets for the main agent). Nothing enters the main thread state.
- **Follow-ups.** Each `AnalysisSpec` (never rows) is saved in Neuron's LangGraph Store under `("analyses", owner_key, thread_id)` with the thread's retention; the export and erase routes include it.

### 4.4 Integration seams with Neuron

| Seam | Neuron component (v1.0) | What Data Agent does there |
| --- | --- | --- |
| Registration | `tools/registry.py` `ToolSpec` | `ask_data_agent`, scope `tools:data_agent`, risk `read`, per-tool timeout; registered only when `APP_DATA_AGENT_ENABLED` is true |
| Authorization | `security/authorization.py` | Same `AuthorizationContext` passed as the subagent's runtime context; new `security/data_access.py` maps verified claims to entitlements |
| Limits | token budget, run lease, run timeout | Subagent model calls charge the same `TokenUsageAccumulator`; its timeout sits inside the run timeout |
| Streaming | `services/agent_service.py`, `services/streaming.py` | Token extraction ignores the subagent's model namespace; additive SSE events `progress` (stage name) and `artifact` |
| Response | `schemas/agent.py` | Optional `artifacts` on `AgentAnswer`, `AgentResponse` and the `final` event; thread history stores the answer and the analysis ID only |
| Memory | ADR 0009 store and `recall` | Reads preferences as context; never writes memories |
| MCP | `APP_MCP_SERVERS` client | Toolbox admitted with pinned tools, flagged not model-visible (or reached via `toolbox-core`) |
| Approvals | `HumanInTheLoopMiddleware` | Not needed for Tier 1; optional approval for Tier 2 queries above the cost ceiling |
| Observability | `observability/semconv.py` | Nested `invoke_agent data_agent` span under `execute_tool ask_data_agent`; one span per stage; no SQL text or values |
| Evals | `evaluation.py` suites | A subagent-level suite (`DataRequest` → `DataResult` against reference results) plus end-to-end cases |
| Client | v0.8.0 web app | Renders table and Flint chart from the artifact; provenance panel; "show SQL" for holders of the SQL scope |
| Agent Server | `langgraph.json` graph | Registered on both paths once artifacts are verified there |

### 4.5 Code layout and boundary

```
src/neuron_agent/capabilities/data_agent/
  __init__.py      build_data_agent_tool(settings) -> ToolSpec | None
  contract.py      DataRequest, DataResult, AnalysisSpec, artifacts
  graph.py         DataAgentState and the workflow
  planner.py       structured-output planning step
  semantic/        catalog repository, resolver, SQL compiler
  sql_policy.py    parser, allow-list, entitlement filters, LIMIT, cost
  executor.py      Toolbox client, timeouts, row caps
  shaping.py       key figures, table, chart spec
  port.py          DataAgentPort: InProcessDataAgent | RemoteDataAgent (A2A)
src/neuron_agent/prompts/data_agent/plan.md
```

&#91;R\] An import-boundary test, like `tests/security/test_import_boundaries.py`, enforces two rules: core modules import only the package root (contract and factory), and the capability imports core only through public interfaces (settings, authorization, errors, semconv, store). Removing the package and the flag leaves Neuron byte-for-byte unchanged in behaviour.

### 4.6 Deployment evolution

In-process by default, behind `DataAgentPort`. \[R\] Move to `RemoteDataAgent` over A2A (signed Agent Card, Neuron's existing identity) only when the data must be reached from a separate network zone, the workload needs its own scaling, or another product wants the same agent. The tool, the contract and the main agent stay the same.

### 4.7 Design upgrades from studying Omni

**\[R\] Omni's production analytics agent confirms the core design: abstract query, not SQL; permissions in the semantic layer; rows kept out of the main model's context. It also shows eleven upgrades worth making.** Source details are in the [landscape doc](https://claude.ai/artifact/PkUyUEkQmB45J8wWDaF8xv), section 5. All are concepts only; Omni is proprietary.

| # | Area | Upgrade | Omni practice it follows | Phase |
| --- | --- | --- | --- | --- |
| 1 | `AnalysisSpec` shape | Fields as `view.field` with time grains (`created_at[month]`); typed filters (`{type, kind, values}`); sorts; limit; pivots; table calculations as an AST; the subject area | Abstract Omni query JSON | 1 |
| 2 | Subject areas | Group the catalog into curated subject areas ("topics"): base table, governed joins, a field allow-list, optional AI-only variants. Planning picks the subject area first, then the spec | Topics, `ai_fields`, `ai_chat_topics`, `extends` | 2 |
| 3 | Value grounding | A `lookup_values(field, text)` step maps user wording to stored values ("New York" → "NYC") before filters are fixed. Lookups run under the same row filters as queries, so they cannot reveal values a user may not see | Field-values tool | 2 |
| 4 | Layered context | Per catalog object: human `description`, short AI-only note, `synonyms`, `sample_values`/`all_values`, and sample questions paired with their correct spec. Personalise with user attributes resolved server-side, never by the model | `ai_context` at four levels, synonyms, `sample_queries`, attribute templating | 2 |
| 5 | Context budget | A context assembler with a character budget per stage and a fixed pruning order: least useful properties first, a small never-pruned core. Plus an admin-only inspector showing exactly what the planner received (not logged, per Neuron's telemetry policy) | \~75K/\~100K caps, pruning order, workbook inspector | 2 |
| 6 | Analysis mode | For open questions ("how is attrition trending in my org?"), a bounded loop: plan a visible task list (streamed as `progress` events), run up to N specs (e.g. 6), check each result, stop early. Simple questions keep the one-call Tier 1 path | Coordinator with task list | 3 |
| 7 | Summarization | A summarizer subagent reads bounded result rows in its own context and returns key figures. The planner only ever sees metadata. A tenant switch can forbid sending any rows to a model; code then computes the summary | Summarization subagent; metadata-only query generation | 2 |
| 8 | Judged evals | Add a trajectory judge next to reference-result checks. It grades subject-area choice, filters, row-limit handling, mental math and period-over-period logic as pass/fail with a rationale. Record cost and AI time per prompt. Compare each catalog or policy PR against `main` and list regressions | Prompt sets, accuracy judge, branch A/B | 0–2 |
| 9 | Reliability first | Strict schemas on every step's input and output; detectors for malformed state; cross-step tests ("after summarizing, do not re-query unless filters changed") | "Each tool does exactly what it says" | 1–2 |
| 10 | Prompt caching | Render the catalog slice and conversation deterministically so prompt caching holds across turns | Stable message representation | 1 |
| 11 | Feedback loop | Thumbs up/down and an admin usage view feed proposed catalog changes (an LLM drafts `synonyms` or notes as a PR; a person approves). Saved analysis workflows as Neuron skills come later | AI usage dashboard, AI model suggestions, Agent Skills | 5+ |

**What changes in the plan.** Phase 2 gains subject areas, value grounding, the context assembler and the summarizer. Phase 3 gains analysis mode next to gated Tier 2. Evals gain the trajectory judge in Phase 0.

**What not to copy:** Omni's privileged raw-SQL path stays out of the default design; the gated Tier 2 is Neuron's equivalent. Omni's per-user OAuth through MCP becomes relevant only if Neuron later exposes the Data Agent to outside clients as an MCP server.

## 5. Enterprise data-access controls, built in-house

**\[R\] The Data Agent enforces per-user data access in code and again in the database, denies by default, and never relies on the model.** These are the features analytics vendors keep for paid tiers (nao, Wren, Cube Cloud). Neuron builds them on its own identity, so they need no extra license and stay inside one audit and erase boundary.

&#91;embedded content: enforcement layers · 6 stages, deny by default\]

The rewrite (layer 3) is the main control. The database views (layer 4) catch any rewrite bug. The result check (layer 5) blocks leaks through small groups, which neither of the others can see.

### 5.1 Enterprise features: what Neuron has, what the Data Agent adds

| Feature (vendor tiers charge for these) | Neuron v1.0 | Data Agent adds |
| --- | --- | --- |
| SSO (OIDC, Entra ID) | Yes: JWT/JWKS verification (ADR 0006) | Nothing |
| Roles and groups | Yes: scopes and `auth_role_permissions` | Data roles mapped from groups |
| Per-user usage budgets | Yes: token budget and run caps | Query cost ceiling per user |
| Audit log | Yes: `observability/audit.py` | `data_policy_decision` and `data_query_executed` events |
| Row-level security | No | Policy-driven row filters (5.3) |
| Column exclusion and masking | No | Column classes with mask rules |
| Minimum group size | No | Suppress aggregates over fewer than *k* people |
| Tenant isolation | No tenant model | Mandatory tenant filter on every table, if multi-tenant |
| Policy authoring and review | No | Policies as versioned files, reviewed like code; admin UI later |
| Warehouse identity passthrough | No | Not planned: service user + rewrite + views instead |

### 5.2 Entitlement model

- **Attributes, never from the model.** `security/data_access.py` builds a `DataPrincipal` per run from the verified token's groups and from Neuron-side tables: org unit, region, legal entity, data roles, and the set of people the user manages.
- **Reporting tree.** Synced from the HR system into a closure table (`ancestor`, `descendant`), so "my team, at any depth" is one indexed join. A stale sync narrows access rather than widening it: unknown means none.
- **Lifetime.** Resolved at run start, carried in the runtime context with the `AuthorizationContext`, and never stored in thread state, prompts or logs.

### 5.3 Policy model

One policy per catalog object, version-controlled beside the semantic layer:

```yaml
object: hr.employee_compensation
owner: people-analytics
rows:
  default: deny
  rules:
    - when: role == "hr_admin" and legal_entity in principal.legal_entities
      filter: "legal_entity_id IN (:principal.legal_entities)"
    - when: role == "manager"
      filter: "employee_id IN (SELECT descendant FROM org_closure WHERE ancestor = :principal.employee_id)"
columns:
  base_salary: { class: restricted, mask: { manager: null, hr_admin: none } }
  national_id: { class: secret, mask: { "*": deny } }
aggregation:
  min_group_size: 5
```

- **Semantics** follow PostgreSQL's model: rules are permissive (any matching rule grants rows); a separate restrictive filter (for example the tenant) is always ANDed on.
- **Masks** follow Apache Ranger's types: nullify, redact, hash, partial show, date truncation, deny.
- **Engine.** Start with a small evaluator over these files. Move to OPA or Cedar only when policies outgrow it, keeping the same decision interface: for one principal and table, return row filters and column masks (the shape Trino's OPA plugin uses).

### 5.4 Enforcement

1. **Rewrite.** After SQL is compiled, sqlglot qualifies every column, finds every base-table reference (joins, subqueries, CTEs, unions) and wraps it in its filter. It replaces masked columns with the mask expression, rejects `SELECT *` on restricted objects, and caps `LIMIT`. Unknown object or parse doubt: refuse.
2. **Database.** MySQL has no native row-level security. The agent's database user can read only secure views, and those views already drop secret columns, so a rewrite bug cannot reach them. If a data role must be enforced in the database too, use one database user per data role.
3. **Result check.** Groups under `min_group_size` are suppressed with a caveat. Totals that would let a suppressed group be derived by subtraction are suppressed as well.
4. **Fail closed.** Any error in layers 1–5 returns `status: refused` with a fixed reason; nothing partial is returned.

### 5.5 Testing the controls

- **Permission matrix.** Fixture users (employee, manager, skip-level manager, HR admin per entity, other tenant) × the golden questions; each cell asserts the exact allowed row set.
- **Invariant tests.** For any query, the rows returned are a subset of the rows the same user gets from the secure view with the policy filter applied directly.
- **Rewrite fuzzing.** Generated SQL with nested subqueries, CTEs, self-joins, unions and aliases; every base table must come out filtered.
- **Adversarial evals.** Prompt-injected questions ("ignore my role"), injected text in catalog descriptions and rows, and difference attacks on small groups.
- **Policy-change tests.** Each policy file change runs the matrix before merge, like nao's context tests.

## 6. Prior art: study, adapt, build our own

**\[R\] Learn from the open analytics agents and data-security systems, reuse permissively licensed code where it saves real work, and write our own wherever a vendor keeps the feature commercial.** Each item below names what to take and what to leave; product profiles are in the companion landscape doc.

### 6.1 What to take from each

| Source | License (verified) | Study and adapt | Leave alone |
| --- | --- | --- | --- |
| [nao](https://claude.ai/artifact/PkUyUEkQmB45J8wWDaF8xv) | Apache 2.0 core; MIT CLI; 63 files under a commercial license | Context as reviewable files (`RULES.md`, per-table docs); `nao test` style context tests; semantic-layer "exclusive" mode; async ask-and-poll contract (`ask_nao` / `get_nao_answer`); clarification status; BI import skills (Metabase, Tableau); MIT sqlglot guards in `cli/nao_core/config/databases/` (allow-listed tables, excluded columns, row predicates) | Every `/* @license Enterprise */` file: SSO, row-level security wiring, column exclusion service, budgets, license checks |
| [Cube](https://github.com/cube-js/cube) Core | Apache 2.0 / MIT | `access_policy` model: groups plus user attributes produce row filters and member-level access; security context from the JWT; `queryRewrite` hook; pre-aggregation caching | Cube Cloud-only features; also evaluate Cube Core as a dependency (section 8) |
| [Wren AI](https://github.com/Canner/WrenAI) core | Apache 2.0 for `core/`, `sdk/`, `skills/`; docs CC BY 4.0; future AGPL modules announced | Modeling definition language (MDL) for semantic models; text-to-SQL pipeline structure; connector layering | Commercial tier (row and column security, access control); any AGPL path once added |
| [Trino OPA plugin](https://trino.io/docs/current/security/opa-access-control.html) | Apache 2.0 | Decision interface: per table, return row-filter expressions and one mask per column; identity + groups as input; batch mode | — |
| Apache Ranger | Apache 2.0 | Row-filter policy model; mask types (nullify, redact, hash, partial, date); audit fields | Its Hadoop-centric plugins |
| PostgreSQL RLS | PostgreSQL License | Permissive vs restrictive policy semantics; deny when no policy applies | — |
| OPA, Cedar, OpenFGA | Apache 2.0 | Policy engines to adopt later if file-based policies outgrow a small evaluator; OpenFGA for reporting-line relationships | — |
| sqlglot | MIT | Use directly: parsing, qualifying, base-table discovery, rewriting MySQL SQL | — |
| [Microsoft Flint](https://github.com/microsoft/flint-chart) | MIT | Use directly in the web client for charts | Hosted MCP endpoint |
| Omni (product); omni-agent-skills (repository) | Proprietary product; skills repository Apache 2.0 | Abstract query over curated topics; value-grounding tool; summarizer subagent; layered AI context with budgets and pruning order; access grants and row access filters; trajectory-judged evals with branch A/B (section 4.7) | Product code and UI (closed); quote the Apache skills only with notice |

### 6.2 Clean-room rules

This is a technical policy, not legal advice; legal should approve it once in Phase 0.

1. **Open code (Apache, MIT, BSD, PostgreSQL License):** may be read and reused. Copied or adapted files keep their license header and are listed in `NOTICE`; the PR says where they came from.
2. **Commercially licensed files are not read by implementers.** These are files that are public but not free to copy, such as nao's Enterprise files, Wren's and Cube's commercial features, or any "source-available" license. Designs for the matching features come only from public docs, papers and open systems (Ranger, Trino, PostgreSQL, Cube Core).
3. **AGPL and other copyleft code is not copied into Neuron.** It may be run as a separate service only after legal review.
4. **Ideas are free; code is not.** Reuse concepts and interfaces. Do not translate a commercial file into Python or closely paraphrase it.
5. **No name or brand reuse.** Do not use "nao", "Cube" or "Wren" in product names, and do not imply endorsement.
6. **Provenance in review.** The PR template gains one line: "Prior art consulted: … / code reused under: …". The `security-reviewer` agent checks it on critical-tier paths.

## 7. Implementation plan

**\[R\] Start once Neuron v1.0.0 is tagged; Phase 2 is the first usable release, about 10–12 weeks later.** Phase 0 re-checks every seam in section 4.4 against the shipped v1.0 code, because ADR 0009 and later releases may land differently from their designs. Durations are indicative for one or two engineers; each phase is several PRs under \~400 changed lines, per `AGENTS.md`.

&#91;embedded content: roadmap · 6 phases, 6 gates, not to scale\]

Phase 2 is highlighted because it is the first release with user value; Phase 3 can be skipped if curated metrics answer most real questions, and Phase 4 can run in parallel with Phase 3.

### 7.1 Repository integration points

| Phase | Files touched (existing → new) | Acceptance criteria |
| --- | --- | --- |
| 0 Decide | `docs/decisions/<next>-data-agent.md` (new ADR, including the entitlement model and clean-room policy); `AGENTS.md` (permit the subagent workflow); `.github/pull_request_template.md` (prior-art line); `NOTICE`; `tests/fixtures/eval_data_cases.json` (new) | Every section 4.4 seam confirmed in v1.0 code; requirement, entitlement model and clean-room rules approved (legal included); Cube Core spike done; 30–50 real questions with reference results and a permission matrix |
| 1 Contract | `config/settings.py` (`APP_DATA_AGENT_*`); `capabilities/data_agent/` skeleton (`contract.py`, `port.py`, `graph.py` with a fake executor); `tools/registry.py` entry; `schemas/agent.py` (`artifacts`); `services/streaming.py` (`progress`, `artifact` events; ignore subagent tokens); import-boundary test | Flag off: all existing tests and eval baselines unchanged; flag on with the fake: artifacts reach the response and SSE, never thread history, export, logs or spans |
| 2 Curated metrics + data controls | `docker-compose.yml` (Toolbox, MySQL fixture with secure views); `deploy/toolbox/tools.yaml` (pinned); `persistence/migrations.py` + grants (catalog, policy and `org_closure` tables); `semantic/`, `planner.py`, `executor.py`, `shaping.py`; `security/data_access.py` (DataPrincipal); `capabilities/data_agent/policy/` (policy files, evaluator, sqlglot rewriter, result check); `observability/semconv.py`, audit events | Tier 1 accuracy meets the G0 target \[A: e.g. pass^3 ≥ 0.9\]; permission matrix 100% exact; rewrite fuzzing finds no unfiltered base table; small-group suppression proven; writes, DDL and unlisted objects fail at the database |
| 3 Gated NL2SQL | Rewriter hardened for free-form SQL (unions, window functions, nested CTEs); Tier 2 Toolbox toolset with its own credentials; `APP_DATA_AGENT_TIER2_ENABLED`; security eval cases (prompt injection, difference attacks) | Validator and rewriter pass 100% of the red-team set; Tier 2 accuracy reported separately; no regression in the existing security suite |
| 4 Charts | `shaping.py` (Flint spec rules + pinned schema); web client renders with `flint-chart` | Every emitted spec is schema-valid; no `data.url`; masked columns never charted; the table shows when a chart fails |
| 5 Pilot | Scope and data-role grants in the IdP / `auth_role_permissions`; `deploy/observability/prometheus-alerts.yaml` (denials, suppressions) | Pilot task completion, accuracy and cost per answer meet targets; zero permission defects in the pilot audit review |

### 7.2 Dependencies

- **Neuron v1.0 seams** (to re-verify in Phase 0): `ToolSpec` registry with per-tool timeout; `checkpointer=None` agents; LangGraph Store; MCP client or a decision to use `toolbox-core`; artifact-capable response and SSE protocol; web client.
- **New packages** \[A, each justified under the `new-dependencies` check\]: `sqlglot` (MIT) for validation and rewriting; `toolbox-core` if not using the MCP client; `flint-chart` (npm, MIT) in the web client only. OPA or Cedar only if policies outgrow the file-based evaluator.
- **Infrastructure:** a MySQL reporting replica with secure views; separate read-only users for Tier 1 and Tier 2 (and per data role if required); the Toolbox container; a frozen fixture dataset with fixture users for tests and evals.
- **Data:** an HR reporting-tree feed (employee → manager), refreshed at least daily, for the `org_closure` table.
- **People:** a data owner for the semantic layer and its policies; legal sign-off on the clean-room rules; catalog and policy changes reviewed like code.

### 7.3 Testing strategy

- **Unit:** SQL policy (each allowed and each rejected construct), catalog resolution, artifact lifting, settings validation; no model and no database.
- **Graph:** tool registered only when the flag is on; a denied scope returns the fixed tool error; artifacts reach `AgentResponse` and the SSE `final` event but not `messages`.
- **Integration (marker-gated):** Toolbox plus a MySQL container with fixture data, like the existing Postgres integration job; timeouts and row caps proven against slow queries.
- **Evals:** a new `data` suite with execution accuracy against reference results (set equality on rows, with tolerances), repeated trials and a baseline in `evals/baselines/`; security cases for injected text in rows and schema comments, and attempts to reach unlisted tables.
- **Abuse:** writes, `INTO OUTFILE`, stacked statements, comments hiding a second statement, very large results, and Toolbox unavailable (the tool fails; the rest of Neuron does not).
- **Judged trajectory evals:** next to reference results, a fixed judge model grades each run's full trajectory pass or fail with a rationale (subject-area choice, date filters, row limits, mental math, period-over-period). Results record cost and AI time, and every catalog or policy PR is compared with `main` for regressions (section 4.7, item 8).

### 7.4 Security requirements

- Database user with `SELECT` on approved views only; TLS; `max_execution_time`; separate credentials for Tier 1 and Tier 2 toolsets.
- Model never supplies SQL directly to Toolbox; Neuron validates first and always.
- No user-token passthrough to Toolbox (ADR 0009); per-server secret from `config/`.
- Result values and schema text marked as untrusted data in the model-visible summary.
- Raw SQL returned only to holders of a separate scope; audit event `data_query_executed` with actor, tables, row count and query hash, no SQL text or values.
- `tools.yaml` version-controlled and reviewed like code; Toolbox started with a fixed tool list.

### 7.5 Observability

- Spans under `execute_tool ask_data_agent`: `data.resolve`, `data.validate`, `db.query` (OTel database conventions, pinned in `semconv.py`), with tier, outcome, row count and query hash only.
- Metrics: queries by tier and outcome, validation rejections by rule, database latency, empty-result rate, truncation rate.
- Toolbox exports its own traces to the same Collector (`--telemetry-otlp`); correlate by request ID.
- Dashboards and alerts on rejection-rate and empty-result shifts, not only errors, since a wrong answer returns success.

## 8. Open questions and assumptions

**Phase 0 cannot close until the first six are answered; the rest can be settled during Phases 1–3.**

### 8.1 Blocking decisions (owner)

- [ ] **Product requirement.** Which users, which questions, which data, and what is a correct answer worth? Without it, `AGENTS.md` blocks the ADR.
- [ ] **Entitlement model.** Does every holder of `tools:data_agent` see all approved data, or must rows and columns be filtered per user? If filtered: which verified token claim carries the attribute, and how `security/data_access.py` maps it without passing the user's token to Toolbox.
- [ ] **MySQL topology.** Dedicated reporting replica, reporting schema or production primary? Volume, concurrency and freshness targets?
- [ ] **Semantic-layer ownership.** Who defines and reviews metrics, and does an existing metric store (BI tool, dbt models) already hold them and should be imported rather than rebuilt?
- [ ] **Reporting-tree source.** Which HR system is the system of record for manager relationships and data roles, and how fresh must the copy be?
- [ ] **Clean-room sign-off.** Legal approves section 6.2 before anyone studies or reuses external code.

### 8.2 Technical decisions to settle

| Question | Options | Leaning \[R\] |
| --- | --- | --- |
| Toolbox or a direct read-only driver? | Toolbox sidecar (catalog, credentials outside the app, OTel) vs direct driver (one fewer service) | Toolbox, re-checked at G2 against its operating cost |
| Toolbox over MCP or `toolbox-core`? | Neuron's MCP client (pins, one path for all MCP) vs SDK (fewer packages) | Whichever path v1.0 ships as stable; prefer one path |
| Planning model | Main model vs a smaller model for the spec step | Smaller only if the data eval shows no loss |
| Where artifacts live after the run | Response only vs stored with a reference in the thread | Response plus the analysis spec in the Store; rows not stored in v1 |
| Tier 2 at all? | NL2SQL vs curated metrics only | Decide at G2 from the questions Tier 1 could not answer |
| Clarification mechanics | Return `needs_clarification` vs `interrupt()` inside the subagent | Return a status; the main agent asks, keeping one voice |
| Agent Server parity | FastAPI only vs both paths | Both, once artifacts are tested under Agent Server |
| Own semantic layer and row-security engine, or Cube Core (Apache 2.0) in front of MySQL? | Build in Python (one stack, fits the spec-first pipeline) vs run Cube Core (mature access policies and caching, but a Node service) | Build; run a one-week Cube Core spike in Phase 0 to check, and borrow its policy model either way |
| Policy engine | File-based evaluator vs OPA or Cedar vs OpenFGA for reporting lines | File-based first, behind a Trino-style decision interface, so an engine can replace it |
| Minimum group size | One value for all vs per metric (salary stricter than headcount) | Per policy, default 5, set with HR and legal |

### 8.3 Assumptions to validate

- &#91;A\] Neuron v1.0 ships the seams in section 4.4 roughly as ADR 0009 designs them (registry, `checkpointer=None`, Store, MCP pinning). Each is re-checked in Phase 0; a missing seam becomes a Phase 1 task.
- &#91;A\] LangChain's `content_and_artifact` tool output survives `create_agent`, Neuron's middlewares (failure isolation rewrites `ToolMessage`s) and streaming, so artifacts reach `_final_answer`. Spike before Phase 1.
- &#91;A\] A subagent's model tokens can be told apart from the main agent's in the `messages` stream by namespace, so `AnswerTokenExtractor` streams only the main answer.
- &#91;A\] The production model is reliable at filling the `DataRequest` and the structured `AnalysisSpec`; ADR 0009 records that the NVIDIA development model bounds what evals can show.
- &#91;A\] Toolbox `queryTimeout` and MySQL `max_execution_time` together cancel long queries server-side, not just client-side.
- &#91;A\] Flint's 1.0 API is stable by the time the client integrates it; the README (0.5.1) and the release page (1.0, 21 Oct) disagree today.
- &#91;A\] The project's evidence review found no independently audited agent outcome metrics; accuracy targets must come from Neuron's own eval set, not vendor claims.

### 8.4 Further research

- Read the Toolbox `mysql-execute-sql` and `mysql-sql` tool pages and its MCP authorization page in full; confirm behaviour of a plain `mysql` source under a read-only user.
- Test a MySQL-dialect parser against the red-team set before committing to it.
- Confirm the semantic-layer alternative (curated metrics) against the first 30–50 real questions; if most need ad-hoc joins, Tier 2 moves earlier.

## Sources

**Repository** ([Md-Nisar/neuron](https://github.com/Md-Nisar/neuron), commit `29638c5`, 27 Oct 2026): `ARCHITECTURE.md`, `AGENTS.md`, `CLAUDE.md`, `docs/ROADMAP.md`, `docs/decisions/0001`–`0003`, `0009-extensible-agent-platform.md`, `docs/research-notes.md` (v0.7.0 section and addendum), `docs/releases/v0.7.0-issues.md`, `src/neuron_agent/graphs/main_graph.py`, `state/main.py`, `agents/factory.py`, `models/factory.py`, `schemas/agent.py`, `security/authorization.py`, `security/input_policy.py`, `config/settings.py`, `persistence/migrations.py`, `services/agent_service.py`, `api/main.py`, `pyproject.toml`, `langgraph.json`.

**Proposal:** Neuron Data Agent — Proposed Architecture and Design (uploaded).

**Official documentation** (opened 28 Oct 2026):

- [LangGraph — Use subgraphs](https://docs.langchain.com/oss/langgraph/use-subgraphs)
- [MCP Toolbox for Databases — Go module and README](https://pkg.go.dev/github.com/googleapis/mcp-toolbox)
- [MCP Toolbox — MySQL source](https://mcp-toolbox.dev/integrations/mysql/source/)
- [MCP Toolbox — Tools configuration](https://mcp-toolbox.dev/documentation/configuration/tools/)
- [MCP Toolbox — Authentication](https://mcp-toolbox.dev/documentation/configuration/authentication/)
- [MCP Toolbox — Read-only tools](https://mcp-toolbox.dev/documentation/configuration/security/read-only/)
- [Microsoft Flint — repository and README](https://github.com/microsoft/flint-chart)
- [Microsoft Flint — releases](https://github.com/microsoft/flint-chart/releases)

* [LangChain — Multi-agent patterns](https://docs.langchain.com/oss/python/langchain/multi-agent)
* [LangChain — Subagents](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents)
* [Cube — row-level security](https://docs.cube.dev/docs/data-modeling/access-control/row-level-security)
* [Cube — data access policies announcement](https://cube.dev/blog/introducing-data-access-policies-in-cube-cloud)
* [Trino — Open Policy Agent access control](https://trino.io/docs/current/security/opa-access-control.html)
* [Wren AI — open-core page](https://www.getwren.ai/oss) and [repository license map](https://github.com/Canner/WrenAI)
* [Cube repository](https://github.com/cube-js/cube) (Apache 2.0 / MIT)
* [nao repository](https://github.com/getnao/nao) and the companion [Data Analytics Agents — Landscape and Prior Art](https://claude.ai/artifact/PkUyUEkQmB45J8wWDaF8xv)

**Project docs:** Agent Platform Research 01 (architecture blueprint), Research 02 (harness design study), Enterprise AI Agent Use Cases — Evidence Review (Oct 2026).
