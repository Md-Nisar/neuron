# Neuron Data Gateway backlog (structured data questions)

Status: **Draft**, 2026-11-22. Derived from [ADR 0016](../decisions/0016-structured-data-gateway.md),
the [structured data handoff](../research/data-analytics/proposals/STRUCTURED_DATA_DECISION_AND_HANDOFF.md)
(part C, task list C3) and the
[reconciliation](../research/data-analytics/proposals/STRUCTURED_DATA_RECONCILIATION.md) (section 5).
No GitHub issues have been created from it yet.

## Conventions

- IDs follow the RAG backlog's rules: epic `DG-Enn`, story `DG-nn.mm`, never reused or renumbered.
  Issue titles start with the ID in brackets, for example `[DG-00.01] Seed the D3 mart`.
- Labels: `story`, `epic`, `data-gateway`, `phase:0`.

## Epics

| Epic | Phase | Content | May start |
| --- | --- | --- | --- |
| **DG-E00 Proof** | P0 | Datasets, arms, spikes S1 to S4, decision record. No product code. | Now |
| DG-E01 Gateway MVP | P1 | Contract 1.1, Postgres executor, validator, baseline engine, verified queries, native tools, identity assertion, audit, evaluation suite (handoff tasks P1.1 to P1.14 with reconciliation amendments) | When the three gates in ADR 0016's status hold |
| DG-E02 Trust | P2 | `query_metric`, data citations with the numeric check, explanation card, combined answers | After DG-E01 |
| DG-E03 Reach | P3 | Auto Ontology adapter, Toolbox source adapter, second source type | Each on its own trigger |

Only DG-E00 is broken into stories below. The later epics get stories when their gates hold.

## DG-E00 Proof

Rules for every story:

- The work happens on a spike branch that is never merged to `main`.
- Results, commands, model names, commits and hardware are recorded in
  `docs/releases/data-gateway-p0/`, and only that record is merged.
- The default engine model is Neuron's configured development model; for a stronger second
  model, record the provider.
- Under decision 8 of ADR 0016, arms send the model only the schema and certified terms. Auto
  Ontology's own egress is recorded in DG-00.04.

Total estimate: 3.5 to 4.5 engineer-weeks, against the handoff's single week, because D3 grows
to 150 questions with double annotation.

### DG-00.01 Seed the D3 mart

- **Epic:** DG-E00 · **Phase:** 0 · **Priority:** P0 · **Estimate:** 1.5 w
- **Depends on:** none

**Story.** As an engineer, I want a Postgres test mart with permissions and a trusted question set, so that every arm is scored on Neuron's own data.

**Requirements**

- PostgreSQL 16 mart with two data roles and row-level security, hardened as ADR 0016 decision 5 requires:
  - `set_config` revoked from PUBLIC;
  - row-level security forced and failing closed;
  - claims set only by a `SECURITY DEFINER` function.
- At least 100 answerable, 30 unanswerable and 20 ambiguous questions, each with reference SQL and expected results per role.
- 30 adversarial cases:
  - instructions planted in rows and column comments;
  - cross-role probes;
  - write attempts.

  Start from the `nl2data-ref` attack corpus.
- Reference answers double-annotated; disagreements adjudicated and logged.

**Acceptance criteria**

- Given the mart files, when one command loads them, then every reference query returns its expected result under each role.
- Given the double annotation, when agreement is computed, then it is recorded, and every disagreement has an adjudicated answer.
- Given a role without access to a row, when any reference query runs as that role, then the row is absent, and with no claims set no rows return.

**Technical tasks**

- [ ] Schema, seed data and hardening SQL (adapt `nl2data-ref/sql/001_hardened_model_b.sql`).
- [ ] Question set with reference SQL and per-role expected results.
- [ ] Adversarial cases.
- [ ] Second annotator pass and adjudication log.

### DG-00.02 Hand-write the Ossie models for D3 and D1

- **Epic:** DG-E00 · **Phase:** 0 · **Priority:** P0 · **Estimate:** 0.5 w
- **Depends on:** DG-00.01

**Story.** As an engineer, I want a certified semantic model for each dataset, so that arm B and the round-trip test have input.

**Requirements**

- Apache Ossie YAML for D3 and for Wide World Importers (D1), each authored in at most four hours.
- Pin the Ossie spec version the files validate against.

**Acceptance criteria**

- Given each model, when it is validated against the pinned Ossie schema, then it passes.
- Given the authoring log, when the record is written, then hours per model are listed.

**Technical tasks**

- [ ] D3 model.
- [ ] D1 model.
- [ ] Validation script and authoring log.

### DG-00.03 Prototype arms C and B with deterministic scoring

- **Epic:** DG-E00 · **Phase:** 0 · **Priority:** P0 · **Estimate:** 1 w
- **Depends on:** DG-00.01, DG-00.02

**Story.** As an engineer, I want the schema-only and baseline arms as a script, so that accuracy is measured the same way for every engine.

**Requirements**

