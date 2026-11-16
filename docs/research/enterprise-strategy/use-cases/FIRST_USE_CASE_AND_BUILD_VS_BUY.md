# Agent Platform Research 03 — First Use Case & Build-vs-Buy

Oct 19, 2026 · @Md Nisar Ahmed

## Decision summary

**First use case: "My Pending Actions & Workflow Status" (C2)**, a read-only assistant that answers *what is waiting on me or my team, what is stuck, who holds it, and what happens next* across goal sheets, reviews, check-ins and hub tasks in Skylark. It scored highest (31/35) in the codebase review, reaches every persona daily, and is the safest candidate to run on today's codebase because it needs no write paths.

**One refinement to the codebase report.** The answer to "what is my next action" should be *computed by code, not reasoned by the model*. Skylark's goal-sheet state machine (\~70 states) is deterministic, so a server-side **pending-actions service** decides the facts and the agent only finds, filters and explains them. This follows the workflow-first rule in Agent Platform Research 01 — Architecture & Implementation Blueprint, makes every answer checkable, and ships in two steps: a deterministic digest in Phase 0, then a conversational agent in Phase 1.

**Build vs buy: build a thin runtime on our own stack, and treat the Skylark-side tool layer as the real project.** Whatever runtime is chosen, the hard work is on the Skylark side: a curated read-only tool layer with per-user and per-tenant checks, correlation IDs, and payload minimisation. Do not extend the current `cgpt` service as-is. A managed runtime (e.g. AWS Bedrock AgentCore) stays an option to test in the Phase 0 spike, not a default.

**Hard prerequisites before any agent traffic:** close the unauthenticated `cgpt` routes, rotate the hardcoded fallback credentials, stop logging full user context, and add correlation IDs. These are security fixes the codebase needs regardless of this project.

**Runners-up:** bulk-upload triage for HR admins (C3) as the second agent, and the Goal Quality Coach (C1) once its prompts move off the unauthenticated route. Design patterns are drawn from Agent Platform Research 02 — Harness & Platform Design Study.

## 1. Inputs and method

The decision rests on a read-only Claude Code review of the Skylark codebase (branch `sprint`, 19 Oct 2026), which describes data by field type only and contains no personal data, tenant names or secrets. This doc does not re-audit the code; it tests the report's recommendation against the platform principles in Research 01 and the design patterns in Research 02.

**What the codebase review established** (all \[C\] confirmed in code unless marked):

| Area | Finding that shapes the decision |
| --- | --- |
| Shape | Modular monolith: 49 Maven modules in one Spring Boot jar, four Angular frontends, a Node LLM service (`cgpt`), shared database with a tenant column on every row |
| Business focus | Strongest in performance management (goal sheets, reviews, check-ins, 360, calibration, PIP), then talent (skills/KSAT, IDP, succession). No leave, payroll, onboarding or wellness domain |
| Workflows | Goal-sheet state machine of \~70 states with up to three approval levels plus HR; about 15 reset and force-close endpoints and several stuck-state repair jobs, which signal frequent confusion and stuck items |
| Existing AI | \~25 Java call sites and several UI panels call `cgpt` (LangChain JS, OpenAI only). An external WorkWise agent already uses Skylark endpoints as tools. No evals, no cost accounting, no PII masking on LLM payloads |
| Agent-readiness gaps | Tenant scoping applied by hand per query; weak object-level authorisation on `/v1/hub/**`; no idempotency keys; some state-changing GETs; no rate limits; no correlation IDs |
| Reusable strengths | JWT already carries tenant and user; hub reads derive the current employee server-side; per-tenant API consumers with URL allow-lists; Envers audit tables; a 24-step end-to-end API test chain covering the review cycle |

**How the candidates were judged.** The report scored 12 candidates from 1 to 5 on seven criteria: user value, frequency, data readiness, tool readiness, evaluability, low risk and low build cost. Scores are \[I\] judgements grounded in code evidence. This doc adds two checks from Research 01: whether the core logic can be a deterministic workflow, and whether the use case stays within the Agents Rule of Two.

**Evidence labels.** \[C\] confirmed in code, \[I\] inferred from structure, \[U\] unknown and needing a human to confirm, \[R\] this doc's recommendation.

## 2. Candidate shortlist and scoring

C2 wins on the report's own scores and also passes the two extra checks: its core logic is deterministic, and it stays read-only, so it never combines all three Rule of Two risks. The other high scorers are good *second* agents rather than better first ones.

