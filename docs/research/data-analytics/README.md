# Structured data, NL-to-SQL and data analytics: map of the research

Everything Neuron has written or built about answering questions from tables and databases, in one
place. This page organises the material; it does not decide anything or settle the conflicts it
lists. As of 2026-11-22, only the uploaded-tables feature (RAG-11.01, v1.4.0) is decided and built.
Everything else is a research proposal.

## Layout

| Folder | Holds |
| --- | --- |
| `landscape/` | Background studies: access control for agents, and the data-agent product landscape |
| `proposals/` | Designs and decision briefs for Neuron, none accepted as an ADR yet |
| `reference-code/` | Tested reference code that backs a proposal (`nl2data-ref`, 68 tests) |

## Reading order

1. [`landscape/FINE_GRAINED_DATA_ACCESS_CONTROL_FOR_AGENTS.md`](landscape/FINE_GRAINED_DATA_ACCESS_CONTROL_FOR_AGENTS.md): who may see which rows, and why the agent must not decide it.
2. [`landscape/NAO_LICENSE_AND_FIT_ASSESSMENT.md`](landscape/NAO_LICENSE_AND_FIT_ASSESSMENT.md): the open-source and commercial data-agent landscape.
3. [`proposals/NEURON_DATA_AGENT_ARCHITECTURE_ASSESSMENT.md`](proposals/NEURON_DATA_AGENT_ARCHITECTURE_ASSESSMENT.md): the first Data Agent design for Neuron.
4. [`proposals/STRUCTURED_DATA_DECISION_AND_HANDOFF.md`](proposals/STRUCTURED_DATA_DECISION_AND_HANDOFF.md): the latest Neuron-specific proposal (Data Gateway, ADR drafts 0016–0018, proof plan).
5. [`proposals/CHART_GENERATION_DECISION_AND_HANDOFF.md`](proposals/CHART_GENERATION_DECISION_AND_HANDOFF.md): charts, which depend on item 4.
6. [`proposals/AI_TO_DATABASE_SOLUTION_ARCHITECTURE.md`](proposals/AI_TO_DATABASE_SOLUTION_ARCHITECTURE.md) and [`reference-code/nl2data-ref/`](reference-code/nl2data-ref/): a general, platform-neutral architecture with tested reference code. It was written without reading items 1–5.

## Documents