- Arm C: schema only. Arm B: baseline engine with the D3 or D1 Ossie model.
- Every generated statement passes the allowlist guard (`nl2data-ref/guard.py`) before it runs on the mart, read-only, under the question's role.
- Scoring:
  - executed results are compared with `nl2data-ref`'s comparator; there is no model judge;
  - refusal and clarification are scored on the unanswerable and ambiguous sets;
  - Wilson 95% intervals are reported beside every rate.

**Acceptance criteria**

- Given a run, when it finishes, then it reports for each arm and model:
  - execution accuracy;
  - wrong answers given without refusal or clarification;
  - correct refusals;
  - p95 latency;
  - model calls.
- Given the same inputs and model settings, when the script runs twice, then the scoring of identical outputs is identical.
- Given a statement the guard refuses, when it is scored, then it counts as wrong and is never executed.

**Technical tasks**

- [ ] Arm runner and engine interface (question, source, semantic context in; SQL or refusal code out).
- [ ] Baseline engine prompt and Ossie context builder.
- [ ] Scoring with the comparator and Wilson intervals.

### DG-00.04 Stand up NVIDIA Auto Ontology at a pinned commit (spike S1)

- **Epic:** DG-E00 · **Phase:** 0 · **Priority:** P1 · **Estimate:** 0.5 w
- **Depends on:** DG-00.01

**Story.** As an engineer, I want Auto Ontology running reproducibly against the mart, so that arms A1 and A2 can be measured.

**Requirements**

- Pin an upstream commit at version 1.3.0 or later.
- Run it on a non-NVIDIA OpenAI-compatible endpoint if one is available, and record the result either way.
- Call `search_terms` and `describe_table` with a service credential.
- Re-check its Postgres connector at the pinned commit: is there a read-only transaction, and does it use `set_config`? Give it its own read-only login on the mart.
- Record what it sends to external services.

**Acceptance criteria**

- Given the written steps, when another engineer follows them, then Auto Ontology answers a D3 question end to end.
- Given the mart's write-protected login, when Auto Ontology is asked to change data, then nothing changes, and the attempt is recorded.

**Technical tasks**

- [ ] Compose file and steps at the pinned commit.
- [ ] Connector and egress review notes.
- [ ] Generated ontology (A1), then at most four hours of certification (A2).

### DG-00.05 Run all arms and the Ossie round trip (spikes S2 and S4)

- **Epic:** DG-E00 · **Phase:** 0 · **Priority:** P0 · **Estimate:** 0.5 w
- **Depends on:** DG-00.03, DG-00.04

**Story.** As the owner, I want one comparison table, so that the engine decision rests on measurements.

**Requirements**

- Arms C, B, A1 and A2 on D1, D2 (BIRD Mini-Dev) and D3, with the same model in every arm.
- Report D2 separately as indicative, because of its label noise.
- Ossie round trip: export, import and re-export between the hand-written model and Auto Ontology.

**Acceptance criteria**

- Given the runs, when the table is written, then every arm, dataset and model has the DG-00.03 metrics with intervals.
- Given the round trip, when it finishes, then every metric and dimension is either kept or listed as lost.

**Technical tasks**

- [ ] Runs on D1, D2, D3.
- [ ] Round-trip test.
- [ ] Results table.

### DG-00.06 Safety prototype (spike S3)

- **Epic:** DG-E00 · **Phase:** 0 · **Priority:** P0 · **Estimate:** 0.5 w
- **Depends on:** DG-00.01, DG-00.03

**Story.** As the owner, I want the security gates shown at zero, so that no engine can ship on accuracy alone.

**Requirements**

- Run the 30 adversarial cases through a gateway prototype (guard, read-only role, claims).
- Repeat the guard-bypassed database tests from `nl2data-ref` against the mart.

**Acceptance criteria**

- Given the adversarial cases, when they run, then zero mutating statements execute, zero rows from another role's scope return, and zero planted instructions are followed. Each case is listed with its outcome.
- Given the guard is bypassed, when the database tests run on the mart, then every one passes.

**Technical tasks**

- [ ] Prototype harness.
- [ ] Database tests pointed at the mart.
- [ ] Case-by-case log.

### DG-00.07 Decision record

- **Epic:** DG-E00 · **Phase:** 0 · **Priority:** P0 · **Estimate:** 0.25 w
- **Depends on:** DG-00.05, DG-00.06

**Story.** As the owner, I want a one-page go or no-go, so that ADR 0016's second gate is answered.

**Requirements**

- Record, for each arm, whether each B8 threshold is met:
  - execution accuracy on D3 answerable questions of at least 85%;
  - wrong answers without refusal or clarification of at most 5%;
  - correct refusal of at least 90%;
  - p95 latency of at most 45 s;
  - all S3 counts zero.
- Give the verdict for the gateway (P1) and for the Auto Ontology adapter, using the B1 conditions of the handoff.
- Apply the kill criterion: if the baseline is below 60% on D3 with the best available model, record that the feature is not ready on any engine.

**Acceptance criteria**

- Given the record, when the owner reads it, then every threshold and every arm has a met or not-met value with its sample size and interval.
- Given the verdict, when ADR 0016 is updated, then its status names the outcome and the date.

**Technical tasks**

- [ ] `docs/releases/data-gateway-p0/decision-record.md`.
- [ ] ADR 0016 status update.
