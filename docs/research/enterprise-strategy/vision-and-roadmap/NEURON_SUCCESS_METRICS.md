# Neuron Success Metrics

| | |
| --- | --- |
| Date | 2026-11-10 |
| Package | Document 13 of 14 |
| Evidence | Neuron has no production data. The only measured figure in the repository is a local run of 8 simulated users with a fake model. **This document therefore sets no numeric performance targets.** It defines what to measure, how to obtain a baseline and how to derive a target from it. |

## 1. How targets are set

Three kinds of metric, each with its own method.

| Kind | Examples | Target method |
| --- | --- | --- |
| **Invariant** | Isolation, approval integrity, credential non-disclosure, exactly-once writes | The target is fixed in advance: zero violations, or 100% compliance. Measured by tests that must pass. No baseline needed. |
| **Engineering** | Latency, availability, success rates, cost per run | Baseline from the first hosted measurement (roadmap F0.2) and from each use case's first month. Target is a stated improvement on the baseline, or a budget derived from a user need (for example "an interactive answer starts within the time a user will wait", decided with users). |
| **Outcome** | Time saved, manual steps removed, deflection | Baseline from the design partner's process *before* Neuron, measured by them. Target agreed with them. Not claimed without a partner. |

Rules:

1. A number is published only with its measurement conditions: model, data size, concurrency, environment, date.
2. Confidence intervals accompany rates from samples. The evaluation harness already computes Wilson intervals.
3. A metric with no baseline is reported as "baseline pending", never estimated.
4. Every target names the decision it informs. A metric that changes no decision is dropped.

## 2. Integration metrics

| Metric | Definition | Source | Type | Baseline and target method |
| --- | --- | --- | --- | --- |
| Time to connect an application | Person-hours from registering an application to its first published capability set passing evaluation | Recorded per onboarding in the registry | Engineering | Baseline: use case 1. Target: each later onboarding is lower; the cold onboarding test sets the public figure. |
| Draft acceptance rate | Share of model-drafted capability descriptions and pack entries activated without edits | Review records | Engineering | Baseline: first onboarding with drafting (F3.2). Informs whether drafting is worth its cost. |
| Core changes per onboarding | Changes under `src/` required by a specific application | Pull request labels | Invariant after use case 2 | Target: zero. Any non-zero is a core defect. |
| Connector reliability | Share of capability calls that succeed, excluding denials by policy or by the application | Executor metrics | Engineering | Baseline per application in its first month. Target set per application, since it depends on the application's own reliability. |
| Integration coverage | Published capabilities divided by the operations the application owner wants available | Catalogue | Engineering | Tracked, no target. A low value with satisfied users is fine. |
| Successful authentication rate | Share of credential requests to the broker that yield a valid credential without user action | Broker metrics | Engineering | Baseline in use case 1. A falling rate signals refresh or consent problems. |
| Reconnect rate | Users asked to reconnect an application, per user per month | Broker metrics | Engineering | Baseline; lower is better. |
| API execution success | Share of calls returning a success status, by application and capability | Executor metrics | Engineering | As connector reliability, split by error class (application error, timeout, rate limit). |
| Drift incidents | Capabilities suspended because the specification changed | Registry | Engineering | Tracked. Time to re-review is the number to reduce. |

## 3. Agent metrics

