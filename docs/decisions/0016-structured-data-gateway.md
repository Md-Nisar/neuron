# ADR 0016: Structured data questions through a Data Gateway

## Status

Accepted (2026-11-22, owner approval). Not implemented. The owner accepted all nine
recommendations in
[`STRUCTURED_DATA_RECONCILIATION.md`](../research/data-analytics/proposals/STRUCTURED_DATA_RECONCILIATION.md),
section 6. No production environment exists, so only the proof (phase P0, stories DG-E00 in
[`NEURON_DATA_GATEWAY_BACKLOG.md`](../product/NEURON_DATA_GATEWAY_BACKLOG.md)) may start now. It
writes no product code.

The gateway itself (phase P1) may start only when all three hold:

1. the hosted deployment (roadmap item F0.2) has run;
2. P0's decision record in `docs/releases/` shows the B8 thresholds met on at least one engine;
3. a first database and user are named in this file.

P0 outcome (2026-11-24, final): the proof ran, and gate 2 is **not met**. No engine met every B8
release threshold. The kill criterion was not triggered: the baseline engine scored 71.0% on D3,
above 60%. Auto Ontology remains a conditional GO as an engine behind the gateway. See
[`docs/releases/data-gateway-p0/decision-record.md`](../releases/data-gateway-p0/decision-record.md).

Gate 2 accepted (2026-11-26, owner decision, D31): the live T4 result, 82.5% accuracy on a fresh
set against the 85% threshold, measured on a free-tier model only, with refusal and wrong answers
met. Before the gateway's first release, B8 is re-measured on the deployment's model with no
exception. Gates 1 and 3 still hold P1. See the decision record's last section.

Amended (2026-11-25, owner approval, D30): decisions 3, 5, 7 and 8, the product requirement and the
consequences were corrected from the P0 findings. The corrections and their evidence are in
[`docs/releases/data-gateway-p0/adr-0016-corrections-draft.md`](../releases/data-gateway-p0/adr-0016-corrections-draft.md).

This ADR replaces draft ADRs 0016 and 0018 in
[`STRUCTURED_DATA_DECISION_AND_HANDOFF.md`](../research/data-analytics/proposals/STRUCTURED_DATA_DECISION_AND_HANDOFF.md)
(part C). Draft ADR 0017 (first-party MCP servers) is not adopted: Neuron reaches the gateway
through native tools (decision 2). Number 0015 stays reserved for the product-direction ADR.

## Context

Users want answers from databases as well as documents. ADR 0001 and `CLAUDE.md` forbid new
retrieval and services without a product requirement and an ADR. No engine examined has
independent accuracy evidence; public benchmarks carry heavy label noise. v1.4.0 already runs
model-written SQL in one place: a SQLite sandbox over the user's own uploaded tables (ADR 0014,
amendment "tables").

Constraints checked at `4f64d1b`:

- The MCP client reaches only public addresses in staging and production (`security/egress.py`).
- Once a run is tainted, every `read` MCP tool needs approval (`tools/registry.py`,
  `gated_after_taint`); native `builtin` read tools do not.
- The runtime context carries the verified principal and its scopes, not groups or organisation
  (`security/authorization.py`).

## Product requirement

A signed-in user asks a plain-language question about a database their organisation connected.
They receive an answer computed by a read-only query that ran with their own data permissions,
with the SQL, the business terms and a trust label shown. Otherwise they receive an explicit
statement that the data does not hold the answer. A question about a named value that exists only
outside the caller's data permissions (for example a customer in another region) is refused with
that reason, not answered with zero. The feature is experimental until the P0
release thresholds hold on Neuron's own question set.

## Decision

1. **Gateway process.** A separate process, `neuron-data-gateway`, in this repository,
   implements one Neuron-owned contract. That is the contract in decision C2 of the structured
   data handoff, as version 1.1 with the reconciliation's amendments A1 and A5. Neuron core never
   imports an engine or a database driver for it.
2. **Native tools, not MCP.** Neuron reaches the gateway through native `read` tools with
   `taints_run=True`, built with the `add-tool` checklist.
   - They call one configured address, `APP_DATA_GATEWAY_URL`. In staging and production it is
     the only private address the API process may call, and the question text goes nowhere else.
   - Each call carries a service credential and a short-lived identity assertion minted from the
     runtime `AuthorizationContext`, with the claims and safeguards in C2 and B7: ES256,
     60-second lifetime, audience-bound, single use, rotation through JWKS.
   - The user's bearer token is never forwarded.
