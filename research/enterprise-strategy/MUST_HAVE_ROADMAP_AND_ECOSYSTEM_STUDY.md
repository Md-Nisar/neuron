# Neuron: Must-Have Roadmap and Open-Source Ecosystem Study

| | |
| --- | --- |
| Date | 2026-11-12 |
| Status | Research proposal. Nothing here is decided until an ADR records it. |
| Package | Document 15 in `research/enterprise-strategy/`. It fills the open-source ecosystem gap that document 1 names, and it proposes a different order for the first 90 days of `NEURON_18_MONTH_STRATEGIC_ROADMAP.md` (document 11). It does not replace that roadmap. |
| Audience | The owner, and the model that will implement from this. |

Evidence labels used on every claim:

- **[R]** checked in this repository today (file named where useful).
- **[S]** from web search excerpts on 2026-11-12. I did not open the pages, and most are trade press or vendor blogs.
- **[I]** my inference or recommendation.
- **[U]** unknown; I could not establish it.

## 1. Summary

1. **Neuron does not need more features yet. It needs proof.** Three kinds: it runs somewhere real, it does useful work inside one real application, and it can show a buyer the result. [I]
2. **The existing 18-month roadmap has the right content in the wrong order.** Its first application arrives at about month 9, after six to eight months of foundations. The roadmap's own main risk (document 1, section 8) is that onboarding an application may not be faster with Neuron. That can be tested in about six weeks with what exists today, and it should be tested first. [I]
3. **Proposed product sentence:** Neuron puts a governed agent inside an application you already run, and produces the evidence your security team and your budget holder each ask for. [I]
4. **Several things the field now asks for are already in Neuron and are undersold:** approval before a run that has read untrusted data can send data out, pinned MCP tool definitions, no stdio MCP, a coverage table for the OWASP agentic risks, hash-locked dependencies. Section 4 lists them. [R]
5. **The 90-day must-haves** (section 6), in priority order: a hosted deployment, a six-week application spike, thread and run tables, an audit ledger, and calls made with the user's own delegated credential.
6. **Do not build** a gateway, a connector catalogue, a visual builder, multi-agent orchestration, a code sandbox or a policy language of your own (section 7). Open projects cover each, or no evidence supports it yet.

## 2. The problems worth solving

The request was for a product that solves problems, not one with many features. These are the three enterprise problems the evidence supports, and each maps to something Neuron can own.

| Enterprise problem | Evidence | What Neuron should offer | State today |
| --- | --- | --- | --- |
| Pilots stop because risk and security teams will not sign off | Gartner forecasts that over 40% of agentic projects will be cancelled by the end of 2027, citing cost, unclear value and inadequate risk controls. A Deloitte survey of 3,235 leaders found 21% have governance mature enough for agents. [S] | Controls enforced in code, plus a security evidence pack a reviewer can read | Strong controls [R]; no external penetration test, no hosted run [R] |
| The assistant sits outside the work | The MIT NANDA report (July 2025, preliminary, 52 interviews and 153 surveys) names poor workflow integration and tools that do not learn as the main causes of pilots with no measurable return. [S] | An agent that acts inside the user's existing application, under that user's permissions | Not built: no application onboarding, no per-user credentials, no embedded surface [R] |
| Nobody can show the value | Same sources: "unclear business value" (Gartner); no measurable effect on revenue or cost in 95% of pilots (NANDA; the figure is widely misquoted). [S] | A value report per application: tasks completed, time and cost per completed task, reliability on repeated runs | Token accounting and evals exist [R]; no outcome reporting |

Where returns are most often reported: customer support, IT service desk and document-heavy back-office work. The figures in circulation (for example "171% average ROI") have changing attributions and I could not trace them to a primary source. [S][U]

## 3. Open-source ecosystem study

Decision words: **Adopt** (implement or depend on it), **Work with** (keep compatible, stay outside the core), **Learn from** (take the idea), **Wait**, **Avoid**.

### 3.1 Protocols and standards