| # | Candidate | Score /35 | Deterministic core? | Rule of Two (untrusted input · sensitive data · state change) | Verdict \[R\] |
| --- | --- | --- | --- | --- | --- |
| **C2** | **Pending Actions & Workflow Status** | **31** | Yes: state → next action → actor | Partial · Yes · **No** (read-only) | **First use case** |
| C3 | Bulk-upload & data-sync triage | 28 | Yes: validation rules and known errors | Yes (uploaded files) · Yes (PII) · No | Second agent; admin-only, needs masking |
| C12 | Product help Q&A | 28 | No: retrieval and generation | No · No · No | Low-risk warm-up; lower value |
| C1 | Goal Quality Coach | 27 | Partly: SMART scoring is LLM-judged | Low · Moderate · User-approved | Third; harden `cgpt` routes and add a SMART eval set first |
| C9 | Teams conversational front door | 26 | n/a: a channel, not an agent | Inherits from the agent behind it | Phase 2 channel for C2 |
| C4 | Check-in prep & summary | 25 | No | Low · Yes · No | Later; move the prompt server-side first |
| C8 | IDP plan drafting | 23 | No | Low · Moderate · Draft only | Later |
| C5 | Review-writing assistant | 21 | No | Low · High · Draft only | Later; high-sensitivity output needs strong evals |
| C7 | Admin workflow-ops copilot | 19 | Partly | Yes · Yes · **Yes** (resets) | Needs dry-run endpoints and approvals; not before Phase 2 |
| C11 | Ask HR analytics | 19 | No | Low · Yes · No | Needs a scope-safe query layer |
| C6 | Calibration prep analyst | 18 | Partly | Low · **Special category** (DOB, bonus) · No | Exclude from early agents |
| C10 | Program-setup copilot | 15 | No | Low · Moderate · **Yes** (\~76 write endpoints) | Exclude until write safety exists |

**Why not C12 first, since it is lowest risk?** It proves less. Help Q&A needs no tenant-scoped tools, so it would not exercise the per-user scoping, tool layer and tracing that every later agent depends on. C2 does, while staying read-only.

**Why not C1 first, since the pattern already exists?** Its value is seasonal (goal-setting time), its quality judgement is model-based and harder to evaluate, and its current path runs through an unauthenticated `cgpt` route that must be fixed first.

## 3. The chosen use case

The assistant answers one family of questions well: *what is waiting, on whom, for how long, and what unblocks it*. Everything outside that family is out of scope for v1.

### 3.1 Users and example questions

| Persona | Job to be done | Example questions |
| --- | --- | --- |
| Employee | Know what to do next and why something is not moving | "What do I need to do this week?" · "Why is my goal sheet still not published?" · "Who is my review waiting on?" |
| Manager (direct supervisor) | Clear their own queue and unblock direct reports | "Which goal sheets are waiting on me?" · "Whose check-ins are overdue?" · "What is stuck in my team and why?" |
| HR admin | See where a cycle is stuck across an org unit | "How many goal sheets in my unit are stuck at verifier stage?" (v2: needs the org-scope rules that today live in service code) |

### 3.2 Scope

| In scope for v1 \[R\] | Out of scope for v1 \[R\] | Reason |
| --- | --- | --- |
| Goal sheets (scorecards) and their approval chain | PIP | Disciplinary data; lifecycle actions lack caller checks today |
| Review cycle, including acknowledgement | Calibration | Contains date of birth and bonus multipliers (special category) |
| Check-ins | Succession and nine-box | Flight-risk data; role gates bypassable via hub aliases |
| Hub tasks (Things-To-Do) | 360 feedback content | Rater anonymity; v1 may show *status only*, never responses |
| Employee and direct-report views | Skip-level and org-wide views | Need verified hierarchy scoping first (v2) |
| Read-only answers with links into the app | Any write: submitting, approving, resetting, sending reminders | No idempotency keys or transition guards yet; reminders can come in v2 with human approval |

### 3.3 Workflow core, agent on top

&#91;R\] Split the use case in two, following the "start with workflows, earn autonomy" rule from Research 01:

