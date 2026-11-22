# Structured Data: Reconciling the Four Proposals

| | |
| --- | --- |
| Date | 2026-11-22 |
| Status | **Decided 2026-11-22.** The owner accepted all nine recommendations in section 6, with native tools (draft A only). Recorded as [ADR 0016](../../../decisions/0016-structured-data-gateway.md). No production environment exists, so only the proof (P0) starts now. |
| Question | Four documents propose how Neuron should answer questions from databases. Where do they agree, where do they conflict, and what single design should go forward? |
| Inputs | [Data Agent assessment](NEURON_DATA_AGENT_ARCHITECTURE_ASSESSMENT.md) (28 Oct), [structured data decision](STRUCTURED_DATA_DECISION_AND_HANDOFF.md) (12 Nov), [chart decision](CHART_GENERATION_DECISION_AND_HANDOFF.md) (12 Nov), [AI-to-database architecture v2.0](AI_TO_DATABASE_SOLUTION_ARCHITECTURE.md) (22 Nov), and the principles in [fine-grained data access control](../landscape/FINE_GRAINED_DATA_ACCESS_CONTROL_FOR_AGENTS.md) (25 Oct) |
| Review | Revised the same day after an architecture review: section 3.6 (how Neuron reaches the gateway), the sample-size change in section 5 and the risks in section 7 were added. |
| Method | The structured data decision and the v2.0 architecture were read in full; the Data Agent assessment (summary, sections 4 and 4.2), the access-control decisions (section 13) and the chart summary were read for their recommendations. Neuron's constraints were re-checked in code at `4f64d1b`. NVIDIA Auto Ontology was re-checked upstream on 2026-11-22. |

## 1. Outcome

1. **Go forward with the Data Gateway design from the 12 November decision, amended as in section 3.7.** It is the only proposal written against Neuron's actual code and rules, and its constraints still hold. The v2.0 architecture reaches the same shape from the general literature; its contribution is tested code and nine amendments, not a different architecture.
2. **The proposals agree on more than they disagree.** All four want semantic or typed access before free SQL, validation in code, read-only execution under the user's own permissions, honest refusal, and accuracy measured on Neuron's own questions.
3. **Five real conflicts remain** (sections 3.2 to 3.6): who may write SQL, where SQL runs, the role of MCP Toolbox, whether certified answers come before generated ones, and how Neuron reaches the gateway. Each has a recommendation with its evidence.
4. **One ADR draft if Neuron reaches the gateway through native tools, as recommended; two if through MCP** (section 4). Drafts 0016 and 0018 merge into one Data Gateway ADR. Draft 0017 is needed only for the MCP route, because it amends ADR 0009 for every MCP server.
5. **The proof's release thresholds need larger samples** (section 5). On 25 answerable questions, 22 correct (88%) has a 95% interval of 70% to 96%, and 8 unanswerable questions cannot show a 90% refusal rate: one miss is 87.5%.
6. **Superseded:** the Data Agent assessment's in-process subagent with Toolbox execution. Its two lasting ideas, a typed analysis spec instead of SQL and a data component that writes no prose, survive as `query_metric` and the gateway's no-prose envelope.
7. **Nine owner decisions** are listed in section 6, each with a recommendation; risks of this recommendation are in section 7.

## 2. What changed since 12 November

| Change | Effect on the design |
| --- | --- |
| v1.4.0 shipped `query_table`: the model writes one SQLite `SELECT` over the user's own uploaded table, run in process behind an authorizer allowlist (ADR 0014 amendment "tables"). | The rule "never free-form SQL from the model" (`DOMAIN_AGNOSTIC_INTEGRATION_ARCHITECTURE.md`) already has an accepted exception. The rule needs restating, not defending (section 3.2). |
| Auto Ontology upstream is at version 1.3.0 (`pyproject.toml`, commit of 2026-11-20). The repository still has no release tags; its only tag is `pre-main-merge-backup`. | The B1 condition "a tagged, versioned release" is still unmet. The security notes in v2.0 came from a 25 October snapshot and must be re-checked at the pinned commit in spike S1. |
| A VLDB 2026 study found annotation errors in 52.8% of BIRD Mini-Dev and 62.8% of checked Spider 2.0-Snow examples. | Proof dataset D2 (BIRD Mini-Dev) is indicative only. Gates stay on D3, Neuron's own set, as the 12 November plan already does. |
| MCP specification 2026-07-28 is stateless; MCP Python SDK 2.0 renamed `FastMCP` to `MCPServer`. | The gateway's MCP server pins its protocol revision and SDK major version. |
| `nl2data-ref` provides a sqlglot allowlist guard (27 attacks refused) and a Postgres 16 setup that holds with the guard bypassed (12 integration tests). | Starting points for gateway tasks P1.7 and P1.8 (section 3.7, A3 and A4). |