| Item | State in November 2026 | Decision for Neuron |
| --- | --- | --- |
| MCP specification 2026-07-28 | Latest revision found. Stateless core: no initialisation handshake, no session header. Tasks moved to an extension with polling. Roots, Sampling and Logging reported as deprecated. A policy of at least 12 months between deprecation and removal. [S] | **Adopt.** Neuron pins `mcp` 2.3.0 [R]. Whether that client behaves correctly against a stateless 2026-07-28 server is [U]. Test it in the first 30 days. |
| MCP Enterprise-Managed Authorization (also called ID-JAG and Cross App Access) | One pattern under three names. The user's single sign-on token is exchanged at the identity provider (RFC 8693) for an assertion, which is redeemed for an access token restricted to one MCP server. No refresh token is issued. Reported stable as an MCP extension in June 2026; the IETF draft is still a draft. Supported by Okta, Auth0, Descope and agentgateway. [S] | **Adopt as the shape of the credential broker (F2.2).** It is the standard form of the principle "the user's permissions are the ceiling". Keycloak support for the assertion step is [U]; plain token exchange is the fallback. |
| Agent Skills (`SKILL.md`) | An open format for packaged instructions loaded on demand. About 40 adopting tools by mid-2026. Reported as donated to the Agentic AI Foundation; sources disagree on the date. [S] | **Adopt as the format for domain packs (F3.1)**, instructions only. A skill that runs scripts is code execution, which Neuron forbids [R]. Packs are installed by an operator and pinned by hash, like MCP tools. [I] |
| AG-UI | An open event protocol between an agent and a user interface, from the CopilotKit team. Microsoft Agent Framework documents support. Adoption figures [U]. [S] | **Work with.** Evaluate an adapter from Neuron's event stream in the embedded-surface spike. Do not replace the existing stream. |
| A2A 1.0 | Stable since March 2026 under the Linux Foundation, over 150 supporting organisations. A June 2026 analysis says it lacks human escalation and audit replay at protocol level. [S] | **Wait.** Neuron has one agent [R]. Keep the roadmap's trigger: a partner whose agents must delegate to Neuron. |
| OpenTelemetry GenAI conventions | Still marked Development, including the agent spans. Moved to their own repository in June 2026. One blog claims they are stable; the official pages contradict it. [S] | **Work with.** Neuron already exports OTLP and keeps span names in one file [R]. Do not chase a moving convention. |

### 3.2 Components

| Layer | Projects | Finding | Decision |
| --- | --- | --- | --- |
| MCP and agent gateways | agentgateway (Apache 2.0, hosted by the Agentic AI Foundation, covers MCP, A2A and model traffic), IBM ContextForge (Apache 2.0), Obot (MIT; Okta and Entra sign-on are in its paid edition), Docker MCP Gateway (MIT, local use) [S] | One independent test found agentgateway served every tool to anyone who could reach the port by default, while ContextForge and Docker's gateway refused requests without a token. [S] | **Work with, never build.** Neuron stays a client of gateways. If one is recommended in the documentation, state that authentication must be switched on. |
| OpenAPI to MCP | FastMCP `from_openapi` with route filtering; agentgateway can present REST APIs as tools [S] | FastMCP's own documentation says curated tools work much better than automatic conversion of every endpoint. [S] | **Use for the spike** as a separate service. This finding supports the roadmap's curated capability catalogue (F2.3) over a bulk import. |
| Agent harness | LangChain `create_agent` (in use [R]); Deep Agents, which adds a virtual filesystem, sub-agents, summarisation and skills on top [S] | The filesystem layer in Deep Agents cannot be removed. [S] | **Learn from.** Take summarisation, which is a LangChain middleware [S]. Do not adopt the whole harness: Neuron's control flow is a carefully ordered middleware stack [R]. |
| Durable execution | LangGraph Postgres checkpointer and the `procrastinate` Postgres queue (both in use [R]); DBOS Transact (MIT, a library that stores workflow state in Postgres); Temporal (needs its own cluster) [S] | Neuron already has a Postgres queue and checkpoints. | **Build durable runs on what exists.** No new engine. Reconsider DBOS only if hand-written recovery grows past the run table, the event log and one worker. [I] |
| Policy | Cedar, OPA (Rego), OpenFGA (relationships); Microsoft Agent Governance Toolkit (MIT, April 2026, accepts YAML, Rego and Cedar) [S] | A common split: relationship checks for document access, a policy language for rules on tool arguments. [S] | **Do not invent a policy language (F1.3).** Run a two-day spike on Cedar from Python before choosing. Maturity of the Python bindings is [U]. |
| Tracing and evaluation | Langfuse (MIT, owned by ClickHouse since January 2026, self-hostable), Arize Phoenix (Elastic License 2.0, not open source by the OSI definition), LangSmith (hosted, proprietary), DeepEval [S] | Neuron's hosted tracing option is LangSmith [R]. That sits badly with a self-hosting position. [I] | **Document Langfuse over OTLP as the self-hosted path.** Keep LangSmith optional. |
| Model gateways | LiteLLM | Compromised on PyPI twice in 2026 (March, through a compromised Trivy scanner in its build; October, through its release pipeline). [S] | **Avoid as a dependency.** Neuron does not use it [R] and talks to providers directly. Neuron does run Trivy in two workflows [R]; see section 9. |
| Self-hosted knowledge and chat platforms | Onyx (MIT core, 40+ connectors; permission sync and SSO are paid features), Dify, Open WebUI, LibreChat [S] | The crowded category is chat plus document search. The common open-core pattern puts sign-on, permission sync and audit in the paid edition. [S] | **Do not compete on connectors or document search.** Consider keeping every security control in the open core as a stated position (section 11). |