- **Deterministic core (new Skylark service).** A *pending-actions service* reads goal sheets, reviews, check-ins and hub tasks for the signed-in user and returns, per item: type, state, next action, the role responsible, an opaque handle for the person holding it, due date, days in current state, and a *stuck* flag (past due, or in one state longer than a configurable threshold). The state → next action → actor mapping is written once in code from the existing state enums and tested against the 24-step end-to-end chain.
- **Agent layer (platform runtime).** One tool-using agent interprets the question, chooses which tools to call and with what filters, groups and ranks the results, and explains states in plain language in the user's locale. It never decides what the next action *is*; it reports what the service computed.

This split gives the Phase 0 deliverable for free: the deterministic core alone powers a **daily "pending actions" digest** in the app, with no model involved in deciding facts. The conversational agent follows in Phase 1 on the same service.

## 4. How it fits the platform

C2 uses every Phase 0–1 component from Research 01 (runtime, model gateway, tool gateway, tracing, eval harness) while touching Skylark only through new, read-only, user-scoped tools. That makes it the proving ground the later agents need.

&#91;embedded content: request flow · C2 pending-actions assistant\]

Read top to bottom: the user's own token travels down to Skylark, which computes the facts; the model only sees opaque handles and explains the result, and the browser restores names on the way back.

### 4.1 Tools for v1

| Tool \[R\] | Backed by | Returns | Guard |
| --- | --- | --- | --- |
| `list_my_pending_items` (type, stuck-only, due-before) | Pending-actions service, current user | Items with type, state, next action, responsible role, holder handle, due date, days in state, stuck flag, app link | Employee derived from the token, never from a parameter |
| `list_team_pending_items` (same filters) | Pending-actions service, direct reports | Same, per direct report (by handle) | Direct-report relationship verified server-side on every call |
| `get_item_status` (item handle) | Pending-actions service | State history (states and dates), next action, holder handle | Ownership check: caller owns the item or supervises its owner |
| `explain_state` (item type, state) | Static state map in code | Plain-language meaning of the state and what unblocks it | No personal data at all |

**Deliberately not exposed:** the existing `/v1/hub/perform/*` WorkWise endpoints (they take an `employeeId` parameter and can switch tenant), any write or reset endpoint, and the `cgpt` `/json` route.

### 4.2 Data handling

- **Handles, not names.** Tools return opaque per-run handles for people ("approver\_1"). The browser resolves them to names the user is already allowed to see, so names never reach the model or the traces. \[R\]
- **Titles, not comments.** v1 returns item titles but no comment or feedback text. This removes most untrusted free text and most performance narrative from the model's context. \[R\]
- **Special-category fields never leave Skylark.** Date of birth, national ID, bonus data, flight risk and wellbeing scores are out of scope by construction, not by prompt. \[R\]

### 4.3 Rule of Two check

| Property | C2 v1 | Why |
| --- | --- | --- |
| Untrusted input | Minimal | Only user questions and item titles; no comments, files or web content |
| Sensitive data | Yes | Performance-workflow status for the user and direct reports |
| External state change | **No** | No write tools exist |

At most two of three apply, so v1 needs no per-action human approval. \[R\] Adding any write (e.g. "send a reminder") in v2 makes all three apply, so it must come with human confirmation per action.

## 5. Build vs buy

The runtime choice matters less than it looks, because most of the work sits on the Skylark side and must be built under every option. \[R\] Build a thin runtime on our own stack, and test a managed runtime in the Phase 0 spike rather than assuming either.

### 5.1 Built under every option

| Skylark-side work | Why it cannot be bought |
| --- | --- |
| Pending-actions service (state → next action → actor) | Encodes Skylark's own \~70-state workflow |
| Curated read-only tool layer exposed over MCP, with tenant assertion, direct-report checks and rate limits | Today's endpoints have manual tenant scoping and weak object-level checks on `/v1/hub/**` |
| Correlation IDs across REST, queue and cron | No MDC or trace IDs exist today |
| `cgpt` security fixes: authenticate `/json` and `/ksat`, rotate fallback credentials, stop logging full user context | Required for any AI traffic, agent or not |
| Handle-to-name resolution in the browser | Part of the Skylark UI |

### 5.2 Runtime options

