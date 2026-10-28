# ADR 0012: Production Candidate (v0.9.0)

## Status

Proposed (2026-10-28). Inputs: `docs/releases/v0.9.0-research.md`. The owner answered the
first four research questions on 2026-10-28:

- The system under test is the local reference stack (option A).
- The open release gates are deferred, not closed.
- An NVIDIA key exists.
- Load is measured in runs per second as a baseline, not against a fixed target.

Questions 5 to 8 are answered here as proposals and listed under "Open questions". Production
deployment stays out of scope until after v1.0.0 (owner decision, 2026-10-27).

## Context

The roadmap theme for v0.9.0 is "Production Candidate: Load/security/DR/release freeze".
Every part of that assumes a running system, but nothing has been deployed: the v0.6.0
Render pipeline has never run, and v0.7.0 and v0.8.0 were verified locally only. Three
release gates are open: #160 (v0.6.0), #253 (v0.7.0 tracker) and #293 (v0.8.0).

What exists:

- SLOs and burn-rate alerts (`OPERATIONS.md`), with the only SLO evidence coming from eval runs.
- Postgres-backed limits and run leases with two-process tests.
- Backup, restore and rollback runbooks that have never been run.
- Static security scanning: bandit, pip-audit, CodeQL and Trivy, plus security eval datasets up to v5.
- CHANGELOG-driven releases. `check-release` accepts only `vX.Y.Z` (`scripts/deploy_tools.py`, `TAG_PATTERN`).

**Product requirement.** Before v1.0.0, the project can state:

- How much load the service takes, and how it fails past that point.
- Which security risks are covered, and how.
- That a lost database can be restored, and how long that takes.
- That the public contract stops changing.

All of it must come from repeatable scripts that can later run unchanged against a hosted deployment.

## Decisions

1. **Order of work.** The streams are mostly independent:
   - (A) Gate deferral and the reference stack.
   - (B) Load: fake-latency model, scenarios, baseline.
   - (C) Security: threat model, DAST.
   - (D) DR: restore drill, rollback rehearsal.
   - (E) Release freeze and pre-release tags.
   - (F) Live evals, docs and the release gate.

   B, C and D need A.

2. **Deferred gates.** #160, #253 and #293 and their open children are re-labelled and
   commented as deferred until after v1.0.0, with each one's remaining exit criteria listed. They
   are not closed. The v0.9.0 release notes list them as known issues.

3. **Reference stack.** A compose override, `docker-compose.reference.yml`, is the system
   under test for every v0.9.0 number.
   - It runs the image built from the release commit, never `build: .` from a dirty tree. The digest is recorded.
   - There are two API replicas sharing Postgres, so limits and leases cross instances.
   - `APP_AUTH_MODE=jwt` uses the local Keycloak realm, with `APP_LIMITS_BACKEND=postgres`
     and `APP_CHECKPOINTER=postgres`.
   - Ports bind to loopback only, as the existing compose services do.
   - It runs with the production settings profile wherever the validation allows it locally. Each relaxation (for
     example Postgres TLS) is listed in the override with its reason.

   Every number the release records names the reference stack and the host it ran on. None
   is presented as production capacity.

4. **Fake model with latency.** The dev/test fake model gains:
   - `APP_FAKE_MODEL_TTFT_MS`: delay before the first token.
   - `APP_FAKE_MODEL_TOKENS_PER_SECOND`: streaming rate.
   - `APP_FAKE_MODEL_OUTPUT_TOKENS`: answer length.

   They are read in `config/` and refused when `APP_ENV` is `staging` or `production`, as
   `APP_CHECKPOINTER_SETUP_ON_STARTUP` is. Defaults keep today's instant answer, so existing tests do not change.

   Load never targets the NVIDIA API: the free tier is rate limited and is not ours to load.

5. **Load tool and scenarios.** Locust, as a dev dependency (it must pass the 90-day rule),
   in a top-level `loadtest/` directory with its own entry point (`make load`). Scenarios:
   - (a) A new thread with one streamed answer.
   - (b) A follow-up turn on an existing thread (checkpoint read and write).
   - (c) A run that pauses for approval and is approved.
   - (d) A mix of the three, weighted 60/30/10.

   Each virtual user holds a token for its own Keycloak test user, so per-user limits apply as
   in real use. The test client parses the JSON SSE events and records:
   - time to first token;
   - run duration;
   - status and error code per run.

   Locust's request statistics alone are not enough.

6. **Load baseline (owner answer).** There is no pass/fail target. For each scenario the gate
   records, on the reference stack with a fixed fake-model profile:
   - The **highest sustained runs per second** at which the availability, `ttft` and
     `run_duration` SLOs all hold over a 10-minute step.
   - The **knee**: the step where any SLO first breaks.
   - The **failure mode** one step past the knee, such as 429s from limits, 503s, timeouts, or a
     growing Postgres connection queue.

   The results are committed as `docs/releases/v0.9.0-gate/load-baseline.json`, with the
   profile, image digest and host. v1.0.0 must not regress the sustained figure by more than
   10% on the same host and profile. That check is done by rerunning `make load` and comparing
   with a small script.

