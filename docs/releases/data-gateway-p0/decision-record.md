# Data Gateway P0: decision record (DG-00.07)

| | |
| --- | --- |
| Date | 2026-11-24 |
| Answers | ADR 0016, gate 2: "P0's decision record shows the B8 thresholds met on at least one engine" |
| Evidence | [`design-spike-log.md`](design-spike-log.md), sections 6 to 9; branch `spike/data-gateway-p0` at `8a264d8` (`dg-p0/arms/runs/results.md`, `dg-p0/safety/`, `dg-p0/roundtrip/out/`) |
| Model | `nvidia/nemotron-3-ultra-550b-a55b` in every arm. No stronger model and no non-NVIDIA endpoint exist here, so it is also "the best available model" |
| Status | Written by Claude under the owner's delegation (D19); the owner decides whether it stands |

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
| p95 latency, at most 45 s (n = 934 questions) | 33.7 s **met** | 24.8 s **met** | 79.3 s **not met** | 69.9 s **not met** |
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
| NO-GO: fails the uplift over schema-only on two datasets | **No.** Uplift on D3 (+16.5), D1 (+20.6) and D2 (+9.3, indicative) |
| NO-GO: licence change or required hosted service | **No** |
| NO-GO: no commits for 60 days, or two breaking changes in a quarter without a release | **No.** Active (31 commits after 1.3.0) |
| NO-GO: the tools need the full stack, and the stack fails a security review | **Open.** It needs four services. Findings against the stack: F6, F8, F9, F14 |

## What the measurements point to (not a decision)

- The accuracy gap and the safety gap sit in different engines. Auto Ontology writes the most
  accurate SQL (95.2% when it writes SQL), but it never asks back (F13) and refuses half as often as
  it should. Arm B refuses and clarifies best but writes less accurate SQL. No engine is good at both.
- The refusal threshold (90%) is missed by every arm, so it is the binding constraint for any engine.
- Auto Ontology's latency (several model calls per question) misses 45 s with this model.
- Choosing what to do next is the owner's backlog decision (D2). Nothing here designs it.