Still true at `4f64d1b`: the MCP client reaches only public addresses in staging and production (`security/egress.py`, `PublicOnlyBackend`); every `read` MCP tool needs approval once a run is tainted (`tools/registry.py`, `gated_after_taint`); MCP output is capped at 16,384 bytes (`config/settings.py`).

## 3. Topic by topic

### 3.1 Settled points (adopt as stated)

| Topic | Position | Where it is specified |
| --- | --- | --- |
| Permissions | Authorization is enforced by the data layer, never by the model; tool schemas carry no identity fields | Access control D3, D4, D6; decision C2 identity model |
| Execution | One `SELECT`, read-only transaction, statement timeout, row cap | Decision C2; v2.0 §10 |
| Validation | Parse with a SQL parser; allow-listed relations and functions; no locking or `INTO` | Decision C2; v2.0 §10.2 |
| No prose from the data component | Rows and references go back; the main agent writes the answer | Data Agent §4.1; decision envelope rules |
| Explainability | Every answer shows its SQL and the terms used | Decision B6 rows 2 and 5; v2.0 §14.2 |
| Refusal | "The data does not hold this" beats a guess | Decision B6 row 5; v2.0 §5.4 |
| First source | PostgreSQL. v2.0 is written for warehouses in general and does not contest this; its tested code targets Postgres 16 | Decision ADR draft 0016 |
| Evaluation before claims | Measured accuracy on Neuron's own questions; no "comparable to Cortex Analyst" | Decision B8; v2.0 §15 |
| Charts | Later, behind a Neuron-owned chart contract. This replaces the Data Agent assessment's Flint-first position; v2.0 does not cover charts | Chart decision §1 |

### 3.2 Conflict 1: who may write SQL

| Data Agent (28 Oct) | Decision (12 Nov) | v2.0 (22 Nov) | Shipped (v1.4.0) |
| --- | --- | --- | --- |
| Never; the model writes an analysis spec | The agent model never; engines inside the gateway propose SQL, which the gateway validates | Not for certified answers; yes for a labelled exploratory fallback | Yes, against the user's own uploaded table |

**Recommendation: restate the rule as "model-written SQL never reaches a connected database directly."** Model-written SQL may run in exactly two places: the in-process sandbox over the user's own uploaded tables (as shipped), and inside the Data Gateway after validation and under the caller's database role. The agent gets no `run_sql` tool.

**Why.** The 12 November wording already allows engines to propose SQL; the baseline engine is a model. What the old rule protected against, a model's SQL running with shared credentials against company data, is prevented by gateway execution, validation and the database role. The `query_table` exception is safe for a different reason: the data is the user's own and the sandbox has no credentials. Update `DOMAIN_AGNOSTIC_INTEGRATION_ARCHITECTURE.md` when the ADR is accepted.

### 3.3 Conflict 2: where SQL runs

| Data Agent | Decision | v2.0 |
| --- | --- | --- |
| In process, through MCP Toolbox | A separate `neuron-data-gateway` process | One service with in-process tools; Toolbox for verified queries |

**Recommendation: the separate gateway process.** The agent process handles untrusted model output, so database credentials and drivers do not belong in it. That is a security boundary in Neuron specifically. v2.0's "one deployable" advice was for a greenfield service and does not account for it. v2.0's own rule, "MCP only at boundaries", is satisfied: the gateway is a boundary.

### 3.4 Conflict 3: MCP Toolbox

| Data Agent | Decision | v2.0 |
| --- | --- | --- |
| Adopt as the execution layer | Not now; a later source adapter on a named trigger | Adopt for verified queries and catalog lookups |

**Recommendation: keep the 12 November position.** PostgreSQL first needs no extra driver, and verified queries fit in gateway configuration. v2.0's own research supports deferral: Toolbox's identity features sit outside the MCP specification and give row-filter parameters, not user impersonation. The triggers in decision B3 stand: an unreachable source, more than about 20 curated queries, or a Google Cloud customer.

