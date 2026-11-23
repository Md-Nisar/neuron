# Data Gateway design spike: running log

| | |
| --- | --- |
| Started | 2026-11-23 |
| Status | DG-00.01 (#645) in progress on `spike/data-gateway-p0` (see git log): sales and skills schemas, A' hardening, loader, checker and batch runner done; all 300 questions accepted (sales and skills: 100 answerable, 30 unanswerable, 20 ambiguous each; 1,018 checks pass; batches self-approved under D12); adversarial cases next |
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
| D7 | 2026-11-23 | Sales batch 1 accepted as written. S-A-017 keeps the reference answer (reps the persona can see) and stays in the set as a deliberate F2 trap. Finish all sales questions before starting skills. | Owner |
| D8 | 2026-11-23 | Sales batch 2 accepted. S-A-035 keeps the reference answer and stays as an F2 trap. S-A-047 swapped for a sharper question; because the new one is unreviewed, it moves to batch 3 and batch 2 is accepted with 24 questions. | Owner |
| D9 | 2026-11-23 | Sales batch 3 accepted. S-A-052 keeps the reference answer and stays as an F2 trap. For S-A-054 and S-A-061, months as dates and months as numbers are both correct: the second annotator's answer is stored as an accepted alternative (`alternatives` in `questions.jsonl`). | Owner |
| D10 | 2026-11-23 | Sales batch 4 accepted as recommended: S-A-096 keeps the reference (the annotator's query failed); S-A-098 accepts region names as an alternative to ids. The 100 answerable sales questions are complete. | Owner |
| D11 | 2026-11-23 | Sales batch 5 accepted as recommended: S-U-020 to S-U-022 stay "refuse" (the evidence queries show the entity is absent). Record design for unanswerable questions confirmed: expected behaviour, kind, why, and an evidence query where the answer depends on the data. | Owner |
| D12 | 2026-11-23 | Sales batch 6 accepted as recommended: S-U-027 stays "refuse"; S-M-011, S-M-014 and S-M-017 replaced by S-M-021 to S-M-023; S-M-013 replaced by S-M-024 ("average discount": plain vs value-weighted). Then: move to skills, write all remaining batches, and **approve them myself**. | Owner |

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

### Sales batch 2 (2026-11-23)

`dg-p0/d3/batches/sales-02.md`. 25 answerable questions, S-A-026 to S-A-050: quarters, statuses,
per-rep revenue, discount value, gross value, returns by category, top 3, distinct and repeat
customers, lines per order, share of revenue, largest order, days to return, and one more
confidential question (S-A-048, average base salary).

- First run: 22 of 25 agreed. After the two fixes below, 24 of 25 agree.
- S-A-028 was a comparator fault, not a disagreement. Both queries gave the same revenue to the
  cent, but the reference comparator buckets numbers to 6 significant digits, so 2,716,515.00
  and 2,716,514.996 fall into different buckets. `batch.py` now compares numbers within 0.01.
  Batch 1 was re-run with the new comparator: unchanged, 24 of 25.
- S-A-047's first wording ("sold below the list price") was mine and ambiguous: the annotator
  read "sold" as completed orders only, as batch 1 had taught. Reworded to "in orders of any
  status"; the re-asked annotator then agrees. Owner to confirm the rewording.
- S-A-035 disagrees: a second F2 case. "How many customers are there in each country?" The
  annotator LEFT JOINs customers to the fully visible countries table and reports 0 customers
  in the 7 countries outside an analyst's region.

### Sales batch 3 (2026-11-23)

`dg-p0/d3/batches/sales-03.md`. The new S-A-047 (lines with a discount of 10% or more) plus
S-A-051 to S-A-074: harder questions, including a median, a window function (cumulative and
month-over-month), year-over-year per region and per rep, a return rate by category, cross-tabs,
customer cohorts, revenue net of returns, a weekday, and a confidential one (S-A-069, total pay).

- Comparator change: the annotator may return extra columns (S-A-070 added the customer id next
  to the name). Batches 1 and 2 were re-run: unchanged.
- One tie checked: in S-A-070, two EMEA customers returned 27 units each. They are inside the
  top 3, not at the cut-off, so the question ignores row order.
- 22 of 25 agree. The 3 disagreements:
  - S-A-052 (revenue per region, 2024 and 2025): a third F2 case. The analysts get 0 for the
    regions they cannot see. For the manager the numbers match; only the label differs
    (region name instead of id).
  - S-A-054 and S-A-061 (cumulative and month-over-month revenue): the numbers match for every
    persona. The annotator labels months as dates (2025-02-01), the reference as month numbers
    (2). The comparator does not treat these as equal, on purpose: deciding when two labels mean
    the same thing is the owner's call, not the comparator's.

### Sales batch 4 (2026-11-23)

`dg-p0/d3/batches/sales-04.md`. S-A-075 to S-A-100, 26 questions, which completes the 100
answerable sales questions. More everyday wording: date ranges ("first half of 2025", "last
quarter of 2024"), terms only the column comments explain ("small and medium business" for SMB),
named countries and products, shares, HAVING, and one confidential question (S-A-087).

- Caught before running: S-A-094 named a product that does not exist; changed to "Edge Server".
- No ties at the top-1 cut-offs (S-A-079, S-A-083, S-A-090, S-A-099), checked by hand.
- 24 of 26 agree. The 2 disagreements:
  - S-A-096 (highest discount, and how many lines got it): the annotator's query fails with a
    GroupingError (an aggregate without GROUP BY). An annotator mistake; the reference stands.
  - S-A-098 (revenue per segment per region): the numbers match for every persona; the annotator
    labels regions by name, the reference by id. Same kind of case as the month labels in D9.

### Sales batch 5: unanswerable, part 1 (2026-11-23)

`dg-p0/d3/batches/sales-05.md`. S-U-001 to S-U-025. The other 5 unanswerable questions go with
the 20 ambiguous ones in batch 6.

Record shape (a choice of mine, open to the owner): no reference SQL, since there is nothing to
query. Instead, `expected` is `{"behaviour": "refuse"}` for every persona, with `kind`
(missing_data, out_of_range, nonexistent_entity, subjective, outside_database) and `why`. When
the question depends on the data (a year, country, product, rep or segment that is not there),
an `evidence_sql` must return 0 as the superuser. `check.py` re-runs every evidence query, so a
change to the seed that made such a question answerable would fail the check.

Second annotator for non-answerable categories: the same model, asked to classify the question
as answer, clarify or refuse, given the schema only.

- 22 of 25 agree: all 15 missing-data, 4 out-of-range, 1 subjective, 1 outside-database and the
  Government segment question (the schema's CHECK constraint lists the segments).
- S-U-020 (Mexico), S-U-021 (Quantum Router), S-U-022 (rep John Smith): the annotator says
  answer, or clarify, because it sees the schema but not the values. Nothing in the schema says
  Mexico, that product or that rep is absent; only the data does. The evidence queries confirm
  each is absent. A schema-only engine would answer "0" for these, a wrong answer without
  refusal, unless it looks up values before answering.

### Sales batch 6: unanswerable part 2 and ambiguous (2026-11-23)

`dg-p0/d3/batches/sales-06.md`: S-U-026 to S-U-030 and S-M-001 to S-M-020.

Correction to what I told the owner when batch 5 was sent: recording each reading of an ambiguous
question is not beyond the backlog. DG-00.01 asks for "reference SQL and expected results per
role" for the ambiguous questions too. Each ambiguous record therefore holds `interpretations`,
each with a label, reference SQL and an expected result per persona; `check.py` re-runs them.
`batch.py` flags a question whose readings give the same answer for some persona, since a direct
answer would then be right for that persona.

20 of 25 agree. The 5 disagreements:

- S-U-027 (returns from Spain): the annotator says clarify (count of returns or units?). Spain is
  absent (evidence 0), the same schema-only limit as S-U-020 to S-U-022.
- S-M-011 ("How many orders were there in 2025?"), S-M-014 ("average price of our products") and
  S-M-017 ("revenue for Hardware", no period): the annotator says answer, picking one reading
  (all statuses; list price; both years). Each pick is a reasonable default that a careful
  analyst could state and use, so these are weak tests of clarification. My view: the annotator
  is right about these three.
- S-M-013 ("revenue from new customers in 2025"): the annotator agrees it is ambiguous, but for
  the EMEA analyst both readings give the same answer: every EMEA customer whose first order
  was in 2025 also opened their account in 2025 (28 and 28).

Drafted replacements, `dg-p0/d3/batches/sales-06b.md`, all three agree (clarify), with no ties
at their top-1 cut-offs: S-M-021 (category that grew the most: USD or percent), S-M-022 (largest
market: revenue or completed orders), S-M-023 (most valuable segment: total or per customer).
For some analysts, two readings name the same country or segment with a different measure; the
ambiguity is in the measure.

### Self-approved batches (2026-11-23, under D12)

From D12 on, I (Claude) adjudicate and accept each batch; the owner no longer reviews each
batch. This changes what "double-annotated" means for these batches: the two annotators are
the reference author (Claude) and the second model, and the adjudicator is the reference author
too, not an independent person. The owner can audit any decision below; the batch review files
(`dg-p0/d3/batches/*.md`) hold both queries and every persona's answer.

Rules I applied, all taken from the owner's earlier rulings:
- Same values with a different label for the same thing (an id for a name, a date for a month
  number) is accepted as an alternative (D9, D10).
- A schema-only annotator cannot see that a named value is absent; with an evidence query
  returning 0, the question stays "refuse" (D11).
- An ambiguous question the annotator simply answers with a reasonable default is replaced
  (D12). I added one rule of my own: a "which X" ambiguous question whose readings name the
  same X for every persona is also replaced, since a direct answer would then be right.
- A disagreement caused by my own wording is fixed in the wording and the annotator re-asked.
- A question whose answer is 0 for every persona, or 0 for one persona, is replaced before
  running, as with S-A-021.

- skills-01 (K-A-001 to K-A-025): 24 of 25 agree. Before running, K-A-024 ("which employee holds the most certifications") was reworded to a count, since many employees tie at 2. K-A-008: same counts, the annotator labels cycles by id rather than name; accepted with the id form as an alternative (rule from D9 and D10).
- skills-02 (K-A-026 to K-A-050): 24 of 25 agree. Before running, K-A-030 ("certification held by the most employees") became a per-certification count, since two EMEA certifications tie at 7. K-A-047 first read "already left by the date of the assessment"; the annotator counted same-day assessments and differed by 2 to 3, so the wording was mine to fix: now "strictly later than their leaving date", and the re-asked annotator agrees. K-A-038 ("which skill has the largest total gap"): the annotator names the same skill (SQL) without the total; the question asks only which skill, so the name alone is accepted as an alternative.
- Seed quirk found by K-A-047: 133 assessments are dated after the employee left. It makes no answer wrong; the question keeps it as a legitimate data-quality check.
- skills-03 (K-A-051 to K-A-075): 25 of 25 agree. Before running, K-A-075 ("current employees whose manager has left") was replaced because it returned 0 for every persona; now "line managers with more than 5 current direct reports" (4, 4, 12).
- skills-04 (K-A-076 to K-A-100): 25 of 25 agree. Before running, K-A-080 ("hired and left within 2025") was replaced because it returned 0 for the APAC analyst; now "employees who left during 2024" (3, 1, 6). K-A-083's wording was tidied.
- skills-05 (K-U-001 to K-U-025, unanswerable): 21 of 25 agree. K-U-018 to K-U-021 (Rust, a Marketing department, CISSP, Jane Doe): the annotator says answer or clarify because it sees the schema, not the values; each evidence query returns 0. Kept as "refuse", following the owner's ruling on the same case in D11. The Director question agrees, because the schema's CHECK constraint lists the job titles.
- skills-06 (K-U-026 to K-U-030, K-M-001 to K-M-023 less three): first run 21 of 25. K-U-029 (Azure Fundamentals) kept as "refuse" (D11). K-M-004 ("How many people have left?"), K-M-006 ("How many certifications do we have?") and K-M-017 ("assessments per employee"): the annotator answered with a reasonable default, the case the owner resolved by replacement for S-M-011/014/017, so replaced by K-M-021 to K-M-023. Two of the first replacements ("Which skill category are we best at?", "Which cycle had the best results?") were themselves replaced before acceptance: both readings named the same winner for every persona, so a direct answer would have been right. Final: K-M-021 "What is our biggest skill weakness?" (lowest average vs largest total shortfall: different skill for every persona), K-M-022 "How experienced is our workforce?" (years vs level), K-M-023 "Which is our top department?" (headcount vs average score: different department for every persona). 24 of 25 agree.

Totals: 300 questions in `questions.jsonl` (150 sales, 150 skills), 1,018 checks pass.
