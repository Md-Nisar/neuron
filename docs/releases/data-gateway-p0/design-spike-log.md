# Data Gateway design spike: running log

| | |
| --- | --- |
| Started | 2026-11-23 |
| Status | DG-00.01 (#645) in progress on `spike/data-gateway-p0` (`6b9b90b`): sales and skills schemas, A' hardening, loader and checker done (158 checks pass); sales batch 1 written and second-annotated, awaiting owner review (24 of 25 agree; S-A-017 to adjudicate, F2); skills gets its own set (D6) |
| Scope | DG-E00 stories #645 to #651 only, in dependency order. Track 2 dropped (D2) |
| Baseline | `main` at `dc65af2`; ADR 0016 accepted 2026-11-22 |

This log records findings, discussions, decisions, options, trade-offs and open questions, newest
milestone last. It records; it decides nothing until the owner says so in an entry below.

## 1. Context discovery (2026-11-23)

### 1.1 What was read

| Source | Read |
| --- | --- |
| `docs/decisions/0016-structured-data-gateway.md` | In full |
| `docs/product/NEURON_DATA_GATEWAY_BACKLOG.md` | In full |
| `docs/research/data-analytics/README.md` (research map) | In full |
| `proposals/STRUCTURED_DATA_RECONCILIATION.md` (22 Nov) | In full |
| `proposals/STRUCTURED_DATA_DECISION_AND_HANDOFF.md` (12 Nov) | Parts A, B1 to B8, C2, C3, C4 |
| `proposals/AI_TO_DATABASE_SOLUTION_ARCHITECTURE.md` v2.0 | Changes, section 1, section 18, outline |
| `proposals/CHART_GENERATION_DECISION_AND_HANDOFF.md` | Executive summary |
| `landscape/FINE_GRAINED_DATA_ACCESS_CONTROL_FOR_AGENTS.md` | Section 13 (decisions) |
| `landscape/NAO_LICENSE_AND_FIT_ASSESSMENT.md`, `NEURON_DATA_AGENT_ARCHITECTURE_ASSESSMENT.md` | Outline and the summaries quoted by the research map |
| Code | `knowledge/table_engine.py`, `tools/registry.py`, `security/authorization.py` |
| Issues | #644 to #651 (all DG issues), the issue list for related work |

Not yet read in full: v2.0 sections 2 to 17, the Data Agent assessment body, the landscape study
body, the strategy documents beyond the scope rule, open issues #525 (security audit) and #533
(concurrency review).

### 1.2 Where things stand

- **Decided.** ADR 0016 (accepted 2026-11-22): a separate `neuron-data-gateway` process, reached
  by native `read` tools over HTTP (not MCP); only the gateway executes, one validated `SELECT`,
  read-only, under a database role mapped from the caller's scopes; `sqlglot` allowlist
  validator; Apache Ossie YAML for semantic content; built-in `baseline` engine first; trust
  label `certified` or `exploratory`; PostgreSQL first; off by default.
- **Gated.** Gateway build (P1, DG-E01) needs three things, none met today:
  1. hosted deployment F0.2 has run: **no** (no hosted deployment has ever run);
  2. P0 decision record shows the B8 thresholds met on one engine: **no** (P0 not started);
  3. a first database and user named in ADR 0016: **no**.
- **Allowed now.** Only the proof, DG-E00 (#644, stories #645 to #651), on branch
  `spike/data-gateway-p0` (does not exist yet), no product code, record merged from
  `docs/releases/data-gateway-p0/`. Estimate 3.5 to 4.5 engineer-weeks.
- **Built.** Questions over uploaded CSV/XLSX tables (RAG-11.01, v1.4.0): model-written SQLite
  `SELECT` in process, authorizer allowlist, 5 s, 256 MB, 200 rows. Nothing touches external
  databases.

### 1.3 Map of DG-related work

| ID | Issue | Title | Depends on | State |
| --- | --- | --- | --- | --- |
| DG-E00 | #644 | Proof: engines and safety | | Open, not started |
| DG-00.01 | #645 | Seed the D3 mart (100 answerable, 30 unanswerable, 20 ambiguous, 30 adversarial; double-annotated) | none | Open |
| DG-00.02 | #646 | Hand-write Ossie models for D3 and D1 | 00.01 | Open |
| DG-00.03 | #647 | Arms C (schema only) and B (baseline + Ossie), deterministic scoring | 00.01, 00.02 | Open |
| DG-00.04 | #648 | NVIDIA Auto Ontology at a pinned commit (S1) | 00.01 | Open, P1 priority |
| DG-00.05 | #649 | All arms on D1, D2, D3; Ossie round trip (S2, S4) | 00.03, 00.04 | Open |
| DG-00.06 | #650 | Safety prototype (S3) | 00.01, 00.03 | Open |
| DG-00.07 | #651 | Decision record against B8 thresholds | 00.05, 00.06 | Open |
| DG-E01 to E03 | none | Gateway MVP, Trust, Reach | gates above | Not broken into stories |

Release thresholds (B8): execution accuracy on D3 answerable at least 85%; wrong without refusal
or clarification at most 5%; correct refusal at least 90%; p95 latency of `ask` at most 45 s; S3
counts all zero. Kill criterion: baseline below 60% on D3 with the best model.

### 1.4 History of the design (how we got here)

| Date | Document | Position | Now |
| --- | --- | --- | --- |
| 25 Oct | Access control study | Data layer enforces; agent never decides; token exchange; no identity fields in tool schemas | Principles hold |
| 28 Oct | Landscape | Build own; adopt none of nao, Wren AI, Cube, Vanna | Holds |
| 28 Oct | Data Agent assessment | In-process subagent, model writes an analysis spec, MCP Toolbox executes, Flint charts | Superseded on architecture |
| 12 Nov | Structured data handoff | Separate gateway over MCP, first-party MCP class (draft 0017), Auto Ontology optional | Base design, amended |
| 12 Nov | Chart decision | Neuron-owned chart contract, Flint later, rules before model | Waits on the gateway |
| 18 to 22 Nov | AI-to-database v2.0 + `nl2data-ref` | Semantic-first tiers, DB-enforced security, calibrated router, one service | Source of nine amendments |
| 22 Nov | Reconciliation, ADR 0016 | Gateway + native tools + verified queries in P1 | Accepted |

### 1.5 Validated in this session

| Check | Result |
| --- | --- |
| `nl2data-ref` unit tests | 56 pass (sqlglot 30.33.0) |
| `nl2data-ref` Postgres integration tests (guard bypassed) | 12 pass on PostgreSQL 16.15, a throwaway local cluster |
| Configured LLM endpoint (`LLM_*` variables) | Reachable; NVIDIA hosted API, `nvidia/nemotron-3-ultra-550b-a55b`; a trivial text-to-SQL prompt answered correctly in 1.9 s, with reasoning tokens |
| Docker | CLI present, daemon not running in this container; the Compose stack and Auto Ontology (S1) cannot run here as is |
| PostgreSQL 16 binaries | Present; enough for the D3 mart and S3 without Docker |

### 1.6 Gaps found

| # | Gap | Why it matters |
| --- | --- | --- |
| G1 | The gateway contract (C2) is still written for MCP: one text block, 12,000-byte cap, `mcp_data_*` names, `tools:mcp.data.*` scopes. ADR 0016 switched to native HTTP tools but no HTTP contract exists | P1's first artefact; P0 prototypes should not bake in MCP shapes |
| G2 | "Data analytics" beyond one query is not designed: multi-step analysis, follow-ups over an earlier result, computation on results, charts. Decision 9 says numbers may be "computed by code" from results, but no compute step exists (only `calculator`) | The user-facing value of "analytics" may sit here, not in NL-to-SQL accuracy |
| G3 | Two SQL paths with different safety models: SQLite authorizer (uploaded tables) and `sqlglot` allowlist (gateway). No stated relationship or convergence plan | Two validators to maintain; inconsistent behaviour for users |
| G4 | Where `data:source.*` and `data:role.*` scopes come from is not designed (Keycloak roles, `DEV_PERMISSIONS`, grants UI) | Role mapping is the core of "the user's permissions are the ceiling" |
| G5 | No product requirement or first database is named; analytics is not one of the roadmap's first three use cases | ADR gate 3; risk of effort with no user |
| G6 | D3 double annotation needs a second annotator; nobody is named | DG-00.01 cannot finish without one |
| G7 | p95 latency (45 s) measured on the NVIDIA free tier mixes rate-limit waits with engine time | The latency gate may pass or fail for the wrong reason |
| G8 | Apache Ossie's spec version and availability were not re-verified in this session | DG-00.02 pins it |
| G9 | Auto Ontology needs four services and Postgres 17; no Docker daemon here | S1 needs another environment or a daemon |

### 1.7 Open questions for the owner

| # | Question |
| --- | --- |
| Q1 | Is this spike executing DG-E00 as accepted, re-opening parts of ADR 0016, or designing what ADR 0016 leaves out (G1 to G4)? |
| Q2 | Is there a real first database or user (gate 3)? If not, is P0 still worth 3.5 to 4.5 weeks now? |
| Q3 | What does "data analytics" mean for the first users: single questions, multi-step analysis, charts, or reports? |
| Q4 | Who is the second annotator for D3? Is a model-assisted first pass with human adjudication acceptable? |
| Q5 | Is there a key for a second, stronger model, and may the synthetic D3 schema go to it? |
| Q6 | Where should S1 (Auto Ontology) run, given no Docker daemon here? |
| Q7 | Is this log's location right (`docs/releases/data-gateway-p0/`), and should it live on `spike/data-gateway-p0`? |
| Q8 | Skills questions: share the 100/30/20/30 counts with sales, or add their own? **Answered by D6: their own.** |
| Q9 | Answered by D5. |

### 1.8 Proposed plan for the design spike

Two tracks. Track 1 measures (it answers ADR 0016's gate 2). Track 2 designs what ADR 0016
leaves open. Each step has a check.

**Track 1: proof (DG-E00, as accepted)**

1. Create `spike/data-gateway-p0`; local Postgres 16 harness. Check: one command loads a mart.
2. DG-00.01 D3 mart, starting with schema, roles and hardening, then questions in batches of 25.
   Check: reference SQL returns expected rows per role; no claims means no rows.
3. DG-00.02 Ossie models. Check: validate against the pinned schema.
4. DG-00.03 arms C and B. Check: two identical runs score identically; guard-refused SQL counts
   wrong and never runs.
5. DG-00.06 safety (can run in parallel with 4). Check: three zero counts, case by case.
6. DG-00.04 and 00.05 Auto Ontology (needs an environment with Docker). Check: written steps
   reproduce it.
7. DG-00.07 decision record. Check: every threshold has met or not met with n and interval.

Early exit: after step 4 on the first 50 D3 questions, if arm B is far below the 60% kill line,
stop and record before spending the annotation budget.

**Track 2: design questions (options and trade-offs, no build)**

| Topic | Options to compare |
| --- | --- |
| T1 Native HTTP contract (G1) | Port C2 as JSON over HTTP; OpenAPI-first; keep an MCP-compatible envelope for a later facade |
| T2 Query strategy | Schema-only text-to-SQL; Ossie-grounded baseline; typed metric spec (`query_metric`); verified queries; calibrated router across them |
| T3 Analytics beyond one query (G2) | SQL only; sandboxed compute over result rows (DuckDB or SQLite in the gateway); multi-step plans in the agent over several `ask` calls; chart contract |
| T4 Uploaded tables and gateway (G3) | Keep separate; share the engine interface; route uploaded tables through the gateway's validator |
| T5 Identity and scopes (G4) | Signed assertion (accepted); RFC 8693 token exchange; per-role connection pools; how IdP roles become `data:*` scopes |
| T6 Semantic layer | Ossie YAML (accepted); dbt MetricFlow; Cube; none for P0 arm C |

Criteria for every option: scalability, flexibility, performance, maintainability, integration
complexity, plus security (Neuron's first criterion) and fit with ADR 0016.

## 2. Decisions

| # | Date | Decision | By |
| --- | --- | --- | --- |
| D1 | 2026-11-23 | Spike scope is (a) + (c): carry out DG-E00 as accepted (track 1), and design what ADR 0016 leaves open (track 2). ADR 0016 is reopened only where evidence calls for it. Answers Q1. | Owner |
| D2 | 2026-11-23 | Superseded D1 after section 3 showed analytics is not in the backlog: no design work outside the backlog. Track 2 (T1 to T6) is dropped; gaps G1 to G4 stay recorded but are not worked. The DG-E00 stories are done one at a time, in dependency order, each approach agreed before work starts. | Owner |
| D3 | 2026-11-23 | DG-00.01 approach: work on `spike/data-gateway-p0` (push allowed); sales domain; **add an employee skill assessment dataset** (scope addition to DG-00.01; how it counts toward the 150 questions is open, Q8); second annotator is option (b), a different model's independent pass with the owner adjudicating, recorded as model plus owner review, not two humans; owner reviews each batch of 25. | Owner |
| D4 | 2026-11-23 | Skills dataset lives in the same `d3` database as a separate schema, `skills`. Answers the first half of Q8; how its questions count toward the 150 is still open. | Owner |
| D5 | 2026-11-23 | Fix F1 and F1b with option A': policies keyed on the data role through `app.role_regions`, one login per data role. F1c (timeout) stays a documented residual for the executor. Answers Q9. | Owner |
| D6 | 2026-11-23 | Skills gets its own question set with the same counts as sales: 100 answerable, 30 unanswerable, 20 ambiguous, 30 adversarial. D3 now holds 360 questions (300 plus 60 adversarial), about twice the annotation work; batches of 25 stay. Answers Q8. | Owner |

## 3. Is analytics in the backlog? (2026-11-23)

Short answer: **no, not as its own item.** ADR 0016 and the DG backlog cover one thing:
single-question answers from a database (`ask`, verified queries, later `query_metric`).
Analytics beyond that appears only as excluded, deferred or conditional items.

| Capability | Where it stands | Source |
| --- | --- | --- |
| One question, one `SELECT`, answer with SQL shown | In scope: DG-E01 (P1) | ADR 0016; DG backlog |
| Governed metrics by dimension and time grain (`query_metric`) | In scope: DG-E02 (P2) | DG backlog |
| "Answer card": table, SQL and provenance in the web app | Planned with P2's explanation card; no DG story yet | Handoff P2.4; chart decision §7 |
| Numbers "computed by code" from results | Named in ADR 0016 decision 9, but nothing performs the computing | ADR 0016 |
| Rule-based charts, chart type switching, PNG and CSV export | Research proposal only; "with governed metrics". No backlog story | Chart decision §5, §7 |
| Multi-step analysis, follow-ups over an earlier result | Not mentioned anywhere | none |
| Sandboxed code execution (charts and analysis that need code) | RAG-12.02: phase 5, P2, "Pending"; "kept only if read-only SQL proves insufficient"; highest-risk item | RAG backlog; tracker |
| Cross-source joins | Excluded | Handoff B5 "Deliberately not built" (part of ADR 0016) |
| Charts, dashboards, scheduled reports, forecasting | Excluded | Handoff B5 (part of ADR 0016); chart decision §7 excludes dashboards |
| BI front end | Excluded | Handoff B5 |

Consequences for track 2: topic T3 (analytics beyond one query) designs something no backlog item
covers, and two of its options cross lines ADR 0016 draws (charts and reports are on the
"Deliberately not built" list; code execution is RAG-12.02's highest-risk item). Any of them going
forward needs a product requirement and an ADR amendment, not only a story.

## 4. Findings

### F1 (2026-11-23): claims can be rewritten with `SET`, so the database alone does not hold

- **What.** ADR 0016 decision 5 and `nl2data-ref` revoke `set_config` from PUBLIC so that only
  the `SECURITY DEFINER` function sets claims. The `SET` command is not covered: any role may
  write a custom `app.*` setting. As `d3_analyst` with EMEA claims, `SET LOCAL app.regions =
  'EMEA,APAC,AMER'` raised visible APAC orders from 0 to 1,057 (checker: 1,884 foreign orders).
- **Why it was missed.** The reference attack list tries `set_config` but never `SET`.
- **Exposure.** Needs a second statement. The gateway's validator and single-statement execution
  stop it, so this is a defence-in-depth gap: "the database holds with the guard bypassed" is
  false for claims. It matters for S3 (DG-00.06) and for the customer hardening guide.
- **Evidence.** `spike/data-gateway-p0` at `5728d9d`, `dg-p0/d3/check.py`, PostgreSQL 16.15.
- **Fix options (owner to choose):**

| Option | How | For | Against |
| --- | --- | --- | --- |
| A. Role-keyed policies | One data role per scope (for example `d3_analyst_emea`); policies read a `role_regions` table with `current_user`. `SET ROLE` is limited by membership, so it cannot be forged | Pure database enforcement, no secret; matches ADR 0016's "role-level mapping first" | Roles multiply with scopes; per-user policies (`neuron.user_sub`) stay forgeable |
| B. Signed claims | `set_claims` stores claims plus an HMAC (pgcrypto) bound to backend pid and transaction start; `app.regions()` (`SECURITY DEFINER`) verifies it with a key only its owner can read | Keeps claims and per-user policies; forged values fail closed | A key inside the database; more code; pgcrypto needed (available here) |
| C. Accept and document | Rely on the validator and single-statement execution; state the limit in ADR 0016 | No change | Drops a defence layer the ADR claims |

**F1b and F1c (2026-11-23, raised by an automated security review, confirmed by hand).**

- **F1b.** After `SET LOCAL ROLE d3_analyst`, `RESET ROLE` returns to the login, which may call
  `app.set_claims` with any regions, because the function trusts the caller's array. APAC orders
  visible: 0 to 1,057. This also defeats option B: signing protects a value, not who chose it.
- **F1c.** `SET LOCAL statement_timeout = 0` lifts the role's 15 s default. PostgreSQL 16 has no
  `transaction_timeout` (added in 17).
- All three need a second statement, so the validator and single-statement execution still stop
  them. The checker now has a failing case for each (`514b953`).

**Revised options.**

- **A'.** Role-keyed policies, with **one login per data role** (`d3_login_analyst_emea` and so
  on). A login can then reach only its own role, so neither `SET` nor `RESET ROLE` widens it.
- **B'.** Signed claims, plus `set_claims` checking the requested regions against an entitlement
  table keyed on `session_user`. More code.
- **Either.** The executor issues `SET LOCAL statement_timeout` immediately before the statement,
  and validates that the statement is not a utility statement. A PostgreSQL 17 test mart could
  add `transaction_timeout` as a database-side cap.

Revised recommendation: A'. Recommendation: A for the mart now (the role-level mapping ADR 0016 already chose), B noted as
the path for per-user policies. Either way ADR 0016 decision 5's wording needs correcting, which
is an owner call.

### F1 resolution (2026-11-23, `spike/data-gateway-p0` at `6b9b90b`)

- **Change.** Claims and `app.set_claims` are removed. Every policy compares `region_id` with
  `app.role_regions` for `current_user`. Only the superuser writes that table. Each login is a
  member of exactly one data role: `d3_analyst_emea`, `d3_analyst_apac` or `d3_manager`.
- **Evidence.** `check.py`: 158 checks pass, 0 fail. The `SET app.regions` and `RESET ROLE`
  re-entry cases see 0 foreign orders. Three deliberate breaks were each caught, then reverted:
  opening one policy, mapping a second region to a role, granting a confidential table.
- **Residual.** F1c is reported as `KNOWN`, not as a pass.
- **Deviation from the backlog.** DG-00.01 says "two data roles". The mart now has two kinds of
  role (analyst and manager) but three data roles, because A' needs a role per region scope.
  ADR 0016 decision 5's wording ("claims set only by the gateway", `set_config` revoked as the
  safeguard) no longer describes the mart. Correcting the ADR is an owner action; it is not done.

### F2 (2026-11-23): an outer join to a reference table reports hidden rows as zero

Found by the second annotator on sales batch 1, question S-A-017, "How many sales reps work in
each region?". The reference counts `sales.sales_reps` by region. The second annotator's query
starts from `sales.regions` (reference data, every region visible) and LEFT JOINs the reps
(regional, filtered by row-level security). For the EMEA analyst it answers "Americas 0, Asia
Pacific 0, EMEA 8". Both other regions have 8 reps. Row-level security hides rows; it cannot make
a query say "I don't know", so the hidden rows come back as a confident zero.

Why it matters: B8 counts "wrong answers without refusal" (threshold 5%). This is that kind of
answer, produced by a correct-looking query on a correctly hardened database. It is a property of
row-level security combined with fully visible reference tables, not of this question.

Not acted on (backlog only, D2). Recorded for the stories it touches: the baseline engine and
answer composer (DG-00.03/04) must not present zeros for regions outside the caller's scope, and
the D3 set should keep S-A-017 as a deliberate trap. Owner adjudicates S-A-017's expected answer.

### Sales batch 1 (2026-11-23)

`dg-p0/d3/batches/sales-01.md` on `spike/data-gateway-p0`. 25 answerable questions: counts,
revenue (net amount of completed orders), grouping, top-N, monthly series, growth, return rate,
one reference-only question (S-A-023), and one confidential question (S-A-024: the manager gets
an answer, analysts are refused). Second annotator: `LLM_MODEL` at temperature 0, given the
question and the schema file, never the reference SQL; about 11 s per question.

- 24 of 25 agree for every persona. S-A-025 agrees with the columns in a different order; the
  comparator now accepts that (`ok (columns reordered)`).
- S-A-017 disagrees: see F2.
- S-A-021 was replaced before review: its first wording ("never placed an order") gave 0 for every
  persona, which a blocked or empty query would also give, so it tested nothing.
- No ties at the top-N cut-offs (S-A-008, S-A-011, S-A-016), checked by hand.