### 3.3 Security and regulation

| Topic | Finding | Consequence for Neuron |
| --- | --- | --- |
| Prompt injection | No filter is reliable: one study of 12 published defences reports human red-teamers bypassed all of them. The deployable approach is containment. Meta's "Rule of Two" (October 2025): in one session an agent should hold at most two of untrusted input, access to sensitive data, and the ability to change state or communicate out. The stronger research designs (CaMeL, dual model) are in no mainstream harness. [S] | Neuron already applies this rule in code: once a run has read a tool result that taints it, tools that send data out need human approval (`ToolSpec.taints_run`, `models/factory.py`, `test_tainted_egress.py`) [R]. Say so plainly in the product material. |
| MCP supply chain | Over 40 CVEs against MCP implementations in 2026 by one count; tool poisoning and "rug pull" changes to approved tools; a command-execution flaw in stdio handling affecting about 200,000 instances. [S] | Neuron refuses stdio and pins a SHA-256 of each tool's name, description and schema (ADR 0009) [R]. This is ahead of common practice. |
| OWASP Top 10 for Agentic Applications (December 2025) | Ten risks, ASI01 Agent Goal Hijack to ASI10 Rogue Agents. [S] | `docs/security/threat-model.md` already maps all ten, with five marked Partial: ASI01, ASI03, ASI04, ASI08, ASI10 [R]. Each Partial row needs a named closing item (section 9). |
| Agent identity | NIST opened an AI Agent Standards Initiative in February 2026. Its concept paper favours adapting OAuth, OpenID Connect and SPIFFE over new mechanisms, and asks about auditing and non-repudiation. No finished standard. [S] | Supports delegated credentials and the audit ledger as early work. |
| EU AI Act | The 2026 omnibus moved standalone high-risk obligations from 2 August 2026 to 2 December 2027, and product-embedded ones to 2 August 2028. Some August 2026 obligations remain; which ones is [U] from these results. [S] | No deadline forces Neuron's order of work. Audit records and human oversight are still what a deployer will be asked for. [I] |

## 4. What Neuron already has that the field is asking for

All [R]. These are assets to state in the README and the security pack, not work to do.

- Approval required for outbound tools after a run has read untrusted or private data.
- MCP over Streamable HTTP only; definitions pinned by hash; arguments checked against the pinned schema before the server is contacted; `mutating` as the default risk class.
- Exact-argument approvals that the model cannot edit, single use.
- Identity only from a verified token; the model never sees it; a per-tool scope for every tool.
- Citations and the `grounded` flag computed in code, not taken from the model.
- A mapped threat model for both OWASP lists, with tests named per row.
- OTLP export, dependency hashes in `uv.lock`, GitHub Actions pinned by commit, image provenance verified at deploy.

What is absent is equally clear from `NEURON_CURRENT_ARCHITECTURE_ASSESSMENT.md`: no production run, no organisation concept, no per-user credentials for external systems, no durable runs, no application onboarding. [R]

## 5. Where I disagree with the 18-month roadmap

1. **The first application comes too late.** Test the central claim in weeks 1 to 6 with a spike that changes no core code (M2 below). If it fails, six months of foundations would have been built for the wrong niche. [I]
2. **The embedded client is listed beyond 18 months.** The vision is an agent inside the application people already use, and poor workflow integration is the leading cause of failed pilots [S]. A thin embedded surface belongs in the first 90 days as a spike. [I]
3. **Policy as data should use an existing language.** The roadmap defers Cedar until customers ask. Choosing a home-grown format first means a migration later. Decide by spike now. [I]
4. **The credential broker should follow the published pattern** (token exchange, audience-restricted, no stored refresh token) from its first slice. [I]
5. **The self-hosted observability story is missing.** [I]
6. **Last week's two decisions are not placed.** The Data Gateway (PR #541) and charts (PR #542) come after delegated credentials, because answering questions over a user's data needs that user's access rights. [I]