| Option | Strengths | Weaknesses | Verdict \[R\] |
| --- | --- | --- | --- |
| **A. Extend `cgpt`** (Node, LangChain JS) | Already deployed; team knows it; existing UI wiring | Unauthenticated routes, open CORS, hardcoded credentials, no tests, OpenAI-only, prompts scattered across four places | **No.** Fix its security issues, but do not grow the agent platform inside it |
| **B. Extend the external WorkWise agent** | Already calls Skylark endpoints as tools | Owner unknown \[U\]; it relies on `employeeId`-parameter endpoints that switch tenant and delegates authorisation upstream | **Not until ownership is clear.** Later, move it onto the new tool layer |
| **C. Thin runtime on our stack** (Python, FastAPI, LangGraph, per Research 01) | Matches the roadmap; provider-neutral; full control of tracing, evals and payload minimisation; agents stay portable | New service to run; Python is a new runtime language next to Java and Node | **Recommended default.** If the team is stronger in Node, LangGraph's JavaScript version is a fair alternative; decide in the spike |
| **D. Managed runtime** (e.g. AWS Bedrock AgentCore) | Runtime, memory, identity, policy and observability as services; Skylark already uses AWS services such as S3 \[I\] | Per-region residency and tenant model to verify; lock-in; still needs everything in 5.1 | **Evaluate in the Phase 0 spike** against option C on residency, isolation and cost |

**Model provider.** `cgpt` uses OpenAI only, and whether the platform may keep doing so, in which region per tenant, is an open legal question (section 8). \[R\] Put every model call behind the model gateway from day one so the provider can change per tenant without touching the agent.

## 6. Success metrics and evaluation plan

Because the pending-actions service computes the facts, it is also the answer key: every factual part of an agent answer can be graded by code, and model judges are needed only for how clearly the answer explains. All targets below are \[R\] starting points to calibrate on Phase 0 data.

### 6.1 Metrics

| Group | Metric | Definition | Target |
| --- | --- | --- | --- |
| Quality | Fact accuracy | Items, next actions and responsible roles in the answer match the service output | pass^3 ≥ 0.9 on the golden set |
| Quality | Grounding | Items or people mentioned that do not appear in tool results | 0 |
| Quality | Explanation clarity | LLM-judge rubric, calibrated against human labels | Judge–human agreement measured; clarity ≥ 4/5 |
| Safety | Scope leaks | Cross-tenant, non-direct-report or out-of-scope module data in any answer | 0 in negative tests |
| Safety | Injection resistance | Instructions planted in item titles change behaviour | 0 successes in the red-team set |
| Operations | Trace coverage | Runs with a complete trace and correlation ID | 100% |
| Operations | Latency | Time to full answer | p95 within the budget agreed in Q12 |
| Operations | Cost | Tokens and cost per conversation, per tenant | Reported from day one; budget set after Phase 0 |
| Outcome | Adoption | Weekly active users in the pilot tenant | Baseline in pilot, then target |
| Outcome | Stuck items | Median days items wait at approval stages, pilot vs. before | Measurable reduction |
| Outcome | Support load | "Stuck goal sheet or review" tickets | Reduction vs. baseline (Q8) |

### 6.2 Building the evaluation set

1. **States from the existing test chain.** Seed a test tenant by running the 24-step review-cycle chain in `automation/`, snapshotting each step. Each snapshot yields questions for the employee, each approver and HR.
2. **Answers from code.** Generate the expected answer for each question from the pending-actions service, so labels cost nothing and stay correct as the state map changes.
3. **Adversarial cases.** Instructions planted in goal and task titles; questions about another tenant, a non-direct report, or PIP and calibration; a manager asking about a former report.
4. **Locales.** Repeat a sample of questions in the languages the pilot tenant uses, since Skylark is multilingual.
5. **Real questions.** With the pilot tenant's agreement, add anonymised real questions from Phase 1 traffic each week, and turn every reported wrong answer into a test case.

**Grading.** Code graders check facts, grounding and scope; an LLM judge scores only explanation clarity, with judge–human agreement re-measured whenever the judge prompt or model changes.

## 7. Delivery plan

C2 maps directly onto the Research 01 roadmap: the deterministic digest is Phase 0's "one workflow in production", and the conversational assistant is Phase 1's "one tool-using agent with pilot users". Durations are \[R\] indicative and follow Research 01.

