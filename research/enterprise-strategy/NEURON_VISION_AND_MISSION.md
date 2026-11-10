# Neuron: Vision and Mission

| | |
| --- | --- |
| Date | 2026-11-10 |
| Status | Research proposal. Nothing here is decided until an ADR records it. |
| Package | Document 1 of 14 in `research/enterprise-strategy/` |
| Read next | `COMPETITIVE_POSITIONING.md` for why the vision is narrowed, `NEURON_18_MONTH_STRATEGIC_ROADMAP.md` for the plan |

## How this package was produced

- **Neuron facts** come from `NEURON_CURRENT_ARCHITECTURE_ASSESSMENT.md` (a static read of `main` at `fa6f6cd`, v1.1.0) and spot checks of the repository made for this package. No test, load run or deployment was executed.
- **Prior research used:** `NEURON_CURRENT_ARCHITECTURE_ASSESSMENT.md` and `NEURON_GLOBAL_AGENT_ARCHITECTURE_RESEARCH.md`. The brief also refers to an open-source ecosystem study, a commercial product intelligence report and an "advanced agent architecture patterns" report. **None of those is in this workspace.** Their ground is covered again here, more thinly than a dedicated study would.
- **Market facts** come from 32 web searches run on 2026-11-10. I read search excerpts, not whole pages. Many results were trade press or vendor marketing.
- **Evidence labels**, used in every document:
  - **[V]** the vendor's or project's own page appeared in the results.
  - **[S]** secondary source only (press, analyst, competitor blog).
  - **[K]** my own background knowledge, not re-checked in this session.
  - **[I]** my inference.
- **Not verifiable from public sources:** the internal design of every proprietary product named here. Statements about how those products work describe documented behaviour, not implementation.
- Effort, complexity and score figures are my estimates. None is measured.

## 1. The stated vision

> Neuron becomes a domain-agnostic enterprise agentic integration platform: existing enterprise applications, whatever their industry, stack or age, gain agentic capability through secure integration, without being replaced.

The ten principles in the brief are sound and are kept: integrate rather than replace, reuse existing capability, stay domain-independent, preserve the application's own authorization, keep humans in control of consequential operations, and make every action observable and auditable.

## 2. What the research says about that vision

Three findings change how the vision should be pursued.

**The vision as worded is not differentiated.** At least ten funded vendors make the same claim today: MuleSoft Agent Fabric, Workato Enterprise MCP, Boomi Agent Control Plane, Microsoft Foundry and Copilot Studio, Amazon Bedrock AgentCore Gateway, ServiceNow Action Fabric, IBM watsonx Orchestrate, Google's Gemini Enterprise Agent Platform, Glean and Kong. Several advertise connector counts above a thousand. Details are in `ENTERPRISE_AI_MARKET_AND_PRODUCT_RESEARCH.md`.

**Neuron is far from the starting line those vendors stand on.** Neuron today is a single-agent chat service with private document retrieval. It has no organisation or tenant concept in code, no connector framework, no per-user credentials for external systems, no durable runs, and it has never been deployed. Its real strength is narrow and unusual: authorization, tool gating, taint tracking, accounting and failure handling that are enforced in code and heavily tested.

**The gap the large vendors leave is real.** Each application vendor's agents work best inside that vendor's suite. The integration vendors sell hosted, proprietary control planes priced for large enterprises. Custom-built and legacy line-of-business applications, organisations that must self-host, and software vendors who want to add agent capability to their own product are served poorly. [I]

## 3. Recommended vision

> **Neuron is the open-source, self-hostable agent layer for the applications the big platforms do not cover.** An organisation points Neuron at an application it already runs, and its users get an agent that works inside that application's existing permissions, asks before consequential actions, and leaves a complete audit record.

This keeps the domain-agnostic ambition and narrows where Neuron fights:

| The broad vision says | The recommended vision says |
| --- | --- |
| Any enterprise application | First, applications with an HTTP API or an MCP server, especially custom and line-of-business ones |
| Universal integration platform | An agent runtime with an application onboarding pipeline. Connectors are consumed, not built |
| Compete with enterprise platforms | Complement them. Be callable from them through MCP |
| Every deployment model | Self-hosted and customer-cloud first. Hosted SaaS later |
| Autonomous cross-application workflows | Human-supervised actions first. Workflows after approvals are durable |

## 4. Mission

Make an unfamiliar application agent-capable in days, by configuration and review rather than by writing agent code, without the agent ever holding more access than the person it works for.

## 5. Product principles

These are testable rules. The roadmap's acceptance criteria refer to them.

1. **The user's permissions are the ceiling.** Calls into an application carry the requesting user's own delegated credential wherever the application supports it. A shared service account is a last resort and is restricted and flagged.
2. **The model is never a security boundary.** Every permission, approval and data-flow rule is enforced in code and expressed as data. This is Neuron's existing rule, extended.
3. **No domain logic in the core.** Everything specific to an application or an industry lives in versioned configuration: an application manifest, a domain pack, agent definitions and policies.
4. **Concepts keep their owner.** An entity always belongs to the application that defines it. `crm.Customer` and `his.Patient` are never merged by inference. Links between applications are declared by a person.
5. **Use the application's own process where one exists.** If the HR system already routes leave requests to a manager, Neuron submits the request and stops. It does not rebuild the approval chain.
6. **Deterministic where the process is fixed, agentic where judgement is needed.** Reconciliation rules, thresholds and routing are code or policy. Interpretation, investigation and drafting are the model's job.
7. **Consume, do not rebuild.** Identity providers, connector catalogues, secrets stores, gateways and observability backends are integrated.
8. **Every action is attributable.** One record per action names the user, the agent version, the application, the capability, the policy decision, the approval and the result, without storing sensitive payloads by default.
9. **Evidence before claims.** A capability counts as delivered when it has run in a hosted environment with a real model and the result is recorded.

## 6. What success looks like

| Horizon | Evidence of success |
| --- | --- |
| 6 months | One hosted deployment with measured load. Organisation model, policy as data and the audit ledger in place. A first application importing through the pipeline in a test environment. |
| 12 months | Two applications from different domains (a CRM and an HR system) onboarded with no change to the core between them. Users act under their own credentials. One design-partner organisation using it for real work. |
| 18 months | A cross-application workflow with durable approvals in use. A person outside the project onboards a fourth application from the documentation alone. |
| 3 years | Known as the open-source default for adding governed agents to custom and self-hosted applications. Callable from the major agent platforms through MCP. A paying user base that funds maintenance. |

## 7. What the vision does not include

Stated here so later documents can refer to it:

- A connector marketplace that competes on count.
- A visual workflow builder.
- A control tower that discovers and governs other vendors' agents.
- Robotic process automation or browser automation built in-house.
- Industry-specific agents shipped as product.
- Model hosting or fine-tuning.

`BUILD_VS_INTEGRATE_ANALYSIS.md` gives the reasoning for each.

## 8. The main risk

The recommended niche is defensible only if onboarding an application is clearly faster and safer with Neuron than with a general agent SDK plus hand-written tools. If the onboarding pipeline (`DOMAIN_AGNOSTIC_INTEGRATION_ARCHITECTURE.md`, sections 5 and 6) does not deliver that, Neuron is one more agent framework with good security defaults. The first three use cases exist to test exactly this.