### 3.5 Conflict 4: certified answers before generated ones?

| Decision | v2.0 |
| --- | --- |
| P1 ships `ask` (baseline engine, generated SQL); P2 adds `query_metric` and verified queries | Certified tiers first; generated SQL is a later, labelled fallback |

**Recommendation: keep `ask` in P1, and move verified queries from P2 into P1.** `ask` is needed in P1 because it is the proof's control arm and the contract's main tool. Verified queries are small (decision B6, row 6, sizes them S) and give a certified path from the first release. `query_metric` stays in P2: it needs a compiler and a certified model. Every P1 answer carries a trust label (A1), so generated answers are never presented as certified.

### 3.6 Conflict 5: how Neuron reaches the gateway

| Data Agent | Decision | v2.0 |
| --- | --- | --- |
| A native tool, `ask_data_agent`, in process | An MCP server of a new "first-party" class (draft 0017): private-address allow-list, signed identity assertion, and an exemption from the after-taint approval | MCP only at external boundaries; internal calls are typed functions |

**Recommendation: native Neuron tools that call the gateway over HTTP, not MCP.** The gateway stays a separate process holding the credentials; only the transport changes.

**Why.**

- **No platform-wide change.** The MCP route needs draft 0017 to amend ADR 0009 for every MCP server: a trust class, a private-address allow-list and a signing key. Native tools need none of it.
- **The approval gate applies to MCP, not to native tools.** `tools/registry.py` gates only `source == "mcp"` read tools after a run is tainted. Native tools such as the knowledge tools are `builtin`, `read` and `taints_run=True`, and run without a pause. Native gateway tools follow the same path, so combined document-and-data answers work without relaxing the MCP rule. The exemption is not hidden: the ADR must state that the question text leaves the process only for the first-party gateway at a configured address.
- **Typed contract, no text cap.** Native tools get typed arguments and a structured result, instead of MCP's text-only output capped at 16,384 bytes. A size cap stays, for the model's context.
- **Fewer moving parts.** No tool pins to regenerate, no MCP protocol or SDK version to track (section 2).

**What it costs.** Other MCP clients cannot use the gateway directly. If that becomes a requirement, the gateway can add an MCP facade over the same contract later, and draft 0017 returns then. Neuron ships a small client and four tool definitions, built with the `add-tool` checklist.

### 3.7 Amendments to the gateway design

| # | Amendment | Source | Changes |
| --- | --- | --- | --- |
| A1 | Envelope field `explain.trust`: `certified` only for `query_metric` and verified queries, `exploratory` for `ask` | v2.0 §1.1 | Contract C2 (minor version 1.1) |
| A2 | Verified queries in P1 | Section 3.5 | Move task P2.2 into P1 |
| A3 | Validator starts from `nl2data-ref/guard.py`: function allowlist, `Lock` and recursive-CTE rejection, `LIMIT` clamp, comments stripped on output (sqlglot keeps them by default). New dependency `sqlglot`, pinned; it was already planned for RAG-11.01 before the SQLite amendment | v2.0 §16.3; tests | Task P1.8 |
| A4 | Database hardening for the D3 mart and the documented customer setup: `set_config` revoked from PUBLIC, row-level security forced and failing closed, claims set only by the gateway. Required in Neuron's test mart; recommended to customers (revoking `set_config` can affect other applications on a shared database) | v2.0 §16.7; 12 Postgres tests | Tasks P0.1, P1.7, operations docs |
| A5 | `query_metric` filter operators are a closed enumeration; values are typed and escaped by the gateway | v2.0 §16.4 | Contract C2 |
| A6 | Runtime check that every number in the final answer appears in, or is computed by code from, an envelope's rows | v2.0 §16.5 | Task P2.3 |
| A7 | Model egress classes for engine calls: schema and certified terms by default; sample values and rows only when the source's policy allows | v2.0 §11 | Answers open question 4; gateway source configuration |
| A8 | Literal values ("NY" or "New York") are resolved by a live query under the caller's role, never from a shared value index | v2.0 §10.1 T5 | Baseline engine (P1.10) |
| A9 | D3 reference answers are double-annotated and disagreements adjudicated before any gate uses them | v2.0 §15.1; VLDB 2026 | Task P0.1 |

### 3.8 What is dropped or deferred

