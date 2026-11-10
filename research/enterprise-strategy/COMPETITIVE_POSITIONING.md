# Competitive Positioning

| | |
| --- | --- |
| Date | 2026-11-10 |
| Package | Document 4 of 14 |
| Evidence | Product facts and their labels are in `ENTERPRISE_AI_MARKET_AND_PRODUCT_RESEARCH.md`. Judgements here are mine [I]. |

## 1. Verdict on the proposed positioning

> "Neuron provides a universal agentic intelligence and integration layer that makes existing enterprise applications agent-capable, regardless of domain or technology stack."

**This is not differentiated.** The same sentence, almost word for word, describes MuleSoft Agent Fabric, Workato Enterprise MCP, Boomi Agent Control Plane, Microsoft Foundry, Amazon Bedrock AgentCore, IBM watsonx Orchestrate and Google's Gemini Enterprise Agent Platform. Each of them has what the sentence implies and Neuron lacks: a connector catalogue, a sales channel, compliance attestations and production history.

Three specific problems with the claim:

1. **"Universal"** invites comparison on connector count. Vendors advertise 1,400 to 12,000. Neuron has none.
2. **"Regardless of technology stack"** cannot be honoured. An application with no API, no database access and no MCP server can only be reached by screen automation, which Neuron's security model excludes.
3. **"Integration layer"** names a category (iPaaS, API management) where buyers expect ten years of maturity.

## 2. Competitor analysis

Scope note: the last column states what the research found, with prices from secondary sources. The deployment entries for UiPath, Palantir, MuleSoft, Boomi and the cloud-only vendors are background knowledge [K], not re-checked. Blank means not found, not "none".

| Product | Does exceptionally well | Integration strength | Domain limits | Ecosystem advantage | Security | Deployment and price signals |
| --- | --- | --- | --- | --- | --- | --- |
| **Microsoft Copilot Studio** | Low-code agent building for Microsoft 365 organisations | Reported 1,400+ connectors; MCP | Best where data lives in Microsoft 365 and Dataverse | Entra, Teams, the installed base | Entra Agent ID per agent | Cloud. Credits, reported $0.01 each |
| **Salesforce Agentforce** | Agents on CRM data with a planning engine | Deep in Salesforce; outside it through MuleSoft | CRM-centred | Largest CRM base | Inherits Salesforce permissions | Cloud. Reported $2 per conversation or Flex Credits |
| **ServiceNow AI Agents** | Agents over IT and employee workflows; governance console | Action Fabric exposes workflows and approvals by MCP | Workflow-centred; strongest in IT service | The workflow system of record in large enterprises | Control Tower; permission enforcement partner | Cloud |
| **SAP Joule** | Agents with SAP business semantics | SAP systems; A2A and MCP outward | SAP-centred | ERP base | SAP roles | Cloud; timelines unclear |
| **Oracle AI Agent Studio** | Agents inside Fusion applications | Fusion; A2A outward | Fusion-centred | ERP and HCM base | Inherits Fusion roles | Included with Fusion per reports |
| **IBM watsonx Orchestrate** | Multi-vendor agent catalogue and governance | Catalogue of 150+ agents and tools | Horizontal | Consulting channel; hybrid and on-premises | Vault for agents; discovery of third-party agents | Hybrid |
| **Google Gemini Enterprise Agent Platform** | Managed runtime with search and A2A | Hundreds of connectors | Horizontal | Google Cloud and Workspace | Cloud IAM | Cloud |
| **Amazon Bedrock AgentCore** | Building blocks: runtime, gateway, identity, policy | OpenAPI and Lambda to MCP tools | Horizontal, developer-facing | AWS base | Cedar policy at the gateway; token vault | Cloud, consumption |
| **Workato** | Recipes plus agents on one platform | "12,000+" applications through Enterprise MCP | Horizontal | iPaaS customers | Governed MCP access | Cloud |
| **MuleSoft** | API-led integration with agent registry and gateway | Existing APIs become MCP through a bridge | Horizontal | Salesforce; large-enterprise API estates | Gateway policies for MCP and A2A | Hybrid |
| **Boomi** | Integration plus agent registry with kill switch | Managed MCP servers for enterprise systems | Horizontal | iPaaS customers | Control plane enforcement | Hybrid |
| **UiPath** | Automating applications with no API; orchestrating robots, agents and people | UI automation is the differentiator | Horizontal | RPA installed base | Robot credentials and orchestrator controls | Cloud and on-premises |
| **Glean** | Permission-aware search across company content | Content connectors that carry access lists | Knowledge, not transactions | Search-first adoption | Source permissions enforced at query | Cloud |
| **Moveworks (ServiceNow)** | Employee service assistant | IT and HR systems | Employee support | Now ServiceNow | | Cloud |
| **Palantir AIP** | Ontology that models objects and actions with permissions | Whatever is modelled into the Ontology | Any domain, after a heavy modelling project | Government and large industrial accounts | Action submission criteria; scoped agents | Cloud and on-premises; high-touch |
| **Emerging: Composio, Arcade, Nango, Merge Agent Handler** | Managed authentication and ready-made tools for agent developers | Hundreds of APIs | Horizontal, developer-facing | Fast-moving, well funded | Per-user OAuth handling | Cloud; some source-available |
| **Emerging: open-source gateways** (agentgateway, ContextForge, Microsoft MCP Gateway) | Routing and policy for MCP traffic | Whatever MCP servers exist | Horizontal | Foundation governance | OAuth and per-tool policy | Self-hosted, open licences |

