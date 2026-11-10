# Build Versus Integrate Analysis

| | |
| --- | --- |
| Date | 2026-11-10 |
| Package | Document 10 of 14 |
| Evidence | Licence and status facts carry the labels from document 2: **[V]** project's own page, **[S]** secondary, **[K]** background knowledge not re-checked. **Every licence must be confirmed against the project's repository before adoption**; several here are [K] or [S]. No candidate was installed or tested. |

## 1. Decision rules

1. **Own what is the product.** If the capability is why someone would choose Neuron, build it.
2. **Integrate what is infrastructure.** If a mature component exists under a permissive licence and Neuron adds nothing to it, use it behind an interface.
3. **Prefer what is already in the stack.** Postgres, Keycloak, Procrastinate, OpenTelemetry, Docling and LangGraph are already dependencies. A new dependency must beat extending one of these.
4. **Never require a hosted service.** Self-hosting is the positioning.
5. **Licence filter.** Apache-2.0, MIT, BSD, MPL and PostgreSQL-style licences are acceptable as dependencies. Source-available licences (BSL, SSPL, Elastic, Sustainable Use, FSL) are not acceptable as required components of an Apache-2.0 product that software vendors may embed. They may be optional integrations the customer chooses.
6. **The repository's own rule applies:** a new dependency must be justified, on PyPI and at least 90 days old.