| Metric | Definition | Source | Type | Baseline and target method |
| --- | --- | --- | --- | --- |
| Task completion rate | Share of evaluation cases where the end state matches the expected one | Evaluation harness, per agent and application | Engineering | Baseline at publish. Target: no regression beyond the confidence interval on any change (the existing baseline-comparison method). |
| Correct action rate | Share of cases where the capabilities called, their order and their key arguments match the expected trajectory | Trajectory evaluation (F3.5) | Engineering | Same method. |
| Wrong-action rate | Mutating calls proposed that a reviewer or approver rejected as incorrect | Approval records | Engineering | Baseline from the first hundred approvals per capability. This is the number that decides whether any confirmation could ever be relaxed. |
| Human intervention rate | Runs that needed a clarification, correction or manual takeover, divided by all runs | Run events | Engineering | Baseline per use case. Interpreted with care: interventions that are required approvals are counted separately. |
| Workflow completion time | Trigger to final step, split into agent time, waiting-for-approval time and application time | Run events | Engineering | Baseline in use case 3. Approval waiting time usually dominates and is the partner's process, not Neuron's speed. |
| Recovery success | Share of injected failures (worker kill, application error, timeout) after which the run completes or compensates correctly | Resilience tests | Invariant for duplicates (zero), Engineering for completion | Duplicate side effects: zero. Completion: baseline from the first resilience run. |
| Evaluation performance | Scores on the standing suites: quality, multi-turn, security, approvals, per-application | Existing harness | Engineering | Existing baselines in `evals/baselines`; extended per application. |
| Capability retrieval rate | Share of cases where the needed capability was in the selected set | F2.5 evaluation | Engineering | Baseline with the synthetic large catalogue. |
| Grounding | Share of factual claims backed by a valid citation or record reference | Existing citation validation plus record-reference validation | Invariant for validity (no invalid references shown), Engineering for coverage | |

## 4. Enterprise metrics

These need a real organisation using Neuron. Until then they are "baseline pending".

| Metric | Definition | Source | Notes |
| --- | --- | --- | --- |
| Connected applications | Published applications per organisation | Registry | A count, not a goal. Three well-used applications beat thirty unused. |
| Active users | Users with at least one run in a week, and in a month | Runs table | Report the weekly-to-monthly ratio as a stickiness signal. |
| Active agents | Agent definitions with runs in a month | Runs table | |
| Completed business workflows | Workflow instances reaching their final step | Run events | Split by outcome: completed, compensated, abandoned. |
| Business process time saved | (Baseline handling time minus handling time with Neuron) times volume | Design partner's own measurement plus run events | Only claimed with a measured baseline from the partner. |
| Reduction in manual operations | Manual steps per case before and after, from a process walk-through | Design partner | Count steps, not opinions. |
| Repeat use | Share of users who return in the following month | Runs table | The most honest value signal available without a survey. |
| Feedback ratings | Existing thumbs ratings per answer | `neuron_feedback` | Already collected. |

## 5. Security metrics

Most of these are invariants: the target exists before any baseline.

| Metric | Definition | Source | Target |
| --- | --- | --- | --- |
| Unauthorized action attempts blocked | Capability calls denied by policy, by cause (scope, argument rule, data-flow rule, taint, emergency stop) | Audit ledger | Count and trend. A sudden rise is an alert, not a success. |
| Application-side denials | Calls refused by the application (401, 403) | Executor | Trend. Shows the user-ceiling principle working; a rise may indicate the agent probing beyond the user's rights. |
| Approval compliance | Mutating calls executed with a valid approval of the required tier, divided by mutating calls executed | Audit ledger | 100%. Anything less is an incident. |
| Approval integrity tests | Tampered argument, expiry, replay, self-approval | Security suite | All refused, every build. |
| Tenant isolation test results | Cross-organisation and cross-user access attempts at API and SQL level | Security suite | Zero successes, every build. |
| Credential non-disclosure | Planted marker credentials found in model context, checkpoints, run events, logs or traces | Security suite | Zero, every build. |
| Audit completeness | Capability calls with exactly one action record, divided by capability calls | Reconciliation job between executor metrics and the ledger | 100%. |
| Audit chain integrity | Result of the periodic hash-chain verification | Ledger job | Pass. |
| Policy enforcement coverage | Published capabilities with at least one explicit policy rule and one evaluation case, divided by published capabilities | Catalogue | 100% at publish; enforced by the publish gate. |
| Injection resistance | Share of adversarial cases where the injected instruction changed a capability call or an answer | Adversarial evaluation set | Zero for changed mutating calls (they also face approval). Baseline and reduction for changed answers. |
| Elevated connections | Applications using delegation mode D, and capabilities exposed on them | Registry | Tracked and reviewed; lower is better. |
| Time to revoke | From IdP deactivation or administrator action to all grants revoked | Broker | Baseline, then a stated bound. |
| External findings | Open findings from the penetration test by severity | Test report | Zero high or critical open. |

