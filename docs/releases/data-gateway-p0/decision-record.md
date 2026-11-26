# Data Gateway P0: decision record (DG-00.07)

| | |
| --- | --- |
| Date | 2026-11-24 |
| Answers | ADR 0016, gate 2: "P0's decision record shows the B8 thresholds met on at least one engine" |
| Evidence | [`design-spike-log.md`](design-spike-log.md), sections 6 to 9; branch `spike/data-gateway-p0` at `8a264d8` (`dg-p0/arms/runs/results.md`, `dg-p0/safety/`, `dg-p0/roundtrip/out/`) |
| Model | `nvidia/nemotron-3-ultra-550b-a55b` in every arm. No stronger model and no non-NVIDIA endpoint exist here, so it is also "the best available model" |
| Status | **Final.** Written by Claude under the owner's delegation (D19), reviewed and re-verified, then accepted by the owner on 2026-11-24 (D23). **Gate 2 accepted by owner decision on 2026-11-26 (D31); see the last section.** The verdicts below are the measurements as recorded and are not rewritten |

## Verdict

- **Gateway (P1): NO-GO for now. Gate 2 is not met.** No engine meets every release threshold. The
  closest, arm B, misses accuracy (71.0% against 85%) and correct refusal (80.0% against 90%).
- **Kill criterion: not triggered.** The baseline (arm B) scores 71.0% on D3, above 60%. The feature is
  not declared unready on every engine.
- **Auto Ontology adapter: stays CONDITIONAL GO, not a full GO.** It clears the S2 accuracy uplift and
  triggers no NO-GO condition, but two of the four full-GO conditions fail, and on its own it fails
  three release thresholds.

## Release thresholds on D3 (B8), per arm

Wilson 95% intervals. Accuracy is per question: a question counts only if every persona got it right
(units in brackets). The p95 was measured with 4 to 6 questions in flight.

| Threshold | C (schema) | B (Ossie + columns) | A1 (Auto Ontology) | A2 (certified) |
| --- | --- | --- | --- | --- |
| Execution accuracy, answerable, at least 85% (n = 200) | 73.0% [66.5, 78.7] **not met** (units 78.7%) | 71.0% [64.4, 76.8] **not met** (84.0%) | 79.0% [72.8, 84.1] **not met** (86.5%) | 89.5% [84.5, 93.0] **met** (94.0%) |
| Wrong answers without refusal or clarification, at most 5% (n = 900 units) | 17.7% [15.3, 20.3] **not met** | 3.7% [2.6, 5.1] **met** | 24.9% [22.2, 27.8] **not met** | 16.6% [14.3, 19.1] **not met** |
| Correct refusal, unanswerable, at least 90% (n = 60) | 65.0% [52.4, 75.8] **not met** | 80.0% [68.2, 88.2] **not met** | 50.0% [37.7, 62.3] **not met** | 46.7% [34.6, 59.1] **not met** |
| p95 latency, at most 45 s (n = 934 requests, one question asked by one persona) | 33.7 s **met** | 24.8 s **met** | 79.3 s **not met** | 69.9 s **not met** |
| S3 counts all zero (n = 60 cases, 188 runs) | 0, 0, 0 **met** | 0, 0, 0 **met** | 0, 0, 0 **met** | 0, 0, 0 **met** |
| **All met** | no | no | no | no |

S3 counts are mutating statements executed, rows from another role's scope, and planted
instructions followed. They hold for every arm because the guard and the database enforce them,
not the engine. With the guard bypassed, the 13 database tests ported from `nl2data-ref` pass.

## Spikes

| Spike | Pass condition | Result |
| --- | --- | --- |
| S1 | Runs from a pinned commit on a non-NVIDIA endpoint; `search_terms`, `describe_table` callable without interactive sign-in | **Partly.** Runs from written steps at `7dac5ff7`. No non-NVIDIA endpoint was available to test. The tools' REST routes work with a viewer token, but MCP itself needs per-user OAuth (F7) |
| S2 | A2 beats C by at least 10 points on D1 and D3, and beats B by at least 5 on D3 | **Met.** D3: A2 89.5% against C 73.0% (+16.5) and B 71.0% (+18.5). D1: 41.2% against 20.6% (+20.6), n = 34, wide intervals |
| S3 | Zero, zero, zero | **Met** (above; DG-00.06) |
| S4 | Export, import and re-export keep every metric and dimension | **Not met.** All 77 dimensions kept; 9 of 12 metrics lost (every dataset-scoped one); all certification lost (F11, F12) |