Verdicts used: **Adopt** (take as a dependency), **Integrate** (optional, behind an interface, customer's choice), **Extend** (grow what Neuron has), **Build**, **Inspiration** (learn from, do not depend on), **Reject**.

## 2. Capability by capability

### 2.1 API management and gateways

| Candidate | Licence and status | Verdict | Reason |
| --- | --- | --- | --- |
| Kong | Open-source gateway; MCP OAuth plugin is Enterprise-only [V] | Integrate | A customer who owns Kong can front applications with it. Neuron does not need it. |
| agentgateway | Apache-2.0, Linux Foundation [V] | Integrate; Inspiration | Possible optional egress gateway. Young project. |
| IBM ContextForge | Apache-2.0, no official support [V] | Inspiration | Federation ideas; unsupported. |
| Microsoft MCP Gateway | Reported MIT [S] | Inspiration | Kubernetes-oriented. |
| WSO2 API Manager | Open-source heritage [K] | Integrate | Customer's choice. |
| **Neuron's own executor** | n/a | **Build** | Neuron needs policy and credentials applied to *its own outbound calls*, which is a library concern, not a network appliance. The existing egress backend is the base. |

### 2.2 iPaaS and connectors

| Candidate | Licence and status | Verdict | Reason |
| --- | --- | --- | --- |
| Workato, MuleSoft, Boomi, Zapier, Make | Commercial | Integrate through MCP | They expose catalogues as MCP servers. |
| n8n | Sustainable Use License; embedding terms disputed in sources [S] | Reject as a component; customer may run it beside Neuron | Licence conflicts with rule 5. |
| Pipedream | Acquired by Workday [S] | Reject | Roadmap risk. |
| Nango | Source-available per its own description [V] | Inspiration; optional integration | Closest design reference for per-user OAuth handling. Licence fails rule 5 as a required part. |
| Composio, Arcade, Merge Agent Handler | Commercial, hosted | Integrate as optional credential and tool providers | Conflict with rule 4 if required. |
| Airbyte and similar data movers | Mixed licences [K] | Not needed | Neuron reads live, it does not replicate data. |
| **Connector catalogue of Neuron's own** | n/a | **Reject** | Document 4. |

### 2.3 Workflow orchestration and durable execution

This is the one decision with real alternatives.

| Candidate | Licence and status | For | Against |
| --- | --- | --- | --- |
| **Extend Procrastinate plus an event log** | MIT [K]; already pinned in `pyproject.toml` | No new dependency. Transactional with business data. The team knows it. | It is a job queue, not a workflow engine: step memoisation, resume and timers must be built. |
| **DBOS Transact** | MIT; a library that stores workflow state in the application's Postgres [V] | Durable steps and resume as a library, on the database Neuron already has. No server. | New dependency. Vendor-published performance claims only [V]. Overlaps with LangGraph checkpoints, so the boundary must be designed. |
| **LangGraph durable execution with the existing checkpointer** | MIT [K]; already a dependency | Already persists agent state; interrupts already power approvals. | Resumed nodes re-run, so side effects must be idempotent (prior research). No job distribution; needs a queue anyway. |
| **LangSmith Agent Server** | Commercial licence for self-hosted production use [K] | Background runs, threads, cron out of the box (prior research) | Fails rule 4 and 5 as a required part. The Agent Server path is the weaker entry point the assessment recommends removing. |
| **Temporal** | MIT server [V/S]; separate cluster to operate | Most mature; an official integration with a major agent SDK exists [S] | A second stateful system to run. Heavy for a single-host install. |
| **Restate** | Licence not confirmed here | Lightweight server | Unknown licence; another server. |
| **Camunda, UiPath Maestro, ServiceNow, Power Automate** | Commercial or mixed | Customers already own them | Integrate for long business processes; not a core dependency. |

**Recommendation.** Keep LangGraph checkpoints for agent state inside a run. Put runs on Postgres job tables with a run-event log, leases with heartbeat and fencing, and idempotency keys. Before writing the run engine, run a two-week spike comparing "extend Procrastinate" with "adopt DBOS Transact" on three tests: crash in the middle of a tool call, approval wait of a day, and 200 concurrent runs. Record the result in the run-engine ADR. Temporal is the fallback if a customer's scale later outgrows Postgres.

### 2.4 Identity

| Candidate | Licence and status | Verdict | Reason |
| --- | --- | --- | --- |
| Keycloak | Apache-2.0 [K]; already shipped with a custom theme | **Adopt (keep)** as the default broker | Brokers SAML and OIDC IdPs; supports token exchange [K]. |
| Microsoft Entra, Okta | Commercial | Integrate through OIDC | Customer IdPs. |
| WSO2 Identity Server | Open source [K]; documents agent identity for MCP [V] | Integrate; Inspiration | Alternative broker. |
| Own identity provider | n/a | Reject | Never build. |
| MCP enterprise-managed authorization | Official MCP extension, underlying grant is an IETF draft [S] | Design for; implement when two target IdPs support it | Standard still settling. |

### 2.5 Authorization

| Candidate | Licence and status | Verdict | Reason |
| --- | --- | --- | --- |
| Typed rule table in Postgres | n/a | **Build first** | Covers the first year's rules; testable; no dependency. |
| Cedar | Open source [K]; used by AgentCore Policy for tool calls [V] | **Adopt when customers must author rules** | Shape matches (principal, action, resource, conditions). Check the maturity of the Python binding before committing. |
| Open Policy Agent | Apache-2.0, CNCF graduated; maintainers moved to Apple, governance unchanged [S] | Integrate as an alternative decision point | General and proven; Rego is a learning cost; usually a sidecar. |
| Cerbos | Open-source core [S]; licence not confirmed | Inspiration | A separate service to run. |
| OpenFGA | Apache-2.0 [K], CNCF incubating [V] | Defer | Relationship-based sharing at scale is not yet needed; the grants table suffices. |

The decision *interface* (inputs and three outcomes) is Neuron's and is built now, so the engine behind it can change.

### 2.6 Agent orchestration

| Candidate | Verdict | Reason |
| --- | --- | --- |
| LangChain `create_agent` and LangGraph | **Adopt (keep)** | In use; middleware model fits policy and approvals. |
| LangChain Deep Agents | Inspiration | Planning tool and context patterns (prior research). |
| Claude Agent SDK, OpenAI Agents SDK, Google ADK, Microsoft Agent Framework | Inspiration | Switching frameworks buys nothing and risks the tested security layer. |
| A2A SDK | Defer | Adopt when a customer needs agent-to-agent calls. |

### 2.7 Observability and evaluation

| Candidate | Licence and status | Verdict | Reason |
| --- | --- | --- | --- |
| OpenTelemetry | Apache-2.0; graduated at CNCF in 2026 per reports [S] | **Adopt (keep)** | In use with GenAI conventions. |
| Prometheus, Grafana | Open source (Grafana is AGPL as a separate service) [K] | Integrate | Reference dashboards only. |
| LangSmith | Commercial; already optional | Integrate (keep optional) | Must stay optional under rule 4. |
| Langfuse, Arize Phoenix | Open-source cores [K]; licences to confirm | Integrate as optional trace viewers | Useful for trajectory review; receive OpenTelemetry. |
| Neuron's evaluation harness | n/a | **Extend** | Already has baselines and confidence intervals; add trajectory grading and per-application cases. |

### 2.8 Knowledge retrieval and document processing

| Candidate | Verdict | Reason |
| --- | --- | --- |
| Postgres with pgvector and full-text search | **Adopt (keep)** | In use; one database. |
| Docling | **Adopt (keep)** | In use. |
| A dedicated vector database | Reject for now | No measured need. |
| Unstructured, LlamaIndex | Not needed | Overlap with what exists. |
| Glean, Elastic, Coveo, Microsoft Graph | Integrate through their MCP servers or APIs | A customer's existing search becomes a capability. |
| Graph database | Reject for now | Document 6, section 10. |

### 2.9 Event processing

| Candidate | Verdict | Reason |
| --- | --- | --- |
| Signed webhook endpoint into Postgres job tables | **Build** | Small; covers application events. |
| Kafka, NATS, RabbitMQ clients | Reject in core | Customers bridge streams to webhooks. |
| CloudEvents format [K] | Adopt as the accepted envelope | A standard shape for inbound events; no runtime dependency. |

### 2.10 Sandboxing

| Candidate | Verdict | Reason |
| --- | --- | --- |
| Any code or browser sandbox | Reject | Neuron runs no model-written code and no browser. Decided in the prior research; nothing here changes it. |

### 2.11 Secrets management

| Candidate | Licence and status | Verdict | Reason |
| --- | --- | --- | --- |
| Secrets interface with an envelope-encrypted Postgres backend | n/a | **Build** (small) | Works on a single host with no extra system. |
| OpenBao | Open licence, Linux Foundation, v2.7 [S] | **Integrate as the recommended production backend** | Open fork of Vault. |
| HashiCorp Vault | BSL, IBM [S] | Integrate if the customer owns it | Licence fails rule 5 as a required part; API-compatible with OpenBao for basic use [K]. |
| Cloud secrets managers and KMS | Commercial | Integrate | For customer-cloud deployments. |
| CyberArk and other privileged-access products | Commercial | Integrate on demand | Customer-side. |

### 2.12 Legacy access

| Candidate | Verdict | Reason |
| --- | --- | --- |
| UiPath, Automation Anywhere, Power Automate robots | Integrate as capabilities through their APIs or MCP servers | The only sound way to reach applications with no interface. |
| In-house browser automation | Reject | Security model. |
| Read-only database adapter with pre-approved queries | Build later, on demand | Useful for legacy data; small if queries are fixed. |

## 3. The minimum set Neuron must own

These seven are the product. Everything else is replaceable.

| Component | Why it must be Neuron's |
| --- | --- |
| **1. Application onboarding pipeline** (registry, manifest, importer, curation) | The reason to choose Neuron; no open equivalent ties import to risk classification and review |
| **2. Credential broker** | Enforces the user-ceiling principle; too security-critical to delegate to a hosted third party |
| **3. Policy decision point** (interface and default rule engine) | The single choke point; must be default-deny and fully tested |
| **4. Approval service** | Tiers, binding to arguments, separation of duties |
| **5. Run engine and event log** | Durability, resume, idempotency; the audit trail hangs off it |
| **6. Domain packs** | The domain-agnostic mechanism |
| **7. Audit ledger** | The evidence that the other six worked |

Kept from today and extended: the agent loop integration, taint tracking, egress control, the Knowledge Engine and the evaluation harness.

## 4. Dependency additions over 18 months

| Addition | Certain or conditional |
| --- | --- |
| An OpenAPI parser and validator library | Certain |
| DBOS Transact | Conditional on the spike in section 2.3 |
| A Cedar binding | Conditional on customers needing to author rules |
| An OpenBao or Vault client | Certain, optional at run time |
| A SCIM library | Conditional |
| A Helm chart (not a Python dependency) | Certain |

Nothing else is expected. No message broker, no graph or vector database, no second web framework.

## 5. Operational cost notes

| Choice | Operational effect |
| --- | --- |
| Postgres for queue, events, audit, vectors | One system to back up and tune; growth in one place, so partitioning and retention matter early |
| Keycloak as broker | Already operated; upgrades and theme maintenance continue |
| Secrets backend | One more system in production deployments; none on a single host |
| No gateway of its own | No extra network hop; customers who want one add it |
| Optional trace viewer | Only for teams that want trajectory review |

## 6. Open questions to resolve before adoption

1. Result of the durable-execution spike.
2. Licence and Python-binding maturity for Cedar; licence of Cerbos and Restate.
3. Which IdPs the first design partners use, which decides whether token exchange or per-user OAuth is built first.
4. Whether the first target applications publish usable OpenAPI documents. If most do not, the importer needs a "describe by example" path sooner.