| Date | Document | Question | Main recommendation | Status |
| --- | --- | --- | --- | --- |
| 2026-10-25 | Fine-grained data access control for agents | How do agents respect row and column permissions? | Keep authorization out of the agent: the application owns grants, the data layer enforces them, the agent carries the user's token (token exchange, no user fields in tool schemas) | Research |
| 2026-10-28 (update 31 Oct) | Data analytics agents: landscape and prior art | Which open-source data agents exist, and what can Neuron use? | Build Neuron's own Data Agent; adopt none of nao, Wren AI, Cube, Vanna, DB-GPT and others as a backend; clean-room rules | Research; recorded as a decision of 28 Oct in the document |
| 2026-10-28 | Neuron Data Agent architecture assessment | How should Neuron's Data Agent be built? | Specialist subagent behind one tool, `ask_data_agent`; the model writes an analysis spec, never SQL; code compiles it against a semantic layer and runs it read-only through MCP Toolbox; Flint charts | Research |
| 2026-11-12 | Structured data decision and handoff | Adopt NVIDIA Auto Ontology? What about MCP Toolbox? | A separate `neuron-data-gateway` process executes every query itself, PostgreSQL first; Auto Ontology only as an optional engine; Toolbox later as a source adapter; semantic content in Apache Ossie YAML; ADR drafts 0016–0018; a no-code proof (P0) first | Proposal; ADRs not accepted |
| 2026-11-12 | Chart generation decision and handoff | Flint or alternatives for charts? | Flint later as the first optional renderer; a Neuron-owned chart contract; rules before the model | Proposal; depends on the gateway |
| 2026-11-18, updated 2026-11-22 | AI-to-database solution architecture v2.0 + `nl2data-ref` | What is the most robust general design for NL access to databases? | Semantic layer first, verified queries second, guarded generated SQL as a labelled fallback; database-enforced security; vendor and Auto Ontology bake-off before building | Research (PR #642); not reconciled with the rows above |

## What is built

| Item | Where | Notes |
| --- | --- | --- |
| Questions about uploaded tables (CSV, XLSX) | ADR 0014 amendment "tables" (2026-11-14); backlog RAG-11.01; released in v1.4.0 (2026-11-17) | `find_tables` and `query_table` in `src/neuron_agent/knowledge/tools.py`. The model writes one SQLite `SELECT`, run in process with an authorizer allowlist (`knowledge/table_engine.py`), 5 s and 256 MB limits, at most 200 rows, results taint the run. The amendment replaced the backlog's earlier "DuckDB plus sqlglot" plan |
| Table eval cases | `tests/fixtures/knowledge/table_cases.json` | Cases that search-only answers failed |
| Knowledge tables with role grants and row-level security | RAG-01.02 (#417) | Applies to the Knowledge Engine's own storage, not to external databases |

Not built: connections to external databases, a Data Agent or Data Gateway, a semantic layer, charts. ADR numbers 0016–0018 exist only as drafts inside the structured data decision; 0015 is reserved for the product-direction ADR.

## Where the documents agree and differ

For the reconciliation step. Each cell is what that document proposes; nothing here is a decision.

| Topic | Data Agent assessment (28 Oct) | Structured data decision (12 Nov) | AI-to-database architecture (22 Nov) | Built (v1.4.0) |
| --- | --- | --- | --- | --- |
| May the model write SQL? | Never; it writes an analysis spec | The agent model never does; engines inside the gateway may propose SQL, which the gateway validates | Not for certified answers; yes for a labelled exploratory fallback | Yes, one SQLite `SELECT` on an uploaded table |
| Where SQL runs | MCP Toolbox, read-only | The gateway process only | The service's executor; MCP Toolbox for verified queries | In process, SQLite |
| MCP Toolbox | Adopt as the execution layer | Not now; a later source adapter | Adopt for verified queries and catalog lookups | Not used |
| NVIDIA Auto Ontology | Not covered | Optional engine behind the gateway; not a foundation | Bake-off candidate | Not used |
| Identity to the data | Not the focus | Signed `Neuron-Identity` assertion; query runs under a role mapped from the caller (ADR draft 0017) | Per-user OAuth where the warehouse supports it; otherwise database-enforced claims (tested on Postgres 16) | Knowledge bases filtered by `allowed_kbs` |
| Semantic layer | Governed semantic layer | Semantic content in Apache Ossie YAML, engine-neutral | Platform-native, or MetricFlow / Cube | None |
| SQL validation | Compile and validate in code | One validated `SELECT`, read-only transaction, timeout, row cap | sqlglot function allowlist, then database limits | SQLite authorizer allowlist |
| First data source | Not fixed | PostgreSQL only | Warehouses in general | Uploaded CSV and XLSX |
| Evaluation | Not detailed | Proof thresholds (P0, "B8") before any product code | Double-annotated golden set, calibrated routing, bake-off | `table_cases.json` |
| Charts | Flint | Flint later (chart decision) | Not covered | None |

The fine-grained access control study (25 Oct) underpins the identity row in all three proposals; the landscape study (28 Oct) underpins the build-own direction in the Data Agent assessment.

## Related material elsewhere

- `docs/decisions/0014-knowledge-engine.md`, amendment "tables": the only accepted decision in this area.
- `docs/product/NEURON_RAG_PRODUCT_BACKLOG.md`, epic RAG-E11 (issue #593, open) and story RAG-11.01 (#594, closed).
- `docs/research/rag/` (three consolidated RAG reports): table handling as part of retrieval.
- `docs/research/enterprise-strategy/`: data questions appear briefly in the 18-month roadmap, the domain adaptation strategy and the current architecture assessment.
- `docs/ROADMAP.md`, v1.4.0 row.