7. **Threat model.** `docs/security/threat-model.md` maps every item of:
   - the OWASP Top 10 for LLM Applications 2026;
   - the OWASP Top 10 for Agentic Applications.

   Each item maps to the control in code, the test that proves it, or a known issue. It covers what v0.7.0 and v0.8.0 added:
   - memory;
   - approvals and mutating tools;
   - the browser and OIDC.

   Rows without a test become issues, not prose. The entry text of both lists is re-read from
   the OWASP site when the file is written, not from the research excerpts.

8. **DAST.** A manual-dispatch workflow starts the reference stack and authenticates as a
   Keycloak test user. It then runs ZAP's API scan against `/openapi.json` and the SSE route.
   - The action is pinned by SHA.
   - Findings at medium or above fail the run unless listed with a reason in a rules file.
   - The report is uploaded as an artifact.
   - It does not run on pull requests (time and noise). The gate needs one clean run.

9. **Restore drill.** `scripts/dr_drill.py` runs against the reference stack:
   1. Seed threads, memories and an erasure.
   2. Take a base backup and archive WAL.
   3. Write more data, then restore to a recorded point in time on a new Postgres container.
   4. Point one API replica at the restored database and run `setup` and the smoke test.
   5. Replay the erasure from the restore runbook and check it.
   6. Check the `UNLOGGED` rate-limit table is empty, as `OPERATIONS.md` says.

   It records the drill's RTO and RPO and deletes the restored container. Hosted PITR values stay blank in
   `OPERATIONS.md` until after v1.0.0.

10. **Rollback rehearsal.** The new image is deployed onto the reference stack with its
    migration applied, then rolled back to the previous release's image per the rollback
    runbook. The smoke test must pass on the old image against the migrated database. This
    proves the expand-then-contract rule (ADR 0008) for the v0.8.0 to v0.9.0 migrations, and the
    result is recorded.

11. **Release freeze.** The freeze starts when v0.9.0 is tagged and holds until v1.0.0:
    - `main` takes fixes, docs, dependency and security updates only.
    - The `/v1` API, `STREAM_PROTOCOL_VERSION` 1, `APP_*` setting names and existing migrations
      do not change incompatibly.
    - New migrations are additive.
    - An exception needs the owner's approval recorded in the PR.

    `CONTRIBUTING.md` states the policy, and the PR template gains a freeze checkbox.

12. **Pre-release tags.** v1.0.0 is preceded by `v1.0.0-rc.N` tags from `main`.
    - `TAG_PATTERN` accepts `-rc.N`.
    - `check-release` requires the CHANGELOG section of the base version.
    - `deploy.yml` skips the production job for pre-release tags. Today a `v*` tag of any shape
      triggers it.
    - The GitHub Release for an `rc` tag is marked as a pre-release.

    Tests cover each rule.

13. **Live evidence.** One live `--trials 3` run of the regression and security suites on the
    NVIDIA development model is recorded and committed as the v0.9.0 baseline, with
    `compare` against the latest committed baseline. A failing or inconclusive `compare` is
    recorded honestly, with the owner's sign-off, as in ADR 0008 open question 18.

## Consequences

- Locust and a ZAP workflow join the toolchain. Locust adds no runtime dependency.
- Capacity numbers exist for the first time. They describe one local host, and every
  document that quotes them says so.
- The fake model gains settings. A guard and its test keep them out of staging and production.
- v1.0.0 still ships without any hosted deployment having run. This is accepted by the
  owner, stated in the release notes, and is the main known issue of the candidate.
- After the freeze, a contract change waits until after v1.0.0 or needs an owner exception.

## Alternatives considered

- **k6.** It is strong for CI thresholds, but it is AGPL-licensed, adds a second JavaScript
  toolchain beside `web/`, and its SSE support is disputed in the sources.
- **LLM benchmarks** (GenAI-Perf, llmperf). They measure a model server, not an authenticated
  agent API with threads, approvals and limits.
- **Loading the NVIDIA API.** Its rate limits would be measured instead of the service, and
  the terms of use were not checked.
- **Render staging for v0.9.0.** This is research option B, which the owner declined.
- **A fixed runs-per-second target.** It was declined by the owner. With no product traffic
  estimate it would be invented.

## Open questions

1. **Fake-model profile for the baseline** (research Q5). Proposed: 800 ms to first token,
   40 tokens per second and 200 output tokens, which approximates the NVIDIA runs in the
   v0.5.0 gate. To be confirmed in the fake-latency issue against those logs.
2. **Security scope** (Q6). Proposed: the threat model and DAST in v0.9.0, and an external
   pentest after v1.0.0. #290 (CSP and silent renew in a real browser) stays deferred with
   #293, per the owner's answer. Pulling it forward is the owner's call, because it is
   the only deferred security item a local stack can close.
3. **Freeze and `rc` tags** (Q7). The proposal is decisions 11 and 12.
4. **#103, #162, #210** (Q8). Proposed: #210 (refuse a public bind with auth off) in
   v0.9.0 as a small hardening fix before the freeze; #103 and #162 after v1.0.0.
5. **Postgres TLS on the reference stack.** Either a self-signed certificate so the
   production profile validates unchanged, or a listed relaxation. To be decided in the
   reference-stack issue.