Everything else in document 11 I would keep, including its rejections.

## 6. The must-have roadmap: next 90 days

Day 1 is the day the direction ADR is accepted. **Must** items are the plan; **Should** items go in only if the Must items in the same window are on track. If capacity allows five things only: M1, M2, M5, M6, M10.

### Days 1 to 30: prove it

| ID | Item | Priority | Why | Roadmap ID | Done when |
| --- | --- | --- | --- | --- | --- |
| M1 | One hosted deployment with a real model, the load baseline, a restore and a rollback | Must | Every figure so far is from a laptop [R] | F0.2 | A dated record in `docs/releases/` |
| M2 | Application spike (below) | Must | Tests the niche before building for it | new | A written result against the pass and fail lines |
| M3 | Direction ADR 0015, with the decisions in section 11 | Must | Nothing in this package is decided [R] | F0.1 | ADR accepted |
| M4 | Standards and supply-chain check: the MCP client against a stateless 2026-07-28 server; confirm no third-party scanner step can read a publishing credential | Should | Section 3.1 and the LiteLLM incidents | new | Findings added to the threat model |

**M2 in detail.** Take one open-source CRM from document 12 (their APIs are not yet verified [U]). Hand-pick 10 to 15 operations from its OpenAPI document and expose them through an OpenAPI-to-MCP bridge running as its own service. Register it in `APP_MCP_SERVERS` with pins; writes stay `mutating` and need approval [R]. The spike uses one shared credential, because per-user credentials do not exist yet, so it tests onboarding speed and task quality and not delegation. Measure: working hours to onboard; 20 scripted tasks, each run three times; failures by cause. Proposed lines [I]: **pass** at two working days or less to onboard and at least 16 of 20 tasks succeeding on all three runs; **fail** above one week or below 12 of 20. A fail means revisiting the niche before building the pipeline.

### Days 31 to 60: the foundations the spike will have exposed

| ID | Item | Priority | Why | Roadmap ID | Done when |
| --- | --- | --- | --- | --- | --- |
| M5 | Thread and run tables; idempotent, cancellable runs; one entry point | Must | Precondition for durable runs, approvals and audit [R: assessment P1] | F0.3, F0.5 | Existing suite passes on the new tables |
| M6 | Audit ledger, first version: one append-only record per action naming user, agent version, tool, decision, approval and result, with each record carrying a hash of the previous one | Must | What security reviewers and auditors ask for first [S]; the hash chain makes tampering detectable [I] | F1.4 | A test alters a row and verification fails |
| M7 | Context management: summarise when history is trimmed; keep tool findings across turns | Should | Multi-step application tasks lose their findings today [R: assessment 7.6] | F3.4 (part) | An eval with a 10-step task passes |
| M8 | Self-hosted trace and evaluation loop: OTLP to Langfuse documented; failed traces become regression cases; reliability reported on repeated runs | Should | Section 3.2; datasets from real failures are the common practice [S] | F3.5 (part) | A failed spike task is in the nightly eval |

### Days 61 to 90: identity and the user's surface

| ID | Item | Priority | Why | Roadmap ID | Done when |
| --- | --- | --- | --- | --- | --- |
| M9 | An organisation identifier on every row and in every query | Must | Cheap now, a rewrite later [I] | F1.1 (minimal) | A cross-organisation read test fails closed |
| M10 | Delegated credential, first slice: exchange the user's token for one restricted to a single MCP server; store no long-lived user credential | Must | Principle 1; section 3.1 | F2.2 (slice) | The spike CRM shows the acting user, not a service account, on a record it changed |
| M11 | Durable approvals and a resumable stream, on Postgres and the existing queue | Should | An approval must survive a restart and a closed browser tab [R: assessment 7.4] | F1.5 (slice) | Kill the API mid-run; the approval is still decidable |
| M12 | Embedded surface spike: a web component with token handoff; assess an AG-UI adapter | Should | Section 5, point 2 | new | The agent runs inside a page of the spike CRM |
| M13 | Value report, first version: per application, tasks attempted and completed, approvals, time and cost per completed task | Should | Section 2, third problem | F5.2 (part) | One page generated from the spike data |