## 6. Operational metrics

| Metric | Definition | Source | Baseline and target method |
| --- | --- | --- | --- |
| Latency: time to first token | Request accepted to first streamed token, interactive runs, by percentile | Existing telemetry | Baseline from F0.2 with a real model. Dominated by the model provider; report Neuron's own overhead separately. |
| Latency: Neuron overhead | Time spent outside model and application calls per run | Trace spans | Baseline; this is the part Neuron controls. |
| Latency: policy decision | Time per decision | Trace spans | Budget set so that decisions are negligible beside a model call; verify by measurement. |
| Availability | Successful readiness-backed requests over total, per month | Load balancer and API metrics | No objective until a hosted environment has run for a quarter. Then set one from observed behaviour and the partner's need. |
| Cost per run and per completed workflow | Model cost plus metered application calls, by agent and application | Extended token ledger (F5.2) | Baseline per use case. Target tied to the value of the task: a workflow should cost a small fraction of the labour it saves, with the fraction agreed with the partner. |
| Tokens per run | Input and output, by agent | Token ledger | Baseline; context management (F3.4) should reduce it at equal quality. |
| Connector failure rate | Failed calls over total, by application and error class | Executor | Baseline per application. |
| Queue processing time | Enqueue to start, by job type and percentile | Job tables | Baseline once durable runs exist. Interactive wait is the stage 2 trigger in document 8. |
| Database pool saturation | Time the pool is at its limit | Pool metrics | Any sustained saturation is a trigger to act. |
| Resource consumption | Memory and CPU per worker; storage growth per month for run events, checkpoints, audit | Platform metrics | Baseline; informs retention and partitioning. |
| Recovery time and data loss | Measured in restore exercises | Runbook records | Objectives are set after the first exercise, then tested twice a year. |
| Upgrade success | Upgrades completed from documentation without assistance | Self-hosting users' reports | Tracked. |

## 7. Product-level scorecard

A small set to review at each phase gate. Everything else is diagnostic.

| Question | Metric |
| --- | --- |
| Is onboarding fast? | Time to connect an application; core changes per onboarding |
| Does the agent do the right thing? | Correct action rate; wrong-action rate |
| Is it safe? | Approval compliance; isolation and non-disclosure tests; audit completeness |
| Does it stay up and affordable? | Neuron overhead latency; cost per completed workflow |
| Does anyone want it? | Repeat use; one design partner's measured time saved |

## 8. Baseline plan

| When | Baseline obtained |
| --- | --- |
| Phase 0 gate | Latency, overhead, concurrency and error rate with a real model in a hosted environment; restore and rollback times |
| Use case 1 | Onboarding effort; task and trajectory rates; authentication success; permission fidelity (invariant) |
| Use case 2 | Second onboarding effort; draft acceptance; grounding on shared knowledge |
| Use case 3 | Workflow time split; recovery; proposal approval rate; cost per workflow |
| First design partner | Every outcome metric in section 4 |
| Cold onboarding test | The public time-to-connect figure |

## 9. What not to measure, or not to celebrate

- **Number of connectors.** It rewards the strategy this package rejects.
- **Number of agents created.** Vendors publish such counts; they say nothing about use.
- **Autonomy rate** (actions without a human). In the first 18 months a rising value would mean controls were removed, not that the product improved.
- **Blocked attempts as a success number.** A rise is a signal to investigate.
- **Benchmarks unrelated to the use cases.**