| Item | From | Why |
| --- | --- | --- |
| In-process Data Agent subagent executing through Toolbox | Data Agent | Credentials in the agent process (section 3.3) |
| Vendor bake-off (Cortex, Genie, Fabric, Google) | v2.0 | No accounts, and PostgreSQL comes first; the Auto Ontology comparison is already spikes S1 and S2 |
| Capacity model, SLOs and runbooks for the gateway | v2.0 | No hosted environment until roadmap F0.2; revisit with the first deployment |
| Curator console | v2.0 | No admin UI until F5.1; verified queries and the semantic model are files under review |
| Own semantic modelling language or metric engine beyond simple aggregates | Data Agent | Decision B2; consume Apache Ossie YAML |

## 4. Consolidated ADR drafts

With native tools (section 3.6), only draft A is needed. With MCP, draft B is added. ADR numbers follow decision C1: 0015 stays reserved for the product-direction ADR unless the owner says otherwise (section 6, item 6).

### Draft A: Structured data questions through a Data Gateway (replaces drafts 0016 and 0018)

**Context.** Users want answers from databases as well as documents. ADR 0001 and `CLAUDE.md` forbid new retrieval and services without a product requirement and an ADR. No engine has independent accuracy evidence. v1.4.0 already runs model-written SQL over uploaded tables in a sandbox.

**Product requirement.** As in draft 0016: a signed-in user asks a plain-language question about a database their organisation connected, and receives an answer computed by a read-only query that ran with their own data permissions, with the SQL, the business terms and a trust label shown, or an explicit statement that the data does not hold the answer.

**Decision.**

1. A separate process, `neuron-data-gateway`, in this repository, implements one Neuron-owned contract (decision C2, version 1.1 with amendments A1 and A5). Neuron core never imports a provider or a database driver for it.
2. Neuron reaches the gateway through native `read` tools with `taints_run=True`, over HTTP to one configured address (`APP_DATA_GATEWAY_URL`), authenticated by a service credential plus a short-lived identity assertion minted from the runtime `AuthorizationContext` (claims as in decision C2). In staging and production it is the only private address Neuron's API process may call, and the question text the tools send goes nowhere else. The user's bearer token is never forwarded.
3. Model-written SQL never reaches a connected database directly. Only the gateway executes: one validated `SELECT` in a read-only transaction, under a database role mapped from the caller's scopes in gateway configuration, with a statement timeout and a row cap. The sandbox over uploaded tables (ADR 0014 amendment "tables") is unchanged.
4. The validator uses a function allowlist and rejects locking clauses, `INTO`, data-modifying and recursive CTEs, relations outside the allow-listed schemas, and more than one statement. Adding a SQL dialect requires a reviewed allowlist and a failing-input test suite for that dialect.
5. Answers carry `trust`: `certified` for verified queries and `query_metric`, `exploratory` for generated SQL.
6. Semantic content is Apache Ossie YAML under version control; only certified terms are served. Engines implement one interface (question, source and semantic context in; SQL proposal and references, or a refusal code, out), never execute against the governed source, and never return prose.
7. The built-in `baseline` engine ships first. NVIDIA Auto Ontology is an optional adapter, pinned to a commit, only after spike S2 passes. MCP Toolbox is a source adapter only after a trigger in decision B3 fires. No engine is required by the contract, the evaluation or the default configuration.
8. Literal values are resolved by live queries under the caller's role; there is no shared value index.
9. The first source type is PostgreSQL. The feature is off by default and experimental until the B8 release thresholds are met and recorded.

**Consequences.** A second deployable to secure and operate. A package boundary `data_gateway/` that imports nothing from `api/`, `services/`, `graphs/`, `agents/`, `models/` or `knowledge/`, enforced by a boundaries test. A new pinned dependency, `sqlglot`. Two new settings, `APP_DATA_GATEWAY_URL` and the assertion signing key, with the safeguards in decision B7. Four gateway tools added through the `add-tool` checklist. The "Deliberately not built" list in decision B5 is part of this ADR.

**Alternatives rejected.** Decision B4's table; sections 3.3 (in-process execution) and 3.6 (MCP transport) of this note.

### Draft B, only for the MCP route: First-party MCP servers and the identity assertion (draft 0017, amends ADR 0009)

If the owner chooses MCP over native tools, adopt draft 0017 as written in the decision's section C1, with two additions:

