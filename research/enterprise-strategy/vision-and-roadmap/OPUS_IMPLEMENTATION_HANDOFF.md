# Opus Implementation Handoff

| | |
| --- | --- |
| Date | 2026-11-10 |
| Package | Document 14 of 14 |
| Audience | The owner, who approves; and the implementing agent, who builds |
| Status | **Nothing here is approved.** The owner accepts ADR 0015 first. Work packages are specifications, not instructions to start. |
| Evidence | Repository facts are from `NEURON_CURRENT_ARCHITECTURE_ASSESSMENT.md`. Sizes are estimates. No code was written or changed for this package. |

## 1. The strategy on one page

**The question:** if Neuron is to become a leading domain-agnostic enterprise agentic integration platform within three years, what must be built, integrated, prioritised and avoided?

**Build** (these seven are the product):

1. An application onboarding pipeline: registry, manifest, OpenAPI and MCP import, human curation with risk classes.
2. A credential broker, so the agent acts with the requesting user's own access.
3. A policy decision point with rules as data, default deny.
4. An approval service with tiers, bound to exact arguments, answerable later by another person.
5. A durable run engine with an event log.
6. Domain packs: namespaced, versioned business context per application.
7. An append-only audit ledger.

**Integrate** (never build): identity providers, connector catalogues and iPaaS (through MCP), secrets stores, API gateways, observability backends, RPA for applications with no API, customers' existing workflow engines.

**Prioritise**, in this order:

1. Evidence: one hosted deployment and one entry point.
2. Organisation model, policy, audit.
3. One application onboarded with per-user access (use case 1).
4. A second domain with configuration only (use case 2).
5. Durable approvals and one cross-application workflow (use case 3).
6. Packaging for self-hosting, a penetration test, an MCP endpoint so other assistants can call Neuron.

**Avoid:** a connector marketplace, a visual workflow builder, a control tower for other vendors' agents, in-house browser or screen automation, industry-specific agents in the core, a knowledge graph database, agent swarms, model hosting, and a multi-tenant hosted service before a customer funds it.

**Position:** the open-source, self-hostable agent layer for an organisation's own applications. Not a universal integration platform; that claim is already made by at least ten larger vendors (`COMPETITIVE_POSITIONING.md`).

**The test of success:** a person outside the project onboards an unfamiliar application from the documentation, with no change to core code.

## 2. Standing rules for the implementer

These come from the repository (`CLAUDE.md`, `AGENTS.md`, `docs/AI_CODE_VERIFICATION.md`) and from this package.

1. **ADR before code.** Each work package names its ADR. The ADR is written, reviewed and accepted by the owner before implementation. The current ADRs forbid queues, custom persistence, subgraphs and multi-agent orchestration without one.
2. **Small pull requests.** Under 400 changed lines, with tests that fail without the change.
3. **All gates.** `make format lint typecheck test security` must pass before any claim that work is verified.
4. **Critical tier.** Changes to `security/`, `tools/`, the broker, the decision point, approvals and the audit ledger get the `security-reviewer` agent and the threat model is updated.
5. **No domain logic in `src/`.** No application name, entity name or industry rule appears in core code or core prompts. A test should enforce this once use case 1 exists.
6. **Behaviour-preserving first.** Refactors land separately from features, with the existing suite unchanged.
7. **Default deny, fail closed.** Any new decision path denies when its data is missing or its store is unreachable.
8. **No new dependency without a written reason.** Document 10 lists the expected ones.
9. **Knowledge Engine work** follows the tracker's "New session protocol".
10. **Report honestly.** A release record states what was and was not run, as the existing ones do.

## 3. ADRs to write

Numbers continue from the existing 0014.

| ADR | Decision | Amends or supersedes |
| --- | --- | --- |
| 0015 | Product direction: positioning, principles, non-goals, the cold onboarding acceptance criterion | Frames all others |
| 0016 | Retire the Agent Server entry point | 0001, 0009 |
| 0017 | Thread and run tables; idempotent run creation | 0005, 0011 |
| 0018 | Organisation, department and role model | 0006 |
| 0019 | Policy decision point and rule storage; emergency stop | 0003 |
| 0020 | Audit ledger | 0007 |
| 0021 | Run engine and durable execution, with the spike result | 0001 (item 5), 0005 (non-goal) |
| 0022 | Application registry, manifest, capability catalogue and executor | 0003, 0009 |
| 0023 | Connection manager and credential broker; secrets interface | 0006 |
| 0024 | Domain packs | New |
| 0025 | Approval service and tiers | 0003 |
| 0026 | Event ingress and schedules | New |
| 0027 | Agent definitions and versions | 0001 |
| 0028 | Workflow definitions and compensation | 0001 |
| 0029 | Neuron as an MCP server | 0009 |

## 4. Work packages

Each package is sized to be split into pull requests under the 400-line rule. "Verify" is the evidence the owner should ask for.

### Phase 0

