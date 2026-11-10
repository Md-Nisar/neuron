# Enterprise Feature Catalog

| | |
| --- | --- |
| Date | 2026-11-10 |
| Package | Document 9 of 14 |
| Evidence | "Neuron today" is from the architecture assessment and repository checks. "Who provides it" is from document 2; vendors are named only where the research found the capability documented. Essential, complexity and value ratings are my judgement [I]. |

## How to read this document

Each table answers the seven questions in the brief:

1. **Essential:** Yes (a serious buyer will not proceed without it), Later (expected within the first year of use), No (optional for Neuron's positioning).
2. **Neuron today:** Has, Partial, None.
3. **Who provides it:** representative competing products.
4. **Open source:** an available implementation, where one exists. Licences from the research are in document 10; others are from background knowledge and need checking.
5. **Approach:** Build (Neuron owns it), Extend (grow something Neuron has), Integrate (use an external product).
6. **Complexity:** S, M, L.
7. **Value:** High, Medium, Low for the recommended positioning.

The **Roadmap** column points to the feature id in `NEURON_18_MONTH_STRATEGIC_ROADMAP.md`. "n/p" means not planned within 18 months.

## 1. Enterprise onboarding

| Capability | Essential | Neuron today | Who provides it | Open source | Approach | Complexity | Value | Roadmap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Enterprise registration | Later | None | All hosted platforms | n/a | Build, minimal (self-hosted: one organisation created at install) | S | Low | F1.1 |
| Organisation management | Yes | None (users only) | All | Keycloak organisations | Build the data model; integrate IdP for membership | M | High | F1.1 |
| Department management | Yes | None | Microsoft, ServiceNow, Workday | IdP groups | Build as a mapping from IdP groups | S | Medium | F1.1 |
| User provisioning | Later | Partial (just-in-time from token) | All; SCIM is standard | Keycloak; SCIM libraries | Integrate (SCIM endpoint later) | M | Medium | F1.2 |
| Single sign-on | Yes | Partial (OIDC through Keycloak) | All | Keycloak (brokers SAML and OIDC) | Integrate | S | High | F1.2 |
| Application connection management | Yes | None (operator file for MCP) | Workato, MuleSoft, Boomi, Composio, Arcade, Nango | Nango (source-available) | Build | L | High | F2.1, F2.2 |

## 2. Integration

| Capability | Essential | Neuron today | Who provides it | Open source | Approach | Complexity | Value | Roadmap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Connector marketplace | No | None | Workato, Microsoft, Zapier, Boomi | None comparable | Integrate through MCP. Do not build. | n/a | Low for Neuron | n/p |
| Custom connector SDK | Later | None | MuleSoft, Workato, Microsoft | MCP SDKs | Build as documentation of the manifest format, not a code SDK | M | Medium | F5.5 |
| API discovery (OpenAPI import) | Yes | None | AgentCore Gateway, Foundry, MuleSoft MCP Bridge | OpenAPI parsers; several OpenAPI-to-MCP tools | Build the pipeline on existing parsers | M | High | F2.3 |
| MCP support (client) | Yes | Partial (static, operator token, pinned) | All | Official MCP SDK (in use) | Extend | M | High | F2.6 |
| MCP support (server) | Later | None | ServiceNow, Workato, Glean, Palantir | Official MCP SDK | Build on the SDK | M | Medium | F5.4 |
| Webhook support | Later | None | All integration platforms | n/a | Build | M | High | F4.2 |
| Event integration (streams, queues) | No | None | MuleSoft, Boomi, Workato | Kafka, NATS | Integrate through webhooks | n/a | Low | n/p |
| Integration health monitoring | Yes | None | Boomi, MuleSoft, Workato | n/a | Build | S | Medium | F2.7 |
| Per-user delegated credentials | Yes | None | AgentCore Identity, Arcade, Composio, WSO2 | Nango; Keycloak token exchange | Build the broker; integrate IdP and secrets store | L | High | F2.2 |

## 3. Agent management

| Capability | Essential | Neuron today | Who provides it | Open source | Approach | Complexity | Value | Roadmap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Agent creation and configuration | Yes | None (one agent at start-up) | All | LangGraph assistants | Build as versioned definitions | M | High | F4.4 |
| Agent templates | Later | None | Copilot Studio, Agentforce, Workato | n/a | Build as content | S | Medium | F4.4 |
| Domain adaptation | Yes | None | Palantir (Ontology), SAP (Knowledge Graph) | None equivalent | Build (domain packs) | L | High | F3.1, F3.2 |
| Agent permissions | Yes | Partial (scopes per user) | AgentCore Policy, Entra Agent ID | Cedar, OPA | Extend into policy as data | M | High | F1.3 |
| Agent lifecycle management | Later | None | Agent 365, IBM, Boomi, Workday | n/a | Build, small | M | Medium | F4.4 |
| Agent versioning | Yes | None | Palantir (agent versions), most platforms | n/a | Build | S | High | F4.4 |
| Agent testing and evaluation | Yes | Partial (regression harness, single agent) | AgentCore Evaluations, OpenAI trace grading, IBM staging | Langfuse, Phoenix, promptfoo | Extend the harness; export traces to a tool if wanted | M | High | F3.5 |
| Dynamic tool selection | Yes | None (fixed at start-up) | Anthropic tool search, Kong, AgentCore | n/a | Build | M | High | F2.5 |
| Model selection per agent | Later | None (one global model) | All | LiteLLM | Extend the model factory | M | Medium | F3.4 |

## 4. Workflow

| Capability | Essential | Neuron today | Who provides it | Open source | Approach | Complexity | Value | Roadmap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Multi-application workflows | Later | None | UiPath Maestro, Workato, ServiceNow, Pega | Temporal, DBOS, Camunda | Build a small step runner on the run engine; integrate customers' engines for long processes | L | High | F4.3 |
| Human approvals | Yes | Partial (same user, live run) | Microsoft Agent Framework, ServiceNow, Palantir | LangGraph interrupts (in use) | Extend into a durable approval service | M | High | F4.1 |
| Long-running execution | Yes | None | Managed Agents, LangSmith Agent Server, AgentCore | DBOS, Temporal, Procrastinate (in use) | Build on Postgres, pending the evaluation in document 10 | L | High | F1.5 |
| Scheduling | Later | Partial (cron inside the ingestion worker) | All | Procrastinate periodic tasks | Extend | S | Medium | F4.2 |
| Event-triggered execution | Later | None | All integration and automation platforms | n/a | Build | M | High | F4.2 |
| Workflow history | Later | None | All | n/a | Build (falls out of the run event log) | S | Medium | F1.5 |
| Recovery and resume | Yes | Partial (clean failure only) | Temporal, LangGraph, Microsoft workflows | Same | Build with durable runs | L | High | F1.5 |

## 5. Enterprise knowledge

| Capability | Essential | Neuron today | Who provides it | Open source | Approach | Complexity | Value | Roadmap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Document ingestion | Yes | Has | Glean, Microsoft, all | Docling (in use), Unstructured | Keep | n/a | High | n/a |
| Application-aware retrieval | Later | None | Glean, SAP, Palantir | n/a | Build through domain packs plus live reads | M | Medium | F3.1 |
| Permission-aware search | Yes | Partial (owner-only; grants table unused) | Glean, Microsoft Graph, Elastic, Coveo | OpenSearch document-level security | Extend to shared bases with grants | M | High | F3.3 |
| Knowledge graphs | No | None | SAP, Palantir, Glean | Neo4j (licence varies), Apache AGE | Do not build now; relational identity links instead | n/a | Low now | n/p |
| Business entity relationships | Later | None | Palantir, SAP | n/a | Build in domain packs | M | Medium | F3.1 |
| Data source management (sync connectors) | No (first year) | None | Glean, Microsoft, Unstructured | Airbyte, Unstructured | Integrate later; upload first | L | Medium | n/p |

## 6. Governance

| Capability | Essential | Neuron today | Who provides it | Open source | Approach | Complexity | Value | Roadmap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Policy management | Yes | Partial (rules in Python) | AgentCore Policy, Kong, MuleSoft | Cedar, OPA, Cerbos | Build a rule table first; adopt a policy language when customers author rules | M | High | F1.3 |
| Audit logs | Yes | Partial (audit events in logs) | All | n/a | Extend into an append-only ledger | M | High | F1.4 |
| Tool permissions | Yes | Has (scope, risk, taint per tool) | AgentCore, Kong, Claude Code | n/a | Extend to argument level | M | High | F1.3 |
| Data access controls | Yes | Partial (owner isolation, row-level security) | Glean, Palantir, application vendors | Postgres row-level security (in use) | Extend with organisation id and data labels | M | High | F1.1, F1.3 |
| Execution policies (limits, quotas) | Yes | Has per user | All | n/a | Extend to organisation, department, agent | S | Medium | F5.2 |
| Agent monitoring | Later | Partial (traces, metrics) | Agent 365, Boomi, IBM, ServiceNow | OpenTelemetry (in use) | Extend | S | Medium | F5.1 |
| Emergency stop | Yes | None (process shutdown only) | Boomi | n/a | Build at the decision point | S | High | F1.3 |

## 7. Operations

| Capability | Essential | Neuron today | Who provides it | Open source | Approach | Complexity | Value | Roadmap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Usage analytics | Later | Partial (token ledger per user) | All | Grafana | Extend | S | Medium | F5.2 |
| Cost monitoring | Yes | Partial (tokens, not money) | Boomi, ServiceNow, IBM | Langfuse, LiteLLM | Extend the ledger with dimensions and prices | S | High | F5.2 |
| Execution traces | Yes | Has (OpenTelemetry, GenAI conventions) | All | OpenTelemetry | Keep; add a user-facing run timeline | S | High | F1.5 |
| Performance metrics | Yes | Has | All | Prometheus, Grafana | Keep | n/a | Medium | n/a |
| Connector monitoring | Yes | None | Integration platforms | n/a | Build | S | Medium | F2.7 |
| Agent evaluation | Yes | Partial | See agent testing | See agent testing | Extend | M | High | F3.5 |
| Error management | Yes | Has (error taxonomy) | All | n/a | Extend with application error normalisation | S | Medium | F2.4 |

## 8. User experience

| Capability | Essential | Neuron today | Who provides it | Open source | Approach | Complexity | Value | Roadmap |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Enterprise AI assistant (chat) | Yes | Has | All | n/a | Keep | n/a | High | n/a |
| Application-aware conversation | Yes | None | Application vendors, Glean | n/a | Build through packs and capability selection | M | High | F3.1, F2.5 |
| Agent workspace (choose an agent, see its scope) | Later | None | Copilot Studio, Agentforce, Glean | n/a | Build, small | M | Medium | F4.4 |
| Task monitoring (run timeline) | Yes | Partial (live stream events) | Devin, Cursor, most platforms | n/a | Build on the event log | M | High | F1.5 |
| Approval inbox | Yes | None | ServiceNow, Microsoft, Palantir | n/a | Build | M | High | F4.1 |
| Workflow visibility | Later | None | UiPath, ServiceNow | n/a | Build with workflows | M | Medium | F4.3 |
| Generated reports and artifacts | No (first year) | None | Most assistants | n/a | Defer | M | Low now | n/p |
| Embedded assistant inside the host application | Later | None | Application vendors | n/a | Build a small embeddable client once the API is stable | M | Medium for software vendors | n/p |
| Administration console | Yes | None | All | n/a | Build, minimal | L | High | F5.1 |

## 9. Summary counts

Of 60 capabilities listed:

| | Count |
| --- | --- |
| Essential now ("Yes") | 36 |
| Expected later | 19 |
| Not essential | 5 |
| Neuron has | 7 |
| Neuron has partially | 17 |
| Neuron has none | 36 |
| Approach: integrate, defer or do not build | 7 |
| Not planned within 18 months | 6 |

The essential capabilities Neuron lacks entirely cluster in four places: organisation model, application connection and credentials, agent definitions, and durable execution. Those four are the spine of the roadmap.

## 10. Capabilities deliberately rated non-essential

| Capability | Why it is not essential for Neuron |
| --- | --- |
| Connector marketplace | Available through MCP from vendors with thousands of connectors |
| Event streams and queues | Customers' integration platforms bridge them to webhooks |
| Knowledge graph | Identity links cover the first cross-application needs; revisit at larger scale |
| Sync connectors for content | Upload and live reads cover the first use cases |
| Generated reports and artifacts | Present in every general assistant; not a reason to choose Neuron |
| Low-code agent builder | Agent definitions are forms over data; a visual builder is a product of its own |
