# Neuron — Global Agent Architecture Research

Date: 2026-11-10. Companion to `NEURON_CURRENT_ARCHITECTURE_ASSESSMENT.md` (referred to below as "the assessment").

## How this was produced, and how far to trust it

- **Sources.** Web searches restricted, where possible, to official documentation, vendor engineering blogs and public repositories. Thirty-four queries were run. Section 9 lists the pages relied on.
- **Depth.** I worked from the search engine's excerpts of those pages. I did not open and read each primary page end to end. Anything load-bearing for a decision should be re-read at the source first.
- **Evidence labels.** Every claim about a vendor carries one of three labels:
  - **[V]** — stated on the vendor's own documentation, blog or repository.
  - **[S]** — reported only by a third party (press, independent blog). Not confirmed against the vendor.
  - **[I]** — my inference from public behaviour. Not stated by anyone.
- **What is not known.** No vendor publishes its full internal architecture. Devin, Cursor, Manus, Perplexity and the ChatGPT agent in particular publish principles and product behaviour, not system designs. Where a cell in the matrix says "not published", that is the finding.
- **Neuron facts** come from the assessment, which was a static code read. Nothing was executed for this document, and no code or existing file in the repository was changed.
- **Time sensitivity.** Several products are in preview or being renamed (LangGraph Platform → LangSmith Deployment; Bedrock Agents → "Classic", closed to new customers from 2026-07-30 [V]; OpenAI reported as winding down Agent Builder and Evals [V, from a note on OpenAI's own announcement page; scope not checked]). Product names and limits here will age quickly.

## 1. Summary

1. **The industry has converged on one loop and diverged on everything around it.** Every product studied runs the same core: a model calls tools in a loop until it stops. Differentiation is in the harness: context management, where execution happens, how state survives, and how actions are authorised.
2. **Neuron's loop is standard. Its harness is strong on authorisation and weak on durability and context.** Neuron's identity, tool gating, taint tracking, token accounting and audit are at or above what the open-source SDKs ship by default. Its runs die with the process, its streams cannot be resumed, and its conversation history discards tool results. Those three are where it differs most from every leader.
3. **The single most repeated architectural idea is separating the run from the request.** Anthropic (session log outside the harness), LangChain (background runs on a task queue), Google (background interactions), AWS (per-session microVMs) and Microsoft (checkpointed workflows) all make a run a durable object the client attaches to. Neuron ties a run to one HTTP connection.
4. **The second is treating the context window as a managed resource.** Anthropic, Manus, Google ADK, OpenAI Codex and LangChain Deep Agents all publish explicit techniques: compaction, tool-result clearing, files as external memory, stable prefixes for cache hits, and sub-agent isolation.
5. **Most of what makes the coding and computer-use agents impressive does not apply to Neuron.** Sandboxed VMs, browsers, hundreds of parallel agents and multi-day runs serve products whose job is to operate a computer. Neuron is a governed question-answering and tool-calling service. Adopting those would add its largest attack surface for no stated product need.
6. **Multi-agent is a narrower win than its popularity suggests.** Anthropic reports a 90.2% gain on its research eval at roughly 15× the tokens of chat [S, quoting Anthropic]. Cognition argues against it by default and, in its 2026 follow-up, accepts only designs where sub-agents read and one agent writes [V]. Cursor found a flat peer structure failed and a planner/worker split worked [S, quoting Cursor].

## 2. Organisation profiles

Each profile lists what is published, then what is inferred. The sixteen dimensions are compared side by side in section 3.

### 2.1 Anthropic — Claude Agent SDK, Claude Code, Claude Cowork, Managed Agents

- **Loop and SDK.** The Agent SDK exposes the same tools, loop and context management as Claude Code, in Python and TypeScript [V]. It has hooks at lifecycle points such as `PreToolUse`, permission modes with allow and deny lists, sub-agents, and sessions that can be resumed or forked [V].
- **Context.** Anthropic's "Effective context engineering" post (2025-09-29) frames context as a finite resource [V]. The platform ships context editing (drops old re-fetchable tool results but keeps the record of the call), a file-based memory tool, tool search (definitions loaded on demand; suggested above roughly 20 tools) and programmatic tool calling (the model writes code that calls tools in a sandbox) [V]. Anthropic reports memory plus context editing improved an internal eval by 39% [V].
- **Sub-agents.** They run in a separate context and return a summary to the parent [V].
- **Long-running work.** "Effective harnesses for long-running agents" (2025-11-26) addresses work that spans many context windows; the published pattern is a progress file and task list that each new session reads first [V for the problem statement; S for the pattern summary].
- **Managed Agents.** The April 2026 post "Decoupling the brain from the hands" splits the system into the brain (model plus harness), the hands (sandboxes and tools) and the session (an append-only event log) [V]. Containers are provisioned only when a tool call needs one [V]. Interfaces such as `getEvents`, `wake`, `emitEvent` and `execute(name, input)` and "credentials kept out of the sandbox" are reported by secondary summaries [S].
- **Sandboxing.** Claude Code's sandbox combines filesystem and network isolation, and Anthropic states both are required: without network isolation files can be exfiltrated, without filesystem isolation the network boundary can be bypassed [V]. Permission rules and the sandbox are separate layers [S].
- **Checkpoints.** Claude Code takes a checkpoint before each prompt and can rewind edits made by its file tools [V].
- **Cowork.** An official architecture page exists; it states the VM enforces network egress filtering, syscall restrictions and per-session user isolation [V]. Folder-scoped file access, remote MCP connectors and plugins bundling skills, connectors and sub-agents are described by secondary sources [S].
- **Multi-agent research.** Lead agent plus parallel sub-agents; 90.2% better than a single agent on Anthropic's internal research eval, at about 15× the tokens of chat [S, quoting the Anthropic post].
- **Inference.** Model routing inside Claude Code (which model handles which sub-task) is configurable but its defaults are not an architectural publication [I].

### 2.2 OpenAI — Agents SDK, Codex, ChatGPT agent

- **Agents SDK.** Primitives are agents (instructions, tools, guardrails, handoffs) and a runner that loops, switches agent on handoff, and stops on completion or when paused for approval [V]. It has sessions, human-in-the-loop, built-in tracing and, more recently, sandbox agents with resumable sandbox sessions [V].
- **Codex loop.** "Unrolling the Codex agent loop" (2026-01-23) describes the CLI harness calling the Responses API [V]. Each prompt is an exact prefix of the next so prompt caching works, and a dedicated endpoint compacts the conversation once an auto-compact limit is exceeded [S, summarising the post].
- **Codex security.** Two independent controls: the sandbox sets technical boundaries, the approval policy decides when to stop and ask [V]. Network access is off by default in the workspace-write sandbox [V]. OS mechanisms (Seatbelt on macOS, Landlock on Linux) are reported by third-party mirrors [S].
- **ChatGPT agent.** Runs on its own virtual computer with browser and terminal [S]. "Watch mode" supervises sensitive actions, "takeover" lets the user type secrets directly, and confirmations precede consequential actions [S]. OpenAI says it trained the model to ignore suspicious instructions and runs monitors that can stop the agent [S]. Independent critics note that watch-mode activation is heuristic, not deterministic policy [S].
- **Evaluation.** Trace grading assigns scores to an end-to-end trace of decisions and tool calls; datasets and graders sit beside it [V]. A notice on OpenAI's page says Agent Builder and Evals are being wound down [V; not investigated further].
- **Not published.** The ChatGPT agent's orchestration, routing between its browser tools, and monitor design.

### 2.3 Google — Agent Development Kit, Gemini Deep Research

- **ADK core.** Sessions hold events and per-conversation state; Memory is separate and spans sessions; artifacts store files [V]. In-memory services lose data on restart, so production uses managed back ends [V].
- **Context.** ADK has event compaction: a sliding window that summarises older events, configured by `compaction_interval` and `overlap_size`, with a pluggable summariser [V]. A Google Developers Blog post describes the context architecture for multi-agent production use [V, title only].
- **Resume and approval.** Resumability is opt-in through `ResumabilityConfig` (Python v1.16.0); it changes the flow for long-running functions, confirmations and authentication, and custom agents need extra work [V]. A tool can require a yes/no confirmation [V].
- **Evaluation.** `adk eval` runs eval sets; metrics include tool-trajectory and response-match scores [S for metric names; V that built-in evaluation and multi-turn datasets exist].
- **Deep Research.** Offered as an agent through the Interactions API. `background: true` runs server-side beyond HTTP timeouts; the client polls, streams, and can reconnect [V]. Collaborative planning returns a plan for the user to refine before the research runs [S, from a docs mirror and a Google employee's walkthrough]. It can combine Google Search, remote MCP servers, URL context, code execution and file search [V, launch blog].
- **Not published.** How Deep Research decomposes and schedules searches internally.

### 2.4 Microsoft — Agent Framework, Foundry Agent Service, Entra Agent ID, Agent 365

- **Framework.** Open-source successor to Semantic Kernel and AutoGen [V]. Two layers: agents, and graph-based workflows with type-safe routing, checkpointing and human-in-the-loop [V]. A middleware pipeline and OpenTelemetry observability are core [V].
- **Durable approval.** Workflows checkpoint, pause for a human decision, and resume from the checkpoint [V, Foundry blog]. The "approval arrives hours later through another channel" framing is from community write-ups [S].
- **Identity and governance.** Entra Agent ID gives agents their own identities; Conditional Access policies evaluate agent risk when a token is issued or refreshed [V]. Agent 365 is the registry and control plane: which agents exist, who owns them, whether they are blocked [V].
- **Inference.** Microsoft's distinctive bet is that agents are directory objects governed like users and service principals [I, from the product structure].

### 2.5 LangChain — LangGraph, Deep Agents, LangSmith Deployment

- **LangGraph.** Durable execution comes from the checkpointer; durability modes trade speed for safety (the `exit` mode persists only when the run ends) [V]. Interrupts require a checkpointer; the interrupted node re-executes on resume, so side effects must be idempotent or wrapped in tasks [V]. Time travel replays or forks from a checkpoint [V].
- **Deep Agents.** A harness on LangGraph with four defaults, all middleware: a `write_todos` planning tool, filesystem tools as working memory, a `task` tool that delegates to sub-agents with isolated context, and summarisation [V]. Filesystem back ends are pluggable: ephemeral state, real disk or the LangGraph Store [V].
- **Agent Server.** Resources are assistants, threads, runs and cron jobs, stored in PostgreSQL [V]. Background runs are queued, executed and checkpointed without a client connection [V]. Double-texting policies (reject, enqueue, interrupt, rollback) handle a new message during a run, and exist only on the server product, not in open-source LangGraph [V].
- **Relevance.** Neuron is built on this stack. It uses `create_agent` and the checkpointer, and implements its own leases and streaming instead of Agent Server's.

### 2.6 Cognition — Devin

- **Principles.** "Don't Build Multi-Agents" (June 2025): share full context, and treat actions as carrying implicit decisions; architectures that break these should be ruled out by default [V]. The April 2026 follow-up accepts a narrower class where sub-agents contribute intelligence and writes stay single-threaded; such sub-agents "mostly resemble tool calls" [V].
- **Product.** Managed Devins: a coordinator session delegates to child sessions, each in its own VM, and can message, sleep or terminate them and cap their compute budget [V]. Knowledge holds standing guidance; Playbooks are reusable task procedures [V]. Machine snapshots save environment state for later sessions [V, 2024 post].
- **Verification.** Devin fixes findings from its own review agent until the diff is clean [V].
- **Not published.** Models used, compaction method, planner design. Cognition publishes no system architecture.

### 2.7 Cursor

- **Scaling.** Hundreds of agents on one codebase for weeks. A flat structure failed (agents avoided hard tasks); separating planners from workers worked; removing an "integrator" role improved results; prompts mattered more than coordination machinery; different models suited different roles [S, summarising Cursor's January 2026 post].
- **Cloud agents.** Each runs in its own VM; they run in privacy mode; VMs and snapshots are deleted on timers [V]. Repository hooks run in cloud agents; enterprise admins manage hooks and network allow and deny lists [V].
- **Not published.** The harness internals, context assembly and code-indexing design in any detail I retrieved.

### 2.8 Perplexity

- **Deep Research.** It "iteratively searches, reads documents, and reasons about what to do next, refining its research plan", finishing in 2–4 minutes [V].
- **Computer.** Breaks work into tasks and sub-tasks and creates sub-agents; the stated premise is that different frontier models suit different work, so the system routes between them [V]. Which model does what, and the count of models, is press reporting [S].
- **Not published.** Retrieval stack, planning internals, verification.

### 2.9 Manus

- **Context engineering (2025-07-18).** KV-cache hit rate is called the most important production metric; keep the prompt prefix stable (no timestamps at the top), make context append-only, serialise deterministically [V]. Do not add or remove tools mid-run; mask them at decode time instead [V]. Use the file system as unlimited external memory so that shortening context is reversible [V]. Recite the plan (a todo file) to hold attention [V for the heading; detail not retrieved].
- **Execution.** Every session has a dedicated cloud VM [V]. Wide Research runs many sub-agents, each a full general-purpose instance [V].
- **Not published.** Model choice and routing, sandbox vendor, safety controls.

### 2.10 Amazon — Bedrock Agents (Classic) and AgentCore

- **Classic agents.** Action groups backed by Lambda, a ReAct-style orchestration loop over prompt templates, optional custom orchestrator, and "return of control" where the caller executes the action [V]. Closed to new customers from 2026-07-30; AWS directs users to AgentCore [V].
- **AgentCore Runtime.** Each session runs in its own microVM, destroyed and memory-sanitised at the end; 15-minute idle timeout, 8-hour maximum [V]. State in the session is ephemeral by design [V].
- **Identity.** The agent exchanges the user's JWT for a workload token that unlocks that user's entries in a token vault; the agent never holds refresh tokens or client secrets [S, consistent across sources].
- **Policy.** Rules in Cedar (or natural language compiled to it) are evaluated at the Gateway on every tool call, before the tool sees it [V, announcement].
- **Memory.** Short-term memory is an immutable event log per actor and session with configurable expiry; long-term memory is extracted from it asynchronously by strategies [S].
- **Evaluations.** Model-graded and code evaluators, online and batch [S].
- **Inference.** AgentCore is framework-agnostic infrastructure: it assumes the loop comes from elsewhere (including LangGraph) [I, supported by the product structure].

## 3. Comparison matrix

Cells are terse by design. "n.p." means not published. Evidence labels are in section 2; this table does not repeat them.

### 3.1 Frameworks and platforms

| Dimension | Anthropic | OpenAI | Google | Microsoft | LangChain | Amazon |
| --- | --- | --- | --- | --- | --- | --- |
| 1 Lifecycle | Single loop; hooks at each stage | Runner loop; stops on finish or approval | Runner over session events; callbacks | Agent loop plus graph workflows | `create_agent` loop on a graph | ReAct loop (Classic); bring your own (AgentCore) |
| 2 Planning | Model-driven; todo list; plan mode | Model-driven | Workflow agents; Deep Research plan review | Explicit workflows | `write_todos` tool | Prompt templates; custom orchestrator |
| 3 Tools | MCP, built-ins, tool search, code-driven tool calls | Function tools, hosted tools, MCP | Function tools, MCP, long-running tools | Functions, MCP | Tools, MCP | Lambda action groups; Gateway to MCP |
| 4 Multi-agent | Sub-agents return summaries; lead/worker research | Handoffs; agents as tools | Hierarchies; sequential/parallel/loop | Workflow orchestrations | `task` sub-agents; subgraphs | Supervisor (Classic) |
| 5 Context | Compaction, context editing, memory files, skills | Exact-prefix caching; compaction endpoint | Event compaction, caching | Middleware | Summarisation middleware; files | n.p. beyond memory |
| 6 Memory | File memory tool; project instruction files | Sessions | Memory service distinct from state | Foundry memory | Store | Event log plus extracted long-term |
| 7 Long-running | Session log; wake; multi-window harness | Background responses; cloud tasks | `background: true` interactions | Checkpointed workflows | Background runs; cron | 8 h sessions |
| 8 State | Append-only session events | Sessions; sandbox sessions | Session, events, state, artifacts | Workflow checkpoints | Checkpoints; threads/runs in Postgres | Ephemeral session; durable Memory |
| 9 Browser / computer | Computer use; sandboxed bash; Cowork VM | ChatGPT agent VM; Codex sandbox | Code execution; URL context | Via Foundry tools | Sandbox back ends | Browser and code interpreter tools |
| 10 Approval | Permission modes, rules, hooks | Approval interruptions; Codex approval policy | Tool confirmation with resume | Pause/resume workflows | `interrupt`; HITL middleware | Return of control; confirmation |
| 11 Routing | Per-agent model choice | Per-agent model | Per-agent model | Multi-provider clients | Per-agent or middleware | Per-agent |
| 12 Recovery | Rewind checkpoints; resume session | Resume sandbox session | Resume invocation | Resume from checkpoint | Replay/fork; durability modes | New microVM; state from Memory |
| 13 Evaluation | Guidance and tooling, not a harness product | Trace grading, datasets | `adk eval`, trajectory metrics | Foundry evaluations | LangSmith | AgentCore Evaluations |
| 14 Observability | Hooks, OTel export | Built-in tracing | Callbacks, plugins, tracing | OpenTelemetry | LangSmith, OTel | AgentCore Observability |
| 15 Security | FS + network sandbox; permissions | Sandbox + approvals; network off by default | Callbacks as guardrails | Entra, middleware policy | Left to the builder | microVM isolation; Cedar policy at Gateway |
| 16 Governance | Managed settings; enterprise hooks | Enterprise controls | Agent platform | Agent ID, Conditional Access, Agent 365 registry | Deployment RBAC | IAM, token vault, policy |

### 3.2 Products

| Dimension | Devin | Cursor | Perplexity | Manus | ChatGPT agent |
| --- | --- | --- | --- | --- | --- |
| 1 Lifecycle | Long session in a VM | Agent in editor or cloud VM | Search–read–reason loop | Loop in a VM | Loop on a virtual computer |
| 2 Planning | n.p.; playbooks guide | Plan mode; planner/worker at scale | Plan refined each iteration | Todo recitation | n.p. |
| 3 Tools | Shell, editor, browser, MCP | Editor, terminal, MCP | Search, connectors | VM tools; masked, not removed | Browser, terminal, connectors |
| 4 Multi-agent | Coordinator plus child VMs; single writer | Planners and workers | Sub-agents per sub-task | Parallel full instances | n.p. |
| 5 Context | Share full context | n.p. | n.p. | Cache-stable, append-only, files | n.p. |
| 6 Memory | Knowledge, playbooks | Rules | n.p. | Files | ChatGPT memory |
| 7 Long-running | Hours; sleep/wake | Days to weeks (preview) | Minutes | Session-length | Tens of minutes |
| 8 State | VM snapshots | VM snapshots | n.p. | VM file system | VM |
| 9 Browser / computer | Yes | Desktop in cloud VM | Agentic browser | Yes | Yes |
| 10 Approval | Human reviews PR | Review; hooks | n.p. | n.p. | Watch mode, takeover, confirmations |
| 11 Routing | n.p. | Different models per role | Core claim: route across models | n.p. | n.p. |
| 12 Recovery | Fix-until-clean review loop | n.p. | n.p. | Keep errors in context | Monitors stop the run |
| 13 Evaluation | n.p. | n.p. | Public benchmarks | None published | System card figures |
| 14 Observability | Session view | Agent view | n.p. | Session replay | n.p. |
| 15 Security | Isolated VMs | Isolated VMs; network lists | n.p. | VM | Trained refusal plus monitors |
| 16 Governance | Enterprise budgets, API | Admin hooks, privacy mode | Enterprise tier | n.p. | Enterprise controls |

## 4. Where Neuron stands

Status against each dimension. "Leaders" means the common practice in section 3, not any one vendor.

| Dimension | Neuron today | Status | Gap to leaders |
| --- | --- | --- | --- |
| 1 Lifecycle | `create_agent` loop behind `AgentService`, up to eleven middlewares | Has | None in the loop itself |
| 2 Planning | None; a middleware forces a knowledge search on the first model call | Missing | No plan artefact; forced step costs tokens |
| 3 Tools | `ToolSpec` registry with scope, risk, source, taint; MCP with pinned hashes and egress checks | Has | Tools fixed at start-up; no on-demand loading |
| 4 Multi-agent | None, by ADR | Missing (deliberate) | No context-isolated delegation |
| 5 Context | History trimmed; tool results dropped after each run | Partial | No compaction that preserves findings; no cache-aware prefix design |
| 6 Memory | `remember`/`forget` tools on a Postgres store | Partial | No extraction, provenance, expiry or user-facing review |
| 7 Long-running | Run lives in one process for one request | Missing | No background runs |
| 8 State | LangGraph checkpoints in Postgres; no threads table | Partial | Checkpoints double as the data model |
| 9 Browser / computer | None; no shell or code tools, by policy | Missing (deliberate) | See section 6 |
| 10 Approval | Human-in-the-loop for risky or tainted tool calls | Has | Approval is bound to the live run |
| 11 Routing | One model per deployment, with an optional ordered fallback list (`APP_FALLBACK_MODELS`); three providers | Partial | No per-task or per-request model choice |
| 12 Recovery | Atomic turn commit, leases, drain on SIGTERM | Partial | A crashed run is lost, not resumed |
| 13 Evaluation | Suites for quality, security and approvals, with confidence intervals and baselines | Has | No trajectory grading; no production-trace loop |
| 14 Observability | Structured logs, audit events, OpenTelemetry | Has | No user-facing run timeline |
| 15 Security | JWT, owner-key isolation, taint tracking, egress control, row-level security | Has (ahead of SDK defaults) | Rules live in code, not policy data |
| 16 Governance | Scopes, audit, token ledger, rate limits, retention | Partial | No agent registry, no per-tenant policy, no credential broker |

### 4.1 Capabilities Neuron already possesses

- A standard tool-calling loop with a middleware pipeline, the same shape as Deep Agents, Microsoft Agent Framework and the Claude Agent SDK hooks.
- Deterministic enforcement outside the model. This matches what Anthropic, OpenAI and AWS all state as the principle.
- Taint tracking that escalates approval once untrusted content enters a run. None of the SDKs studied ships this by default; ChatGPT agent's equivalent is reported to be heuristic.
- Human approval for risky actions, MCP with integrity pins, per-user data isolation, token budgets, audit events, OpenTelemetry and a regression eval harness.

### 4.2 Capabilities Neuron partially implements

- **State persistence.** Checkpoints exist, but there is no first-class thread or run record.
- **Memory.** Explicit save and forget only.
- **Context management.** Trimming without preservation.
- **Model abstraction.** Three providers behind one factory, selected per deployment.
- **Failure recovery.** Clean failure, not resumption.
- **Governance.** Good per-request controls; no organisation-level policy surface.

### 4.3 Missing capabilities

- Background runs and resumable streams.
- Any planning artefact.
- Context-isolated sub-agents.
- Per-task model routing. (An operator-wide fallback list already exists.)
- Trajectory evaluation fed by real traces.
- Credential brokering for user-authorised third-party tools.
- Code execution, browser and computer use (deliberately absent).

### 4.4 Important architectural differences

1. **Run ownership.** Leaders: the server owns the run and clients attach. Neuron: the request owns the run.
2. **Source of truth.** Leaders: an append-only event log or explicit thread/run tables. Neuron: checkpoint blobs.
3. **Where the agent acts.** Coding and computer-use products act inside an isolated machine. Neuron acts only through typed, scoped tools. This is a difference in product, not a deficiency.
4. **Policy location.** AWS and Microsoft express policy as data evaluated at a gateway or directory. Neuron expresses it as Python in `security/` and the registry.
5. **Two front doors.** No platform studied exposes the same agent through two paths with different guarantees. Neuron's Agent Server path does.
6. **Evidence of operation.** Every organisation studied runs its design in production at scale. Neuron has never been deployed.

## 5. Practices Neuron should adopt

Ordered roughly by evidence strength. Each is developed in section 7.

1. Decouple runs from requests with a durable event log.
2. Make streams resumable from that log.
3. Give threads and runs their own tables.
4. Preserve tool findings through compaction instead of dropping them, and keep the prompt prefix stable.
5. Let the model decide when to retrieve.
6. Add a plan/todo tool, not a planner node.
7. Express tool authorisation as policy data, evaluated at one choke point.
8. Make approvals durable and answerable out of band.
9. Route sub-tasks to cheaper models, and account for fallback calls correctly.
10. Grade trajectories, and build datasets from real traces.
11. Broker third-party credentials so they never enter model context.

## 6. Practices that would be inappropriate for Neuron

| Practice | Who does it | Why not for Neuron |
| --- | --- | --- |
| A VM or container per session with shell access | Devin, Manus, Cursor, ChatGPT agent, Cowork, AgentCore | Neuron's security model bans shell and `eval` tools. Anthropic's own guidance is that this needs both filesystem and network isolation done well. No product requirement exists. |
| Browser and computer use | Same group | The largest prompt-injection surface in the field; vendors rely on trained refusal plus monitors, which Neuron's "the model is never a boundary" rule rejects. |
| Swarms of parallel agents | Cursor, Manus Wide Research | About 15× tokens in Anthropic's account; Neuron has a token ledger and no workload that needs breadth. |
| Peer agents that share write access | (Tried and abandoned by Cursor; argued against by Cognition) | The published evidence is against it. |
| Removing or adding tools mid-run | (Manus advises against) | Breaks cache and confuses the model. If Neuron adds dynamic tools, load between runs or use deferred definitions. |
| Explicit workflow graphs for everything | Microsoft workflows, ADK workflow agents | Neuron's ADRs keep the graph trivial. Workflows fit fixed business processes, which Neuron does not have. |
| Heuristic safety monitors as the main control | ChatGPT agent | Useful as an extra layer only. Neuron's deterministic gates are stronger for its tool set. |
| Directory-level agent identity and registry | Microsoft Entra Agent ID, Agent 365 | Solves fleet governance across many agents. Neuron has one agent. Revisit if that changes. |
| Adopting a managed runtime wholesale | AgentCore, Managed Agents, LangSmith Deployment | Would replace the parts of Neuron that are its strength (authorisation, accounting). Worth borrowing designs from, and worth re-evaluating Agent Server specifically for background runs (see improvement 1). |
| Multi-day autonomous runs | Cursor, Devin | No use case. Minutes-long background runs cover deep research. |

## 7. The 15 most valuable architectural improvements

Complexity is relative to Neuron's code base: **S** about a week, **M** two to four weeks, **L** more than a month. These are my estimates, not measured. Section 8 gives the order.

### 1. Durable runs with an append-only event log

- **Why it matters.** A run currently exists only as a task in one API process. A deploy, crash or dropped connection loses it.
- **Evidence.** Anthropic's brain/hands/session split with the session as an event log [V]. LangSmith Agent Server background runs on a queue with runs stored in Postgres [V]. Gemini `background: true` [V]. AgentCore treats session compute as disposable and state as external [V].
- **Benefits.** Runs survive restarts. Unlocks resumable streams, durable approvals, long research tasks and horizontal scaling.
- **Complexity.** L.
- **Dependencies.** A runs table (improvement 3). Neuron already has Procrastinate for ingestion, so no new queue technology is needed, but using it for agent runs requires an ADR.
- **Risks.** Re-executing a step after a crash repeats side effects. LangGraph's own docs say resumed nodes re-run and side effects must be idempotent [V]. Neuron's mutating tools (`remember`, `forget`, MCP) need idempotency keys first.

### 2. Resumable streams

- **Why it matters.** A client that loses its connection today loses the answer.
- **Evidence.** Gemini Interactions lets a client reconnect to a dropped stream [V]. Managed Agents exposes `getEvents` over the session log [S].
- **Benefits.** Reliable mobile and flaky-network use; multiple viewers of one run.
- **Complexity.** M, once 1 exists. The stream becomes a read of the event log from an offset.
- **Dependencies.** 1.
- **Risks.** The leak guard and answer-token extractor currently run inline in the stream; they must run before events are persisted, or filtered content would be stored.

### 3. First-class thread and run tables

- **Why it matters.** Listing, searching, retaining and deleting conversations currently means reading checkpoint data.
- **Evidence.** Agent Server's assistants/threads/runs resources in Postgres [V]. ADK's Session and Events model [V]. AgentCore's event log per actor and session [S].
- **Benefits.** Cheap listing and retention, clear ownership, a place for run status and cost.
- **Complexity.** M.
- **Dependencies.** None. Do this before 1.
- **Risks.** Two sources of truth (tables and checkpoints) drifting. Decide which is authoritative and write the other in the same transaction.

### 4. Context management that preserves findings

- **Why it matters.** Neuron drops tool results after each run, so a follow-up question cannot use what the previous turn retrieved.
- **Evidence.** Anthropic context editing keeps the record of a call while dropping re-fetchable output [V]. ADK sliding-window compaction [V]. Codex compaction endpoint [S]. Deep Agents summarisation middleware [V]. Manus: prefer reversible reduction (a pointer to a file) over lossy compression [V].
- **Benefits.** Better multi-turn answers, fewer repeated searches, lower cost.
- **Complexity.** M. `create_agent` middleware already supports this shape.
- **Dependencies.** A decision on what a "reference" to a past result is (for knowledge results, the citation ids already exist).
- **Risks.** Summaries of untrusted content carry the injection forward. Taint must survive compaction.

### 5. Model-decided retrieval in place of the forced first search

- **Why it matters.** Every run by a caller with the search scope pays for a search, including greetings.
- **Evidence.** Anthropic's context-engineering guidance favours loading information just in time through tools [V]. No product studied forces retrieval on every turn [I, from absence].
- **Benefits.** Direct token and latency savings on non-knowledge turns.
- **Complexity.** S.
- **Dependencies.** An eval that measures whether the model still searches when it should. The existing harness can host it.
- **Risks.** Answer quality may fall on weaker models that under-call tools. Keep the forced mode behind a setting until the eval says otherwise.

### 6. A plan tool, not a planner

- **Why it matters.** Multi-step requests have no visible or persistent plan, so progress cannot be shown, resumed or evaluated.
- **Evidence.** Deep Agents `write_todos` [V]. Manus recitation [V]. Gemini Deep Research plan review [S]. Cursor's finding that prompts mattered more than coordination machinery [S].
- **Benefits.** Better long-task coherence; a natural progress display; a checkpoint for approval before expensive work.
- **Complexity.** S. One tool and one state field.
- **Dependencies.** State change needs the `add-graph-node` checklist.
- **Risks.** Extra tokens on simple requests. The tool should be optional for the model.

### 7. Tool authorisation as policy data

- **Why it matters.** Rules about which principal may call which tool with which arguments are spread across the registry, middleware and `security/`.
- **Evidence.** AgentCore Policy evaluates Cedar rules on every tool call at the Gateway [V]. Claude Code permission rules and hooks [V]. Codex separates sandbox from approval policy [V].
- **Benefits.** One auditable place for rules; argument-level conditions; per-tenant differences without code changes.
- **Complexity.** M.
- **Dependencies.** A decision on rule format. A small typed rule table is enough; adopting Cedar is a new dependency to justify.
- **Risks.** A policy engine that fails open. Default must be deny, with tests proving it.

### 8. Durable, out-of-band approvals

- **Why it matters.** An approval can only be answered while the originating run is alive.
- **Evidence.** Microsoft workflows pause and resume from a checkpoint after a human decision [V]. ADK confirmation with resume by invocation id [V]. OpenAI runner pauses for approval [V].
- **Benefits.** Approvals by a second person, later, from another client; an audit record per decision.
- **Complexity.** M.
- **Dependencies.** 1 and 3.
- **Risks.** Stale approvals: the world changed between request and decision. Approvals need expiry and must bind to the exact arguments.

### 9. Per-task model routing, with correct fallback accounting

- **Why it matters.** One model does everything. An ordered fallback list exists (`APP_FALLBACK_MODELS`), but it is one list for the whole deployment, and metrics label a call served by a fallback with the primary model's name.
- **Evidence.** Anthropic's research system used a stronger lead and cheaper sub-agents [S]. Cursor found different models suited different roles [S]. Perplexity builds on routing [V].
- **Benefits.** Lower cost for summarisation, titles and classification; cost and quality figures that name the model that actually served the call.
- **Complexity.** M. Requires splitting `models/factory.py`, which the assessment already flags.
- **Dependencies.** The token ledger must account per model.
- **Risks.** Behaviour differs across models, so every eval must run per route. Fallback to a weaker model must not weaken tool gating (it will not, since gating is in code).

### 10. One entry point, one set of guarantees

- **Why it matters.** The Agent Server path runs the same graph without budgets, leases, rate limits, memory or knowledge.
- **Evidence.** No platform studied offers a weaker second path; AgentCore and Managed Agents put every call through the same policy point [V/I].
- **Benefits.** Removes the easiest way around Neuron's controls.
- **Complexity.** S to remove the path; L to bring it to parity.
- **Dependencies.** A product decision. If background runs (1) are built on Agent Server, parity becomes the route.
- **Risks.** Losing LangGraph Studio compatibility if the path is removed.

### 11. Trajectory evaluation fed by production traces

- **Why it matters.** Current evals grade answers. They do not grade which tools were called, in what order, or at what cost.
- **Evidence.** OpenAI trace grading [V]. ADK trajectory metrics [S]. AgentCore online evaluations [S].
- **Benefits.** Catches regressions like "stopped searching" or "searched five times" that answer grading misses. Needed to make improvements 4, 5 and 9 safely.
- **Complexity.** M.
- **Dependencies.** Traces already exist through OpenTelemetry. Needs a redaction step before traces become datasets.
- **Risks.** Storing user content in eval sets conflicts with retention rules.

### 12. Memory with extraction, provenance and expiry

- **Why it matters.** Memory holds only what the model chose to save, with no source or lifetime.
- **Evidence.** AgentCore long-term memory extracted asynchronously from an event log [S]. ADK Memory distinct from session state [V]. Anthropic's file-based memory tool [V].
- **Benefits.** Personalisation without bloating context; user trust through review and deletion.
- **Complexity.** M.
- **Dependencies.** 3 (events to extract from). The worker already exists.
- **Risks.** Memory poisoning from tainted runs. Extraction from tainted turns should be blocked or flagged.

### 13. Credential brokering for user-authorised tools

- **Why it matters.** MCP tools that act for a user need that user's token for the remote system. There is no place for it today.
- **Evidence.** AgentCore Identity token vault [S]. Managed Agents keeps credentials out of the sandbox [S]. Entra Agent ID [V].
- **Benefits.** Per-user MCP access without secrets in prompts, state or logs.
- **Complexity.** L.
- **Dependencies.** A concrete MCP integration that needs it. Do not build ahead of one.
- **Risks.** A new store of high-value secrets.

### 14. A context-isolated, read-only sub-agent exposed as a tool

- **Why it matters.** Long research inside one context crowds out the conversation.
- **Evidence.** Claude sub-agents return summaries [V]. Deep Agents `task` tool [V]. Cognition's accepted pattern: sub-agents read, one agent writes [V].
- **Benefits.** Cleaner main context; parallel searches.
- **Complexity.** M.
- **Dependencies.** 1, 4, 11, and a new ADR (the current ADRs forbid sub-graphs and multi-agent).
- **Risks.** Cost multiplies; the sub-agent loses context (Cognition's objection). Start with one sub-agent, read-only, behind an eval that shows a gain.

### 15. Prove one hosted deployment under realistic load

- **Why it matters.** Every claim about Neuron's reliability is from a local stack with eight simulated users.
- **Evidence.** Each organisation studied learned its architecture from operation; Anthropic, Cursor and Manus all describe redesigns driven by production behaviour [V/S].
- **Benefits.** Real numbers for pool size, lease behaviour and stream handling. It will re-order this list.
- **Complexity.** M.
- **Dependencies.** None.
- **Risks.** Cost, and the temptation to fix findings ad hoc instead of through this sequence.

## 8. Recommended implementation sequence

| Phase | Improvements | Reason for position |
| --- | --- | --- |
| A — Foundations | 15, 10, 3 | Get real evidence, close the weak path, and create the tables everything else needs. |
| B — Cheap wins | 5, 6, 11 | Small changes; 11 provides the measurement that later phases depend on. |
| C — Context and cost | 4, 9 | Both change model behaviour and need 11 in place. |
| D — Durability | 1, 2, 8 | The largest change. Needs 3, and idempotent mutating tools. |
| E — Governance | 7, 12 | Independent of D; scheduled after it to limit concurrent change in security-critical code. |
| F — Only on demand | 13, 14 | Build when a named product requirement and an ADR exist. |

Phases A and B can start now. Phase D is the one that changes what Neuron is; it should not start before phase A's deployment has produced data.

## 9. Sources

Pages are listed as surfaced by search. Those marked † are third-party and were used only for claims labelled [S].

**Anthropic**
- [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk.md)
- [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Scaling Managed Agents: decoupling the brain from the hands](https://anthropic.com/engineering/managed-agents)
- [Claude Code sandboxing (engineering)](https://anthropic.com/engineering/claude-code-sandboxing) and [docs](https://code.claude.com/docs/en/sandboxing)
- [Checkpointing](https://code.claude.com/docs/en/checkpointing.md), [features overview](https://code.claude.com/docs/en/features-overview.md)
- [Manage tool context](https://platform.claude.com/docs/en/agents-and-tools/tool-use/manage-tool-context), [context management announcement](https://www.anthropic.com/news/context-management)
- [Claude Cowork architecture overview](https://support.claude.com/en/articles/14479288-claude-cowork-architecture-overview)
- † [Securing Claude Cowork](https://harmonic.security/resources/securing-claude-cowork-a-security-practitioners-guide)

**OpenAI**
- [Agents SDK (Python)](https://openai.github.io/openai-agents-python/), [Agents guide](https://developers.openai.com/api/docs/guides/agents.md)
- [Unrolling the Codex agent loop](https://openai.com/index/unrolling-the-codex-agent-loop)
- [Codex agent approvals and security](https://developers.openai.com/codex/agent-approvals-security), [sandboxing](https://developers.openai.com/codex/concepts/sandboxing), [Running Codex safely](https://openai.com/index/running-codex-safely/)
- [Trace grading](https://developers.openai.com/api/docs/guides/trace-grading), [Introducing AgentKit](https://openai.com/blog/introducing-agentkit)
- † [The Register on ChatGPT agent](https://www.theregister.com/2025/07/18/openai_debuts_chatgpt_agent/), † [VentureBeat on its red-teaming](https://venturebeat.com/security/openais-red-team-plan-make-chatgpt-agent-an-ai-fortress/), † [Adversa analysis](https://airq.adversa.ai/agent/chatgpt-agent)

**Google**
- [ADK overview](https://adk.dev/get-started/about/), [sessions](https://adk.dev/sessions/), [context compaction](https://adk.dev/context/compaction/), [resume](https://adk.dev/runtime/resume/), [tool confirmation](https://adk.dev/tools-custom/confirmation/)
- [Architecting an efficient context-aware multi-agent framework](https://developers.googleblog.com/architecting-efficient-context-aware-multi-agent-framework-for-production/)
- [Interactions API background execution](https://ai.google.dev/gemini-api/docs/background-execution)
- [Deep Research Max announcement](https://blog.google/innovation-and-ai/models-and-research/gemini-models/next-generation-gemini-deep-research/)
- † [Deep Research with the Gemini API walkthrough](https://www.philschmid.de/deep-research-update)

**Microsoft**
- [Agent Framework overview](https://learn.microsoft.com/en-us/agent-framework/overview/)
- [Entra Agent ID: what's new](https://learn.microsoft.com/en-us/entra/agent-id/whats-new-agent-id), [registry convergence](https://learn.microsoft.com/en-us/entra/agent-id/agent-registry-convergence), [Conditional Access for agent identities](https://learn.microsoft.com/en-us/entra/identity/conditional-access/howto-target-agent-identities)
- † [Visualising and checkpointing workflows](https://ravichaganti.com/blog/visualizing-and-checkpointing-workflows-in-microsoft-agent-framework/)

**LangChain**
- [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview.md), [customisation](https://docs.langchain.com/oss/python/deepagents/customization)
- [LangGraph durable execution](https://docs.langchain.com/oss/python/langgraph/durable-execution), [checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)
- [Agent Server](https://docs.langchain.com/langsmith/agent-server.md), [double texting](https://docs.langchain.com/langsmith/double-texting.md), [cron jobs](https://docs.langchain.com/langsmith/cron-jobs.md), [scaling](https://docs.langchain.com/langsmith/agent-server-scale)

**Cognition**
- [Don't Build Multi-Agents](https://cognition.ai/blog/dont-build-multi-agents), [Multi-Agents: What's Actually Working](https://cognition.ai/blog/multi-agents-working)
- [Advanced capabilities (managed Devins)](https://docs.devin.ai/work-with-devin/advanced-capabilities), [creating playbooks](https://docs.devin.ai/product-guides/creating-playbooks.md)
- [Closing the agent loop](https://cognition.ai/blog/closing-the-agent-loop-devin-autofixes-review-comments), [Verifying agentic development at scale](https://cognition.ai/blog/testing-development)

**Cursor**
- [Scaling long-running autonomous coding](https://cursor.com/blog/scaling-agents), [Towards self-driving codebases](https://cursor.com/blog/self-driving-codebases)
- [Cloud agent security overview](https://cursor.com/docs/cloud-agent/security), [secrets and network](https://cursor.com/docs/cloud-agent/security-network)

**Perplexity**
- [Introducing Perplexity Deep Research](https://perplexity.ai/hub/blog/introducing-perplexity-deep-research), [Introducing Perplexity Computer](https://perplexity.ai/hub/blog/introducing-perplexity-computer)
- † [Techzine on Perplexity Computer](https://www.techzine.eu/news/infrastructure/139169/perplexity-computer-assigns-tasks-to-ai-agents)

**Manus**
- [Context Engineering for AI Agents: Lessons from Building Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus)
- [Introducing Wide Research](https://manus.im/blog/introducing-wide-research)

**Amazon**
- [How Bedrock Agents works](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-how.html)
- [AgentCore overview](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html), [runtime sessions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html), [lifecycle settings](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html)
- [AgentCore Policy and Evaluations announcement](https://aws.amazon.com/about-aws/whats-new/2025/12/amazon-bedrock-agentcore-policy-evaluations-preview)
- † [AgentCore lock-in analysis](https://3h4x.github.io/tech/2026/06/13/bedrock-agentcore-lock-in)