**WP-01 Product-direction ADR and documentation corrections** (F0.1)
- Scope: write ADR 0015 from documents 1, 4 and 10. Correct the discrepancies in the assessment's section 8 (`ARCHITECTURE.md`, `CLAUDE.md`, `README.md`, `SECURITY.md`, `docs/ROADMAP.md`).
- Out of scope: any code.
- Verify: each discrepancy row is closed in the pull request description.

**WP-02 Hosted deployment and baseline** (F0.2)
- Scope: resolve the `sslmode=verify-full` blocker in `render.yaml` or choose another host; deploy; run the load baseline with a real model; exercise restore and rollback; dashboards.
- Needs from the owner: a hosting account, a model provider key, a budget for the load run.
- Verify: a release record with measured figures and conditions.

**WP-03 Retire the Agent Server path** (F0.3, ADR 0016)
- Scope: remove `langgraph.json` production use, `security/agent_server.py`, the import-time graph and the dual authorization branch in `graphs/main_graph.py`. Keep a development-only inspection path only if the owner wants it.
- Verify: a security test shows no route to the graph bypasses the run service.

**WP-04 Application factory and service split** (F0.4)
- Scope: application factory; routers for agent, threads, me, knowledge; `AgentService` into run, thread and data-rights services; one audit helper replacing the 18 repeated expressions; move the evaluation modules out of the request-path package; one import-contract test for all packages.
- Out of scope: behaviour changes.
- Verify: unchanged test suite passes; module sizes reported before and after.

**WP-05 Thread and run tables** (F0.5, ADR 0017)
- Scope: `threads` and `runs` tables written in the turn's transaction; `Idempotency-Key` on invoke and stream; ownership read from one place; listing without per-thread checkpoint loads; a migration and backfill.
- Verify: query-count test for listing; retry test for idempotency; migration tested on a copy with existing threads.

### Phase 1

**WP-06 Organisation model** (F1.1, ADR 0018)
- Scope: organisation and department tables; organisation id on every table with a backfill to a default organisation; row-level security policies; fixed role set from IdP group claims.
- Verify: isolation tests at SQL and API level for every table.

**WP-07 SSO federation** (F1.2)
- Scope: documented and tested federation of one OIDC and one SAML IdP through Keycloak; group-to-role mapping.
- Out of scope: SCIM (later package).
- Verify: end-to-end tests with both IdP types in the reference stack.

**WP-08 Policy decision point** (F1.3, ADR 0019)
- Scope: decision interface (inputs and three outcomes); typed rule tables; migrate existing scope, risk and taint behaviour into rules; argument-conditioned rules; data-label rules; dry-run mode; emergency stop.
- Out of scope: Cedar or OPA.
- Verify: old enforcement code path removed with the security suite still passing; allow and deny tests per rule type; fail-closed test.

**WP-09 Audit ledger** (F1.4, ADR 0020)
- Scope: append-only table with the fields in document 7, section 8; insert-only grant; hash chain; export command; auditor role; reconciliation job against executor counts.
- Verify: one record per decision and call across the suite; update and delete denied for the application role; chain test.

**WP-10 Durable-execution spike** (document 10, section 2.3)
- Scope: a time-boxed comparison of extending Procrastinate against adopting DBOS Transact, on three tests: crash mid-tool-call, a one-day approval wait, 200 concurrent runs.
- Out of scope: production code.
- Verify: a written result that ADR 0021 cites.

**WP-11 Durable runs and resumable streams** (F1.5, ADR 0021)
- Scope: run worker role; run events; leases with heartbeat and fencing; stream from the event log with offset resume; idempotency keys on mutating tools; run timeline in the client. Keep the synchronous path behind a setting until parity.
- Verify: worker-kill tests; reconnect test; 24-hour wait test (time-shifted); the full security suite on the durable path.

### Phase 2 (ends with use case 1)

**WP-12 Application registry and manifest** (F2.1, ADR 0022)
- Scope: registry tables and API; manifest versions and lifecycle; import of the existing MCP server file.
- Verify: register, publish, retire without restart.

**WP-13 Credential broker** (F2.2, ADR 0023)
- Scope: secrets interface with an envelope-encrypted Postgres backend and an OpenBao backend; delegation mode B flows (connect, refresh, disconnect); mode D with its restrictions; mode A after B.
- Critical tier.
- Verify: marker-credential search across context, checkpoints, events, logs and traces; two-user permission-fidelity test; revocation test.

**WP-14 OpenAPI importer and catalogue** (F2.3)
- Scope: import, default filtering, risk classification that never lowers automatically, curation API, pinning, drift suspension, principal-bound parameters.
- Verify: import of the chosen CRM's specification; drift test; no application-specific code added.

**WP-15 Capability executor** (F2.4)
- Scope: HTTP adapter with validation, pagination, retries with idempotency, per-application limits and circuit breaker, error normalisation, response caps, connection reuse, per-application private-host allow-list.
- Verify: failure-mode tests listed in F2.4.