| Step | Duration | Deliverables | Gate to pass before the next step |
| --- | --- | --- | --- |
| **Prerequisites** | Weeks 1–2, overlapping Phase 0 | Authenticate `cgpt` `/json` and `/ksat`; rotate fallback credentials; stop logging full user context; correlation IDs across REST, queue and cron; answers to open questions 1, 2 and 12 | Security review signs off the `cgpt` fixes; legal confirms the model provider and processing region for the pilot tenant |
| **Phase 0 · Deterministic digest** | 6–8 weeks | Pending-actions service and state map, tested against the 24-step chain; daily "pending actions" digest in skylark-web for one pilot tenant; runtime interface, model gateway, OpenTelemetry tracing; eval harness v1 with the golden set; spike comparing option C with a managed runtime | Every state in the test chain maps to the correct next action and role; digest matches a manual check on sampled users; 100% of runs traced; eval suite runs on every change; runtime decision recorded |
| **Phase 1 · Conversational pilot** | 8–10 weeks | MCP tool layer with the four v1 tools, tenant assertion, direct-report checks and rate limits; agent in the skylark-web AI panel; handle-to-name resolution in the browser; red-team set; pilot with employees and managers in one tenant | pass^3 ≥ 0.9 on facts; 0 scope leaks; 0 injection successes; p95 latency within budget; cost per conversation reported per tenant |
| **Phase 2 · Expand** | Ongoing | Teams front door (C9); HR admin org-unit views; reminders with per-action confirmation; bulk-upload triage (C3) on the same tool layer; move the external WorkWise agent onto the tool layer if open question 1 says so | Each addition passes its own eval gate; adding writes requires human confirmation per action |

## 8. Risks and open questions

The biggest risk is not technical: the assistant could feel like a fancier version of the Things-To-Do inbox users already have. Its value must come from what the inbox cannot do, which is explaining *why* something is stuck, *who* holds it, and giving managers a team view. The pilot must measure that directly.

### 8.1 Risks

| Risk | Impact | Mitigation \[R\] |
| --- | --- | --- |
| Low added value over the existing inbox | Weak adoption; platform loses its first proof point | Lead with "why stuck / who holds it" and team views; set a kill criterion on pilot adoption and stuck-item metrics |
| State map wrong for edge cases (\~70 states, an overlapping \~75-value status enum, a known enum-chain bug) | Confidently wrong answers | Build the map from code and the test chain; unknown states return "status unclear, open it in the app" instead of a guess |
| Authorisation gaps (`/v1/hub/**` aliases, parameter-based IDs) | Data from other users or tenants leaks through a tool | Tool layer performs its own tenant and ownership checks; cross-tenant and non-report negative tests in every eval run |
| Load on the monolith (no rate limits, synchronous loads, no timeouts on internal calls) | Slow app for everyone during peaks such as review season | Per-user and per-tenant rate limits; cache the digest; timeouts and circuit breakers on tool calls |
| Two assistants (WorkWise chat, external WorkWise agent, and C2) | Confusing experience; duplicated effort | Product decision on open question 1; route "what is pending" questions to C2 |
| Employment-law limits on AI over performance data | Pilot blocked in some regions | C2 reports workflow status, not evaluations, which lowers the risk; confirm under open question 7 before the pilot |
| Team capacity | Skylark-side work competes with sprint commitments | Name owners for the pending-actions service and tool layer before Phase 0 starts |

### 8.2 Open questions

Numbers 1–12 follow the codebase report; 13–15 are new.

| # | Question | Owner | Needed by |
| --- | --- | --- | --- |
| 1 | Who owns the external WorkWise agent, and should the new platform replace or extend it? | Engineering, Product | Phase 0 start |
| 2 | May the platform use OpenAI, and in which processing region per tenant? Are data-processing agreements in place for performance data? | Legal, Security | Prerequisites gate |
| 6 | What retention applies to chat memory, stored prompts and AI feedback records? Any tenant opt-out? | Legal, Product | Phase 1 pilot |
| 7 | Do any regions restrict AI-generated views of performance-workflow data for managers or HR? | Legal, HR | Phase 1 pilot |
| 8 | Which persona raises the most "stuck goal sheet or review" tickets, and how many per month? | Support | Phase 0 (baseline) |
| 10 | Is the `/v1/hub` alias on role-gated controllers intentional, and is a fix planned? | Engineering | Phase 1 |
| 12 | What latency and cost budget applies per interaction, and who owns LLM cost per tenant? | Product, Finance | Phase 0 gate |
| 13 | How many days in one state counts as "stuck", and should tenants configure it? | Product | Phase 0 |
| 14 | Which tenant pilots, and does it agree to anonymised question sampling for evals? | Product, Customer success | Phase 0 |
| 15 | Who owns the pending-actions service and the tool layer long term? | Engineering leadership | Before Phase 0 |