## Auto Ontology against the handoff's B1 conditions

| Condition | Status |
| --- | --- |
| Full GO: a tagged release, MCP package on a registry | **No.** No tags; 1.3.0 exists only in `pyproject.toml` |
| Full GO: beats the baseline engine by at least 5 points | **Yes** on D3 (A2 +18.5 over B) |
| Full GO: SQL without executing, or execution under a caller identity | **No.** It runs its SQL under its own login. Here the gateway re-ran it under the persona |
| Full GO: runs on a non-NVIDIA endpoint with no NVIDIA key | **Not tested.** No such endpoint exists here |
| NO-GO: fails the uplift over schema-only on two datasets | **No.** The 10-point uplift holds on D3 (+16.5) and D1 (+20.6). D2 (indicative) falls just short at +9.3, so one dataset fails, not two |
| NO-GO: licence change or required hosted service | **No** |
| NO-GO: no commits for 60 days, or two breaking changes in a quarter without a release | **No.** Active (31 commits after 1.3.0) |
| NO-GO: the tools need the full stack, and the stack fails a security review | **Open.** It needs four services. Findings against the stack: F6, F8, F9, F14 |

## How firm the verdicts are

Checked in the final review (2026-11-24): the results table regenerated from the saved outputs is
byte-identical to `results.md`; the scorer self-test passes; the 13 guard-bypassed database tests pass.

- **Gate 2 (not met) holds under any reading.** The correct-refusal threshold alone decides it: the
  upper bound of every arm's interval is below 90% (B 88.2%, C 75.8%, A1 62.3%, A2 59.1%). Reading
  accuracy per unit instead of per question would change A1's accuracy row, not the verdict.
- **The kill criterion (not triggered) holds.** Arm B's lower bound is 64.4%, above 60%.
- **S2 on D3 is firm** (A2's and B's intervals do not overlap). **S2 on D1 rests on point estimates**:
  with 34 questions, A2's and C's intervals overlap. The conditional GO does not depend on D1 alone.
- **Open, not closed by P0:** the security review of Auto Ontology's four-service stack (the last
  NO-GO condition), and S1's non-NVIDIA endpoint. Both must close before any adapter work.

## What the measurements point to (not a decision)

- The accuracy gap and the safety gap sit in different engines. Auto Ontology writes the most
  accurate SQL (95.2% when it writes SQL), but it never asks back (F13) and refuses half as often as
  it should. Arm B refuses and clarifies best but writes less accurate SQL. No engine is good at both.
- The refusal threshold (90%) is missed by every arm, so it is the binding constraint for any engine.
- Auto Ontology's latency (several model calls per question) misses 45 s with this model.
- Choosing what to do next is the owner's backlog decision (D2). Nothing here designs it.

## Owner acceptance of gate 2 (2026-11-26, D31)

The owner accepted gate 2 on the live T4 result, by owner decision rather than by every threshold
being met: "mark 82.5 as accepted as it tested against free tier models, frontier model may reach".

| What is accepted | Value | Threshold |
| --- | --- | --- |
| T4 (B triage, value check v4, A2), fresh set, live, accuracy per question | 33/40 = 82.5% [68.0, 91.2] | 85% |
| Same run, correct refusal | 36/40 = 90.0% [77.0, 96.0] | 90%, met |
| Same run, wrong answers | 0.4% [0.1, 2.3] | 5%, met |
| T4 on all of D3, offline (accuracy, refusal, wrong answers) | 87.0%, 91.7%, 4.0% | all met |
| Safety (S3) | 0 in every count | met |
| p95 latency | Not measurable on the free tier (D28) | 45 s, set aside |

The reason: every run used one free-tier model, with rate limits that caused 3 of the 7 fresh misses
(canned or unparsed replies). The other 4 (B asking to clarify, one stored-form mismatch) are not
caused by the tier. The 85% threshold lies inside the accuracy interval, so the shortfall is not
statistically clear either way.

Conditions that come with the acceptance:

- **The engine accepted is T4, not any single arm.** The verdict on arms C, B, A1 and A2 above stands.
- **Before the gateway's first release**, accuracy and p95 latency are re-measured on the
  deployment's model, on a question set written before the run. That run must meet B8 without an
  exception.
- **Gates 1 and 3 are unchanged.** P1 still waits for the hosted deployment and a named first
  database and user. The Auto Ontology adapter stays a conditional GO until its security review.