**WP-16 Dynamic capability selection** (F2.5)
- Scope: per-run capability sets; catalogue search; stable prompt prefix.
- Verify: synthetic catalogue of 300 capabilities; retrieval evaluation.

**WP-17 MCP client, second generation** (F2.6) and **integration health** (F2.7)
- Scope: MCP servers as registry applications with per-user OAuth, re-discovery with pin review, pooled sessions; per-application health in API and metrics.
- Verify: two-user test against an OAuth-protected MCP server; drift suspension; health state change on outage.

**WP-18 Use case 1** (document 12, section 2)
- Scope: choose and stand up the CRM; write its manifest, pack stub, policies and evaluation cases as configuration; record onboarding effort and every core change it forced.
- Verify: the use case's success metrics.

### Phases 3 to 5

Specified at lower resolution on purpose. Each is detailed when its phase starts, using what the earlier phases taught.

| Package | Features | ADR | Gate |
| --- | --- | --- | --- |
| WP-19 Domain packs | F3.1 | 0024 | Homonym, leakage and no-link tests |
| WP-20 Shared knowledge | F3.3 (aligned with RAG-E09) | Amend 0014 | SQL-level grant tests |
| WP-21 Per-application evaluation | F3.5 | Amend 0007 | Publish gate enforced |
| WP-22 Agent definitions (minimal, then full) | F4.4 | 0027 | Two agents, version recorded per run |
| WP-23 Context management and model registry | F3.4 | Amend 0001 | No regression at lower token cost |
| WP-24 Assisted drafting | F3.2 | Within 0024 | Poisoned-specification test |
| WP-25 Use case 2 | Document 12, section 3 | | Zero domain-specific core changes |
| WP-26 Approval service and inbox | F4.1 | 0025 | Expiry, replay, tamper, self-approval tests |
| WP-27 Event ingress and schedules | F4.2 | 0026 | Signature, replay and unattended-write tests |
| WP-28 Workflow definitions and compensation | F4.3 | 0028 | Failure injection at every step |
| WP-29 Use case 3 | Document 12, section 4 | | Exactly-once and compensation metrics |
| WP-30 Usage, cost and quotas | F5.2 | Amend 0004 | Department quota test; cost reconciliation |
| WP-31 Administration console | F5.1 (incremental from phase 2) | Amend 0010 | Cold onboarding done in the console |
| WP-32 Packaging and recovery | F5.3 | Amend 0008 | Install, upgrade and restore by an outsider |
| WP-33 MCP server | F5.4 | 0029 | External client sees only permitted capabilities |
| WP-34 Authoring kit and cold onboarding test | F5.5 | | The acceptance criterion in document 5, section 14 |
| WP-35 Penetration test support | F5.6 | | High and critical findings closed |

## 5. Decisions the owner must make first

The implementer cannot make these.

| # | Decision | Options | Recommendation |
| --- | --- | --- | --- |
| 1 | Accept the narrowed positioning | The broad "universal platform" claim, or "open-source agent layer for your own applications" | The narrowed one (document 4) |
| 2 | Agent Server path | Remove, or bring to parity | Remove |
| 3 | Hosting for the first deployment | Render (blocked today), or another host | Whichever resolves the TLS issue fastest |
| 4 | Stand-in applications | Candidates in document 12 | Confirm APIs and authentication, then choose |
| 5 | Revenue model | Support, hosted service, paid administration features, none yet | Decide before phase 5; it affects which features stay open |
| 6 | Design partner | Find one before phase 2 ends | Without one, outcome metrics stay unmeasured |
| 7 | Durable-execution choice | After WP-10 | Follow the spike |
| 8 | Budget for an external penetration test | | Required before real data |

## 6. Known gaps in this research

The implementer and owner should treat these as open.

1. Two prior reports named in the brief (open-source ecosystem, commercial product intelligence) were not in the workspace. This package re-covered them briefly.
2. Web research used search excerpts. Primary pages were not read in full. Prices and dates conflict between sources in several places (document 2).
3. Not searched: Dynamics 365, HubSpot Breeze, Informatica, Elastic, Coveo, NVIDIA, Cloudflare, Palo Alto's AI security products, LlamaIndex, Unstructured.
4. Licences of Cedar, Cerbos, Restate, Langfuse, Phoenix and the stand-in applications are unconfirmed.
5. The full OWASP agentic list was not retrieved.
6. No customer or user was interviewed. The thirty problems are reasoned, not observed.
7. No capacity figure is measured. Document 8 is design reasoning.
8. Regulatory notes are orientation, not legal advice.

## 7. First assignment

If ADR 0015 is accepted, the first three packages can be assigned immediately and do not depend on any open decision except hosting:

1. **WP-01** documentation corrections (with ADR 0015 itself).
2. **WP-03** retire the Agent Server path (ADR 0016).
3. **WP-02** hosted deployment and baseline.

WP-04 and WP-05 follow. Nothing in phase 1 should start until WP-02 has produced a recorded baseline.