## 7. After 90 days, and what not to build

**Next, in order** [I]: the application registry and curated capability catalogue in the core (only if M2 passed); the Data Gateway and charts; domain packs in the Agent Skills format; the policy language chosen by spike; approval tiers and an inbox; events and schedules; Neuron exposed as an MCP server (cheap, and it makes Neuron callable from the large platforms); the administration console.

| Do not build | Why | Revisit when |
| --- | --- | --- |
| A gateway | agentgateway and ContextForge exist under Apache 2.0 [S] | Never, on present evidence |
| A connector catalogue | Onyx and the integration vendors compete on count [S] | Never |
| A visual workflow builder | Dify and others own it [S]; it is outside the vision | Never |
| Multi-agent orchestration, A2A | One agent today [R]; no evidence it helps the three problems | A partner needs delegation |
| A code or shell sandbox | Conflicts with the no-execution rule [R] | A use case that cannot be met with tools |
| A policy language of Neuron's own | Section 3.2 | Never |
| The whole Deep Agents harness | Section 3.2 | A long-investigation eval shows a gain |

## 8. Architecture rules to hold

1. Postgres stays the only required stateful dependency until a measured limit says otherwise. [I]
2. Standards at the edges, Neuron's own contracts inside. MCP, AG-UI and A2A sit behind adapters, so a specification change touches one module.
3. Everything specific to an application is data with a version and a hash: tool definitions, packs, policies.
4. The model proposes; code decides. Taint follows the data and approvals follow the taint. [R, extended]
5. Never store a user's long-lived credential where an exchange is possible.
6. Each new subsystem is a package with an import-contract test, as `knowledge/` is today. [R]
7. A capability counts as released only after it has run hosted with a real model (principle 9 of document 1).
8. Reliability is measured as success on every one of several repeated runs, not on the best run. [S]

## 9. Security practices to add

- **An external penetration test** before any design partner uses it. It is already on the deferred list. [R]
- **A human-run injection exercise** on the spike application. Static benchmarks are weak evidence for these defences. [S]
- **A closing item for each Partial row** in the agentic risk table (ASI01, ASI03, ASI04, ASI08, ASI10). M10 addresses ASI03; M5 and M11 address ASI08.
- **A runtime kill switch** per application and per tool, usable without a redeploy. Monitoring and kill switches are the usual answer to ASI10. [S]
- **Build pipeline isolation.** The first LiteLLM compromise came through a scanner that could read a publishing token [S]. Confirm that no Trivy step in `image-publish.yml` or `deploy.yml` can. [U until checked]
- **An MCP server onboarding checklist:** owner, authentication on, pins recorded, risk class per tool, review date.

## 10. Risks

| Risk | Response |
| --- | --- |
| The spike fails | That is its purpose. Narrow the niche or change it before building the pipeline. |
| The candidate applications lack usable APIs or delegation | Record it as a finding; it measures how often a shared account will be needed. |
| Keycloak cannot issue the assertion the MCP extension expects | Use plain RFC 8693 exchange; keep the broker interface the same. |
| Ninety days of work again outruns verification | M1 comes first, and every "Done when" is a recorded run. |
| Standards move again | Rule 2 in section 8. |

## 11. Decisions needed from the owner

1. Accept the reordering: spike and hosted deployment first, foundations second.
2. Choose the spike application.
3. Decide whether every security control stays in the open core. I recommend yes: it is the clearest difference from the open-core products in section 3.2. [I]
4. Decide the self-hosted tracing recommendation (Langfuse or none).

## 12. Limits of this study

- 29 web searches in one day; excerpts only. Vendor and trade sources dominate. Dates and figures marked [S] should be checked against primary pages before they are quoted publicly.
- No code was run. The repository claims come from reading files and from the earlier assessment.
- Thresholds, priorities and the 90-day sizing are my estimates.
- I did not check the candidate applications, Keycloak's token-exchange features, or Cedar's Python support.

## 13. Sources