## 3. Where Neuron cannot compete

| Ground | Why not |
| --- | --- |
| Connector breadth | A catalogue is years of maintenance. Vendors with thousands exist, and applications now ship their own MCP servers. |
| Agents inside a vendor suite | Salesforce, SAP, Oracle, ServiceNow and Workday own the data model, the permissions and the user interface. |
| Fleet governance of all agents in an enterprise | Microsoft, IBM, Boomi, ServiceNow and Workday sell this to the same buyer, tied to the directory or system of record. |
| Low-code builders for business users | Requires a large front-end investment and a support organisation. |
| Screen automation | UiPath and its peers have a decade of product. |
| Enterprise search | Glean, Microsoft and Google, with hundreds of permission-syncing connectors. |
| Enterprise procurement today | No SOC 2 report, no production history, no support organisation. |

## 4. Where Neuron can compete

Each row names the advantage and the evidence that it is real today or must be built.

| Ground | Neuron's advantage | Status |
| --- | --- | --- |
| **Self-hosted, open licence** | Apache-2.0, runs on Postgres and one container image, any OpenAI-compatible model including local ones. Most competitors are cloud services; the hybrid ones are proprietary. | Real today (licence, packaging). Unproven in a hosted environment. |
| **Deterministic enforcement** | Permissions, approvals and taint rules enforced in code, with a security test suite. Many agent products rely on prompt instructions plus monitors. | Real today for a small tool set. |
| **User-ceiling access** | The agent acts with the requesting user's credential, so the application's own row and field rules apply. Vendors do this inside their suite; few do it for arbitrary custom applications. | Must be built (credential broker). |
| **Custom and line-of-business applications** | The application vendors do not cover them. Integration vendors cover them at enterprise prices. | Must be built (onboarding pipeline). |
| **Software vendors embedding an agent** | A vendor of a vertical application can ship Neuron beside its product under an open licence, with its own API as the tools. n8n-style licences restrict this; Apache-2.0 does not. | Possible today in principle; needs the onboarding pipeline. |
| **Regulated and sovereign environments** | No data leaves the customer's network when used with a self-hosted model. | Real in design; needs a reference deployment. |

## 5. Where Neuron should integrate rather than compete

| With | How |
| --- | --- |
| iPaaS and connector vendors (Workato, MuleSoft, Boomi, Zapier) | Consume their MCP servers as application connections. |
| Application vendors' MCP servers (ServiceNow, Salesforce, Glean, Databricks) | Same. Use the vendor's server with the user's delegated token. |
| Identity providers (Entra, Okta, Keycloak, WSO2) | OIDC federation; token exchange; later MCP enterprise-managed authorization. |
| Agent platforms (Copilot Studio, Claude, Agentforce) | Expose Neuron's governed capabilities as an MCP server so those assistants can call them. |
| Agent registries (Agent 365, Workday ASOR, Boomi, IBM) | Publish Neuron agents' identity and audit records to them when a customer has one. |
| RPA vendors | Call robots as tools for applications with no API. |
| Policy, secrets, observability | Cedar or OPA; OpenBao or a cloud secrets manager; OpenTelemetry to any backend. |

## 6. Recommended positioning

> **Neuron is the open-source agent layer for your own applications.** Point it at an application's API, and your users get an agent that works within their existing permissions, asks before it acts, and records everything. It runs in your infrastructure, with the model you choose.

Why this wording:

- **"Your own applications"** points at the uncovered ground (custom, line-of-business, self-hosted, a vendor's own product) and away from the suites.
- **"Within their existing permissions"** is the claim buyers most need and can verify.
- **"Runs in your infrastructure"** is the structural difference from almost every competitor.
- It makes no claim about connector count or autonomy.

### Target users, in order

1. **Engineering teams in mid-sized organisations** with one or more important custom applications and a requirement to self-host.
2. **Independent software vendors** who want to add an agent to a vertical product without building the safety layer.
3. **Regulated or public-sector teams** that cannot send application data to a hosted agent platform.

Large enterprises standardised on Microsoft, Salesforce or ServiceNow are not the first market. They are reached later, through the MCP endpoint.

## 7. Limitations of this strategy

1. **The niche may be smaller than it looks.** Mid-sized teams may prefer an agent SDK and hand-written tools. Neuron must show a clear time and safety advantage.
2. **Open source does not fund itself.** A revenue model (support, a hosted offering, paid administration features) is needed and is undecided. This is the owner's decision.
3. **The moat is execution, not technology.** Every component described in this package has a public reference. A well-funded competitor could assemble the same.
4. **MCP may make "connecting" trivial for everyone.** Then the remaining value is governance, and the large vendors are investing there too. Neuron's answer is depth of enforcement and self-hosting, which may or may not be enough.
5. **Per-user delegation depends on the application.** Many custom applications have only API keys. For those, Neuron's strongest claim weakens to "restricted service account with filters".
6. **Trust takes evidence.** No deployment, penetration test or attestation exists yet. Positioning on security without them invites a challenge Neuron cannot meet today.

## 8. Signals that should change the positioning

| Signal | Response |
| --- | --- |
| A design partner needs hosted multi-tenant service | Bring forward SaaS work from beyond the 18-month plan |
| Onboarding an application takes weeks, not days | Stop and fix the pipeline before adding features |
| Most target applications expose only shared API keys | Invest in the restricted-service-account path and say so plainly in the pitch |
| An open-source competitor ships the same pipeline with more adoption | Consider contributing to it and specialising on the policy and approval layer |