- The first-party server pins its MCP protocol revision and SDK major version; a change of either is a contract change.
- Decision 5, which exempts first-party `read` tools from the after-taint approval, still needs the owner's sign-off (section 6, item 2). Without it, combined document-and-data answers pause for approval and everything else stands.

## 5. Changes to the proof plan (decision C3, P0)

| Task | Change |
| --- | --- |
| P0.1 Seed D3 | Apply A4 hardening to the mart; double-annotate reference answers (A9); reuse the `nl2data-ref` attack corpus for the 30 adversarial cases |
| P0.3 Arms C and B | Validate both arms' SQL with the A3 guard; score with `nl2data-ref`'s result comparator |
| P0.4 Auto Ontology (S1) | Pin an upstream commit at version 1.3.0 or later; re-check its Postgres connector (read-only transaction, `set_config` use) at that commit |
| P0.5 Run all arms | Report D2 separately as indicative, because of its label noise |
| D3 size | At least 100 answerable, 30 unanswerable and 20 ambiguous questions, so every threshold can be measured: 85 of 100 correct has a 95% interval of 77% to 91%, against 70% to 96% for 22 of 25. Report Wilson intervals beside every rate; gate on the point estimate with that minimum size |
| P0.6 Safety (S3) | Run the guard-bypassed Postgres tests against the D3 mart as well as the gateway prototype |

Thresholds in decision B8 are unchanged; only the sample behind them grows.

## 6. Decisions for the owner

**Owner decision, 2026-11-22: all nine recommendations accepted.**

| # | Decision | Recommendation |
| --- | --- | --- |
| 1 | Is there a real product requirement and a first database or user (decision question 2)? | Record the requirement as experimental. If there is no real user yet, run P0 only and stop. |
| 2 | Reach the gateway through native tools or MCP (section 3.6)? This replaces decision question 3, the after-taint exemption, which only the MCP route needs. | Native tools. |
| 3 | Gateway P1 before or after RAG-E09, and after F0.2 (decision question 1)? | P0 now; P1 after F0.2, as the decision recommends. |
| 4 | Verified queries in P1 (section 3.5)? | Yes. |
| 5 | Which model for the engine, and which egress class by default (decision question 4, A7)? | Neuron's configured model; schema and certified terms only by default. |
| 6 | ADR numbering and shape: draft A only (draft B too if MCP is chosen), 0015 still reserved (decision question 7)? | Yes. |
| 7 | Is A4 hardening required of customers or only recommended? | Required in Neuron's test mart and reference deployment; recommended to customers. |
| 8 | Role-level mapping first, or per-user row-level security from day one (decision question 6)? | Role-level first; `neuron.user_sub` is available for customers who key policies on it. |
| 9 | Positioning: "measured accuracy on your own questions" instead of "comparable to Cortex Analyst" (decision question 8)? | Yes. |

## 7. Risks of this recommendation

| Risk | Mitigation |
| --- | --- |
| Analytics is not among the first three use cases in the 18-month roadmap, so this can pull effort from committed work | Decision 1 gates everything after P0 on a recorded product requirement |
| A second deployable with no hosted environment to run it in | P1 waits for F0.2; P0 needs no product code |
| Apache Ossie is young (incubating since 2026); its format may change | Pin the spec version the store validates against; the baseline engine reads only metrics, dimensions and terms |
| Enlarging D3 to 150 questions costs authoring and double-annotation time | Draw questions from real use where a design partner exists; record authoring hours as the 12 Nov plan does |
| `sqlglot` behaviour shifts between versions (comment handling, `qualify`) | Exact pin; the guard's attack corpus runs on every upgrade |
| The identity assertion's signing key becomes a high-value secret in the API process | 60-second lifetime, audience-bound, single use, rotation through JWKS (decision B7); replaceable by IdP token exchange with no contract change |
| Native tools make the gateway Neuron-only | An MCP facade can be added later over the same contract (section 3.6) |

## 8. Status of each document after this note

| Document | Status |
| --- | --- |
| Structured data decision (12 Nov) | Base design, amended by this note |
| AI-to-database architecture v2.0 | General reference; its code is the starting point for A3 and A4 |
| Data Agent assessment (28 Oct) | Superseded on architecture; kept for its analysis and history |
| Chart decision (12 Nov) | Unchanged; still depends on the gateway |
| Fine-grained data access control (25 Oct) | Principles apply unchanged |
| Data-agent landscape (28 Oct) | Unchanged reference |