Specifications and standards: [MCP changelog 2026-07-28](https://modelcontextprotocol.io/specification/2026-07-28/changelog) · [MCP stateless revision summary](https://www.noze.it/en/insights/mcp-2026-07-28-stateless/) · [Descope on the July 2026 revision](https://www.descope.com/blog/post/july-2026-mcp-revision) · [WorkOS on ID-JAG](https://workos.com/blog/id-jag-cross-app-access) · [Descope: XAA, ID-JAG and EMA](https://www.descope.com/blog/post/xaa-vs-idjag-vs-ema) · [agentgateway ID-JAG support](https://aaif.io/blog/agentgateway-now-supports-id-jag-and-mcp-enterprise-managed-auth) · [A2A first-year release](https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year) · [AG-UI](https://copilotkit.ai/ag-ui) · [OpenTelemetry agent spans](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-agent-spans) · [GenAI conventions not yet stable](https://dev.to/azena-ai/opentelemetrys-genai-semantic-conventions-are-not-stable-yet-heres-what-actually-shipped-in-2026-3mke) · [Agent Skills donation report](https://fourweekmba.com/ai-anthropic-donates-agent-skills-after-nearly-280m-installs/) · [Agent Skills standard overview](https://codex.danielvaughan.com/2026/05/05/agent-skills-open-standard-portable-skills-codex-cli-cross-agent/)

Projects: [agentgateway at the Agentic AI Foundation](https://aaif.io/projects/agentgateway/) · [MCP gateway hands-on comparison](https://manveerc.substack.com/p/best-mcp-gateways) · [Obot gateway roundup](https://obot.ai/?p=3679) · [FastMCP OpenAPI integration](https://gofastmcp.com/integrations/openapi) · [Deep Agents harness](https://docs.langchain.com/oss/python/deepagents/harness) · [DBOS Transact for Python](https://github.com/DBOS-project/dbos-transact-py) · [Durable execution comparison](https://hackernoon.com/durable-execution-for-ai-agents-langgraph-dbos-inngest-and-temporal-compared) · [OpenFGA for agents](https://openfga.dev/docs/modeling/agents) · [Microsoft Agent Governance Toolkit](https://opensource.microsoft.com/blog/2026/04/02/introducing-the-agent-governance-toolkit/) · [ClickHouse acquires Langfuse](https://clickhouse.com/blog/clickhouse-acquires-langfuse-open-source-llm-observability) · [Open-source observability licences](https://hackernoon.com/two-acquisitions-deep-two-still-standing-whats-really-happening-to-open-source-llm-observability) · [Onyx connectors](https://docs.onyx.app/admins/connectors) · [Onyx comparison](https://onyx.app/insights/openwebui-vs-librechat-vs-onyx) · [Agent evaluation guide](https://mastra.ai/articles/ai-agent-evaluation)

Security and regulation: [Sophos on the lethal trifecta](https://www.sophos.com/en-us/blog/inside-the-lethal-trifecta-blast-radius-reduction-in-ai-agent-deployments) · [Filtering does not stop prompt injection](https://hackernoon.com/you-cannot-filter-your-way-out-of-prompt-injection) · [OWASP agentic Top 10, Giskard summary](https://www.giskard.ai/knowledge/owasp-top-10-for-agentic-application-2026) · [Cloud Security Alliance on MCP](https://labs.cloudsecurityalliance.org/research/csa-research-note-mcp-security-crisis/) · [MCP security incidents](https://upguard.com/blog/mcp-security-incidents) · [LiteLLM, March 2026](https://research.jfrog.com/post/litellm-compromised-teampcp/) · [LiteLLM, October 2026](https://www.helpnetsecurity.com/2026/10/22/litellm-compromised-supply-chain-attack-pypi-docker/) · [NIST AI Agent Standards Initiative](https://www.nist.gov/caisi/ai-agent-standards-initiative) · [EU AI Act omnibus, Gibson Dunn](https://www.gibsondunn.com/eu-ai-act-omnibus-agreement) · [EU AI Act omnibus, Council approval](https://www.scl.org/council-of-the-eu-approves-ai-omnibus-reforms/)

Market evidence: [Gartner forecast coverage](https://www.outlookbusiness.com/deeptech/artificial-intelligence/over-40-of-agentic-ai-projects-will-be-scrapped-by-2027-says-gartner) · [CIO on stalled agent projects](https://www.cio.com/article/4132031/why-most-agentic-ai-projects-stall-before-production.html) · [MIT NANDA report coverage](https://fortune.com/2025/08/19/shadow-ai-economy-mit-study-genai-divide-llm-chatbots/) · [NANDA report summary](https://www.aigl.blog/state-of-ai-in-business-2025/) · [Agent ROI figures and their attribution](https://www.beri.net/article/ai-agent-roi-reality-check-2026)