3. **SQL rule.** Model-written SQL never reaches a connected database directly. Only the gateway
   executes, under these conditions:
   - one validated `SELECT`, in a read-only transaction;
   - under a database role mapped from the caller's scopes in gateway configuration, with no
     default role;
   - with a statement timeout the executor sets inside the transaction (`SET LOCAL`), immediately
     before the statement, and a row cap. A role's default timeout is not relied on.

   The uploaded-tables sandbox is unchanged. The rule "never free-form SQL from the model" in
   `DOMAIN_AGNOSTIC_INTEGRATION_ARCHITECTURE.md` is restated accordingly.
4. **Validation.** The validator parses with `sqlglot` (exact pin) and uses a function allowlist.
   It rejects:
   - more than one statement;
   - locking clauses and `INTO`;
   - data-modifying and recursive CTEs;
   - relations outside the source's allow-listed schemas.

   It emits SQL without comments. Adding a SQL dialect requires a reviewed allowlist and a
   failing-input test suite for that dialect.
5. **Database hardening.** Required in Neuron's test mart and reference deployment, and
   recommended to customers:
   - row-level security is forced and fails closed;
   - policies are keyed on the database role (`current_user`), through a mapping table only an
     administrator can write. No policy reads a session setting;
   - each data role has its own login, which is a member of that role only, so neither `SET
     ROLE` nor `RESET ROLE` can widen what a session sees.

   Per-user policies (keyed on the subject) are not supported. They need claims the session
   cannot forge, and a new decision.
6. **Trust label.** Every answer carries `trust`:
   - `certified` for verified queries and `query_metric`;
   - `exploratory` for SQL generated by an engine.

   Verified queries ship in the first gateway release, alongside `ask`; `query_metric` follows.
7. **Semantic content and engines.**
   - Semantic content is Apache Ossie YAML under version control, and only certified terms are
     served. Ossie core has no notion of certification, so certified status is recorded in a
     `neuron` entry under `nonportable_extensions`. Neuron's files are the only source of
     certification: an engine's own flags and exports are never read for it.
   - Engines implement one interface. They take a question, a source and semantic context, and
     return either a SQL proposal with its references or a refusal code. They never execute
     against the governed source and never return prose.
   - The built-in `baseline` engine ships first.
   - NVIDIA Auto Ontology is an optional adapter, pinned to a commit, and only after spike S2
     passes. It is loaded one way, from Neuron's Ossie files; Neuron never relies on exporting a
     model back out of it.
   - MCP Toolbox is a source adapter only after a trigger in B3 fires.
   - No engine is required by the contract, the evaluation or the default configuration.
8. **Model and egress.** Engines use Neuron's configured model. By default an engine sends the
   model only the schema and certified terms; sample values and rows need the source's policy.
   An engine that sends sample values while compiling (Auto Ontology, F9) may be used only on
   sources whose policy allows it, or with every column the policy excludes tagged so the engine
   skips it. Literal values are resolved by live queries under the caller's role, and there is no
   shared value index.
9. **Answers.** A runtime check confirms that every number in a final answer appears in, or is
   computed by code from, a gateway result.
10. **Scope.**
    - The first source type is PostgreSQL. The feature is off by default.
    - Public claims say "measured accuracy on your own questions", never "comparable to Cortex
      Analyst".
    - The "Deliberately not built" list in B5 of the structured data handoff is part of this
      decision.

## Consequences

- A second deployable to secure and operate.
- Each data scope is a database role with its own login, so the gateway holds one credential per
  scope, and roles grow with scopes. Per-user row policies wait for a decision on unforgeable
  claims.
- A package boundary, `data_gateway/`, that imports nothing from `api/`, `services/`, `graphs/`,
  `agents/`, `models/` or `knowledge/`, enforced by a boundaries test.
- A new pinned dependency, `sqlglot`, and two new settings: `APP_DATA_GATEWAY_URL` and the
  assertion signing key.
- When P1 starts, its first task updates `CLAUDE.md`, `AGENTS.md`, `ARCHITECTURE.md` and
  `SECURITY.md` with these boundaries.
- The gateway is usable only by Neuron. Serving other MCP clients needs an MCP facade over the
  same contract and a new ADR.

## Alternatives rejected

- Neuron connects straight to an engine's MCP server: shared database credential, OAuth mismatch,
  provider names in scopes.
- MCP Toolbox as the gateway: no policy hooks, token passthrough.
- An in-process data module: database credentials in the agent process.
- A first-party MCP server class (draft ADR 0017): it changes ADR 0009 for every MCP server and
  needs an exemption from the after-taint approval.
- Building a semantic modelling language.
- A `run_sql` tool for the agent.

Details: decision B4 of the structured data handoff, and sections 3.3 and 3.6 of the
reconciliation.

## Evidence

The structured data handoff (2026-11-12), the AI-to-database architecture v2.0 and its tested
reference code
([`nl2data-ref`](../research/data-analytics/reference-code/nl2data-ref/): 27 attacks refused by
the guard, 12 Postgres 16 tests holding with the guard bypassed), and the reconciliation
(2026-11-22).
