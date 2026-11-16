# Enterprise AI Market and Product Research

| | |
| --- | --- |
| Date | 2026-11-10 |
| Package | Document 2 of 14 |
| Evidence labels | **[V]** vendor's own page in results; **[S]** secondary only; **[K]** background knowledge, not re-checked; **[I]** inference. See `NEURON_VISION_AND_MISSION.md`. |

## How to read this document

Each product entry states what is publicly documented and what it means for Neuron. Internal designs are proprietary and are not described. Prices come mostly from secondary sources and must be checked against the vendor before use. Products marked [K] were not searched in this session.

## 1. Summary

1. **The market converged on one architecture in 2025 and 2026.** Almost every vendor now describes the same four parts: a registry of agents and tools, a gateway that enforces policy on tool calls, an identity for each agent, and a monitoring console. The names differ (Agent Fabric, Control Tower, Control Plane, Agent 365, AgentCore).
2. **MCP became the standard way to expose an application to an agent, and vendors now ship their own servers.** ServiceNow, Workato, Boomi, MuleSoft, Microsoft, Glean and Palantir all expose their platforms through MCP, and Databricks connects its agents to outside systems through it. An application's vendor is increasingly the supplier of its agent tools.
3. **Connector breadth is a solved, commoditised problem.** Counts above a thousand are common. A new entrant cannot win here.
4. **Identity for agents is the active frontier.** Agent identities in the directory, token exchange on behalf of users, and IdP-managed authorization for MCP all shipped in 2026.
5. **Application vendors keep agents inside their own permission model.** Oracle, Salesforce, SAP, ServiceNow, Workday and Palantir all state that agents inherit the application's roles and data permissions.
6. **Automation vendors agree that fixed process and model reasoning should be separated.** Pega and Automation Anywhere say so explicitly.
7. **Reported failure rates for enterprise agent projects are high, and the cited causes are cost, unclear value and weak controls,** not model capability. The numbers come from secondary reports of analyst work.

## 2. Enterprise AI platforms

| Product | Publicly documented | Relevance to Neuron |
| --- | --- | --- |
| **Microsoft Copilot Studio** | Low-code agent builder. Reported 1,400+ connectors and MCP support [S]. New agents receive a Microsoft Entra Agent ID automatically [V]. Consumption priced in Copilot Credits, reported at $200 per 25,000 credits or $0.01 pay-as-you-go [S]. | The default for Microsoft 365 organisations. Neuron should be reachable from it as an MCP server, not compete with it. |
| **Microsoft Foundry Agent Service** | Tool catalogue including OpenAPI tools, MCP tools, Azure Functions and browser automation. Logic Apps connectors exposed as MCP tools; API Management can expose any API as an MCP tool [V/S]. | Shows the pattern Neuron needs: an existing API becomes agent tools through a gateway, not through hand-written code. |
| **Microsoft Agent 365 and Entra Agent ID** | A registry and governance layer for agents, with directory identities. Reported at about $15 per month; sources disagree on whether per user or per agent [S]. | Fleet governance. Neuron should emit what such a registry needs (identity, audit), not rebuild it. |
| **Microsoft Agent Framework** | Covered in `NEURON_GLOBAL_AGENT_ARCHITECTURE_RESEARCH.md`: checkpointed workflows that pause for human decisions. | Reference for durable approvals. |
| **OpenAI enterprise agent infrastructure** | Covered in the prior research: Agents SDK, trace grading, approval pauses. Connector and enterprise admin features were not re-searched [K]. | Model provider and SDK reference. |
| **Anthropic Claude Enterprise and Agent SDK** | Covered in the prior research. Claude connectors support MCP enterprise-managed authorization per secondary reports [S]. | Model provider. A likely client of a Neuron MCP endpoint. |
| **Google Gemini Enterprise Agent Platform** | Announced April 2026 as the successor branding for Vertex AI Agent Builder, Agentspace and ADK. Managed runtime (Agent Engine), connectors, A2A and MCP [S]. Google's technical guide lists hundreds of connectors [V]. | Same convergence. A2A's main sponsor. |
| **Amazon Bedrock AgentCore** | Generally available October 2025 [V]. Gateway turns Lambda functions, OpenAPI specifications and Smithy models into MCP tools [V]. Policy (Cedar rules evaluated on every tool listing and tool call) generally available March 2026 [V]. Identity includes a token vault and on-behalf-of token exchange [V]. | The clearest public reference for three things Neuron needs: OpenAPI-to-tool conversion, policy as data at one choke point, and a credential broker. |
| **IBM watsonx Orchestrate** | Agent catalogue with 150+ agents and tools [S]. An "Agentic Control Plane" [V]. October 2026: Vault extended to agents; discovery and containment for agents built on Bedrock, Foundry and Gemini [S]. | IBM also publishes ContextForge, an Apache-2.0 MCP gateway without official support [V]. |
| **NVIDIA enterprise AI** | NIM inference microservices and agent toolkits for self-hosted models [K]. Not searched. | Relevant only as a model-serving option for on-premises customers. Neuron's OpenAI-compatible provider path already covers it. |
| **Databricks Agent Bricks** | Expanded in 2026 into an agent platform on governed data; MCP support through Unity Catalog; "100k+ agents built" is the vendor's figure [V]. | Agents anchored to a data platform's governance. Not Neuron's ground. |
| **Palantir AIP** | The Ontology defines object types, action types and functions. An action is one transaction with submission criteria that decide who may run it [V]. Ontology objects, actions and queries can be exposed as MCP tools [S]. Agents acting through action types are bound by the same validation as people [S]. | The strongest public example of a semantic layer where actions, not only data, are modelled and permissioned. The idea is worth borrowing; the cost of building an ontology is what Neuron must avoid. |

## 3. Enterprise application platforms

| Product | Publicly documented | Relevance to Neuron |
| --- | --- | --- |
| **Salesforce Agentforce** | Atlas Reasoning Engine plans and evaluates steps [S]. Pricing reported as Flex Credits at $500 per 100,000 (a standard action about $0.10), or $2 per conversation [S]. | Strong inside Salesforce data. A Salesforce customer will use it there. |
| **MuleSoft Agent Fabric** (Salesforce) | Four parts: Agent Registry (agents, MCP servers, APIs), a gateway (Flex Gateway, renamed Omni Gateway) with MCP and A2A policies, Agent Broker, Agent Visualizer [V]. MCP Bridge wraps existing APIs as MCP without custom code [V]. | Direct overlap with the "universal layer" positioning, from an integration leader. |
| **SAP Joule** | Joule Studio for custom agents; A2A support; a Knowledge Graph being extended to non-SAP data; an Enterprise AI Gateway planned for 2027 per one report [S]. Dates conflict across sources. | SAP customers get SAP semantics from SAP. Neuron cannot match that depth and should not try. |
| **ServiceNow** | AI Control Tower and AI Agent Fabric (2025) [V]. Action Fabric (2026) exposes ServiceNow workflows, approvals and business rules to any agent through its MCP server [S]. Acquired Moveworks, reported at $2.85 billion [S]. | A system of record now ships its own MCP server with approvals included. Neuron's job with such a system is to call it, with the user's identity. |
| **Oracle AI Agent Studio** | Fusion Agentic Applications announced March 2026 [V]. Agents inherit Fusion role-based access and data permissions; A2A supported for external integration [S]. | Same pattern: agents inside the application's permission model. |
| **Workday** | Agent System of Record generally available [V]; Agent Gateway connects partner agents through MCP and A2A [V]. Agreed to acquire Pipedream (3,000+ connectors) in November 2025 [S]. | An independent connector platform was absorbed by an application vendor. Dependence on any single connector vendor carries this risk. |
| **Microsoft Dynamics 365 agents** | Not searched. Built on Copilot Studio and Dataverse [K]. | As Copilot Studio. |
| **HubSpot Breeze** | Not searched. Agents for marketing, sales and service inside HubSpot [K]. | Mid-market, in-suite. |
| **Glean** | Connectors fetch content and the permissions map from each source; results are filtered to what the user may see in the source [V]. Offers an MCP server and agents [V/S]. | The reference for permission-aware enterprise search. The method (sync access lists with content, filter at query time) is the one Neuron must follow for shared knowledge. |
| **Moveworks** | Now part of ServiceNow, relaunched as EmployeeWorks [S]. | Employee service desk is a crowded use case. |

## 4. Enterprise integration platforms

| Product | Publicly documented | Build or integrate |
| --- | --- | --- |
| **MuleSoft** | See Agent Fabric above. | Integrate: a customer with MuleSoft exposes APIs to Neuron as MCP. |
| **Workato** | Enterprise MCP gives agents governed access to "12,000+" applications (vendor figure) [V]. Its own agents (Genies) act as MCP clients and can be exposed as MCP servers [V]. | Integrate through MCP. |
| **Boomi** | Agent Control Tower registers agents from Bedrock, Agentforce and Copilot, with a kill switch [V]. MCP Registry and Boomi Connect (2026) [S]. Agent Control Plane (September 2026) [V]. | Integrate through MCP. |
| **Informatica** | Not searched. Data integration and master data management; acquired by Salesforce [K]. | Out of scope. Relevant only as a source of master data identifiers. |
| **n8n** | Source-available under the Sustainable Use License; sources disagree on how far embedding in a product is allowed [S]. | Do not embed. A customer may run it beside Neuron. |
| **Zapier** | Zapier MCP exposes its catalogue to MCP clients with managed authentication [S]. | Integrate through MCP for small customers. |
| **Make** | Agents and MCP support mentioned in comparisons only [S]. | As Zapier. |
| **Pipedream** | Acquired by Workday [S]. | Avoid as a dependency. |
| **WSO2** | Identity Server documents an agent identity model for MCP, with tokens that name both the user and the agent as actor [V]. Agent Manager generally available September 2026 [S]. Open-source heritage [K]. | A candidate identity and gateway component for self-hosted customers. |
| **Kong** | MCP proxy and an OAuth 2.1 plugin for MCP; the OAuth plugin is Enterprise-only [V]. Aggregates several MCP servers behind one endpoint with per-tool access control [V]. | Optional gateway in front of Neuron's outbound calls. Not a dependency. |
| **Agent-specific integration vendors** | Composio, Arcade, Nango and Merge Agent Handler sell managed authentication and prebuilt tools for agents. Nango describes itself as source-available [V]. Merge Agent Handler reported from $1,000 per month [S]. | Closest commercial analogues to Neuron's connection manager. Use as design references, and allow a customer to plug one in. |
| **Open-source gateways** | agentgateway (Apache-2.0, Linux Foundation, MCP and A2A) [V]. Microsoft MCP Gateway (reported MIT) [S]. IBM ContextForge (Apache-2.0) [V]. | Optional. See `BUILD_VS_INTEGRATE_ANALYSIS.md`. |

**What the integration category teaches:**

- **Connectivity** is sold as a catalogue. Neuron should accept catalogues through MCP.
- **API management** vendors turned their gateways into the policy point for agent traffic. Neuron needs its own policy point for the calls it makes; it does not need to be a general gateway.
- **Event-driven integration** (webhooks, queues) stays the integration platform's job. Neuron needs one inbound door for events.
- **Hybrid deployment** is standard for MuleSoft, Boomi and Kong, with a cloud control plane and customer-side runtimes [K]. Neuron's self-hosted stance covers the same need more simply.

## 5. Enterprise automation platforms

| Product | Publicly documented | Lesson |
| --- | --- | --- |
| **UiPath** | Maestro orchestrates agents, robots and people. Maestro BPMN for fixed processes and Maestro Case (June 2026) for exception-heavy work [S]. Opened to external coding agents in 2026 [S]. | Fixed and dynamic processes get different tools. |
| **Automation Anywhere** | Process Reasoning Engine; in January 2026, paired with OpenAI models: the model reasons, the engine governs execution [S]. | Reasoning and execution are separated. |
| **Pega** | Agentic Process Fabric; reasoning at design time, approved workflows at runtime; A2A and MCP [V/S]. | The most conservative stance, aimed at regulated industries. |
| **Power Automate, ServiceNow workflows** | Not searched separately [K]. | Same family. |

**How deterministic automation and agents fit together** [I]:

- Use a workflow or rule when the steps are known and the same every time.
- Use an agent for the parts that need interpretation: reading an unstructured request, investigating an exception, drafting a response, choosing among known actions.
- Let the agent *call* existing workflows and robots as tools. A legacy screen with no API is a job for an RPA robot exposed as a tool, not for Neuron.

## 6. Enterprise search and knowledge platforms

| Product | Publicly documented | Lesson |
| --- | --- | --- |
| **Glean** | See section 3. | Permissions are indexed with content and applied per user at query time. |
| **Microsoft Graph and Copilot connectors** | Not searched [K]. Connectors ingest external content with access lists. | Same method. |
| **Google enterprise search** | Part of Gemini Enterprise [S]. | Same method. |
| **Elastic, Coveo** | Not searched [K]. Both support document-level security. | Options for customers who already own one. |
| **LlamaIndex, Unstructured** | Not searched [K]. Libraries and services for parsing and indexing. | Neuron already has Docling and its own retrieval. No change needed. |
| **Knowledge graphs** | SAP Knowledge Graph and Palantir Ontology are the vendor examples [S/V]. | Valuable where the vendor owns the data model. Costly to build generically. See `ENTERPRISE_DOMAIN_ADAPTATION_STRATEGY.md`. |

There are two honest ways to respect source permissions [I]:

1. **Query the source live with the user's credential.** The source enforces its own rules. Always correct, sometimes slow.
2. **Index content with its access list and filter at query time.** Fast, and stale by the sync interval.

Neuron should default to the first for application data and use the second only for documents.

## 7. Security and governance platforms and standards

| Item | Publicly documented | Use for Neuron |
| --- | --- | --- |
| **Microsoft Entra** | Agent IDs in the directory [V]. | A customer IdP. Federate through OIDC. |
| **Okta** | Cross App Access (the IdP mediates which application may reach which) [S]. A January 2026 Okta survey reports 69% of 150 IT and security leaders say security issues slow agent adoption [S]. | A customer IdP. The first live IdP for MCP enterprise-managed authorization [S]. |
| **MCP enterprise-managed authorization** | An official MCP extension, reported stable June 2026. The enterprise IdP issues an identity assertion grant (ID-JAG, an IETF draft) for a specific MCP server, which the client exchanges for an access token [S]. | The cleanest future path to per-user access with no consent screen per user. Design for it, do not depend on it yet. |
| **OAuth token exchange (RFC 8693)** | Standard for exchanging a user's token for one scoped to a downstream service [K]. AgentCore Identity and WSO2 implement it [V]. | The main delegation mechanism where the application and IdP support it. |
| **CyberArk, Palo Alto Networks** | Palo Alto completed its acquisition of CyberArk in February 2026; rationale includes agent identities [S]. Palo Alto's AI runtime security products were not searched [K]. | Customer-side controls. Neuron should integrate with a secrets store, not a specific vendor. |
| **HashiCorp Vault and OpenBao** | Vault is under the Business Source License and now part of IBM [S]. OpenBao is the Linux Foundation fork under an open licence, at v2.7 in late 2026, with Nvidia and SAP reported as adopters [S]. | Secrets backend behind an interface. OpenBao is the open default. |
| **Open Policy Agent** | CNCF graduated, Apache-2.0. Its creators joined Apple in August 2025; governance unchanged, Styra's commercial product wound down [S]. | Mature and general. Rego is a learning cost. |
| **Cedar** | Policy language used by AgentCore Policy [V]. Open source [K]. | Purpose-built for permit and forbid rules over principal, action and resource. |
| **OpenFGA** | CNCF incubating since October 2025 [V]. Relationship-based authorization. | For sharing relationships at scale. Not needed until Neuron has many shared resources. |
| **Cerbos** | Open-source core with a commercial hub [S]. Licence not confirmed here. | Alternative policy decision point. |
| **A2A protocol** | Under the Linux Foundation; 150+ supporting organisations reported April 2026; version 1.0 reported March 2026 with signed agent cards [V/S]. | Relevant once Neuron must be called by, or call, other agents. Later. |
| **OWASP Top 10 for Agentic Applications** | Released December 2025. Items seen in results: goal hijack, tool misuse, identity and privilege abuse, supply chain, unexpected code execution, memory and context poisoning [S]. The full list was not retrieved. | Threat checklist for `ENTERPRISE_SECURITY_AND_GOVERNANCE_ARCHITECTURE.md`. |
| **MCP supply-chain risk** | Researchers report thousands of exposed MCP servers and attacks through tool descriptions: tool poisoning and "rug pulls" where a server changes after approval [S]. | Neuron's sha256 pinning of tool definitions already addresses rug pulls. Keep it. |
| **Cloudflare** | Not searched [K]. Offers remote MCP hosting and access controls. | Customer-side option. |

## 8. Adoption evidence

| Claim | Source quality |
| --- | --- |
| About 95% of enterprise generative AI pilots showed no measurable profit-and-loss effect (MIT Project NANDA, 2025). Criticised for a short measurement window. | [S], primary not read |
| Gartner (June 2025): over 40% of agentic AI projects will be cancelled by the end of 2027, because of cost, unclear value and inadequate risk controls. | [S], primary not read |
| A 2026 Gartner follow-up about enterprises shutting down autonomous agents. | [S], unverified, treat as unconfirmed |

The direction is consistent even if the numbers are soft: enterprises fail on value and control, not on getting a model to call a tool. This favours a product that starts from a named business problem and from controls. [I]

## 9. What this means for Neuron

1. **Do not build what has become a commodity:** connectors, a general gateway, a fleet control tower.
2. **Match the converged architecture in miniature:** a registry of applications and capabilities, one policy point, a credential broker, an audit record. These are table stakes, and section 2 shows public references for each.
3. **Assume the application will increasingly bring its own MCP server.** Neuron's value moves from "connect" to "act safely for this user across what is connected".
4. **Lead with what is already strong and uncommon:** deterministic enforcement, taint tracking, self-hosting under an Apache-2.0 licence.
5. **Research gaps to close before decisions that depend on them:** primary documentation for Dynamics 365, HubSpot, Informatica, Elastic, Coveo, NVIDIA, Cloudflare and Palo Alto; the full OWASP agentic list; Restate's and Cerbos's licences; current prices from vendor pages.

## 10. Sources

Secondary sources are marked †.

**Platforms**
- [Microsoft: Copilot Studio and Entra Agent ID](https://www.microsoft.com/en-us/microsoft-copilot/blog/?p=6424)
- [Microsoft: connecting agents with MCP and A2A](https://azure.microsoft.com/en-us/blog/agent-factory-connecting-agents-apps-and-data-with-new-open-standards-like-mcp-and-a2a/)
- [Microsoft Foundry Agent Service at Build 2026](https://devblogs.microsoft.com/foundry/agent-service-build2026/)
- [Copilot Studio pricing](https://dupple.com/learn/microsoft-copilot-studio-pricing) †
- [Agent 365 pricing](https://rencore.com/en/blog/understanding-microsoft-agent-365-pricing) †
- [AWS: AgentCore generally available](https://aws.amazon.com/about-aws/whats-new/2025/10/amazon-bedrock-agentcore-available)
- [AWS: AgentCore Policy generally available](https://aws.amazon.com/about-aws/whats-new/2026/03/policy-amazon-bedrock-agentcore-generally-available)
- [AWS: Okta Cross App Access with AgentCore](https://aws.amazon.com/blogs/machine-learning/govern-ai-agent-access-with-okta-cross-app-access-and-amazon-bedrock-agentcore-part-2/)
- [Google: Gemini Enterprise technical guide](https://services.google.com/fh/files/misc/25952_grdg_enterprise_technical_guide_ebook_final.pdf)
- [Google Cloud Next 2026 coverage](https://thenextweb.com/news/google-cloud-next-ai-agents-agentic-era) †
- [IBM: Agentic Control Plane](https://www.ibm.com/new/announcements/introducing-the-agentic-control-plane)
- [IBM ContextForge](https://github.com/ibm/mcp-context-forge)
- [Databricks: Agent Bricks](https://www.databricks.com/blog/agent-bricks-dais-2026)
- [Palantir: action types](https://www.palantir.com/docs/foundry/action-types/overview/)

**Application vendors**
- [MuleSoft Agent Fabric overview](https://docs.mulesoft.com/general/agent-fabric-overview)
- [Salesforce Architects: Agent Fabric deep dive](https://architect.salesforce.com/fundamentals/mulesoft-agent-fabric-deep-dive)
- [MuleSoft A2A support](https://www.mulesoft.com/platform/ai/a2a-support)
- [Agentforce Flex Credits](https://www.constellationr.com/insights/news/salesforce-revamps-agentforce-pricing-flex-credits-what-you-need-know) †
- [ServiceNow: AI Control Tower launch](https://www.businesswire.com/news/home/20250506205072/en)
- [ServiceNow Action Fabric](https://www.reworked.co/digital-workplace/servicenow-launches-action-fabric-major-overhaul-of-ai-control-tower/) †
- [SAP Joule workflows](https://www.cio.com/article/4240684/sap-wants-joule-to-run-business-workflows-not-just-answer-questions.html) †
- [Oracle Fusion Agentic Applications](https://www.oracle.com/anz/news/announcement/oracle-introduces-fusion-agentic-applications-2026-03-24/)
- [Workday Agent Gateway and Partner Network](https://newsroom.workday.com/2025-06-03-Workday-Announces-New-AI-Agent-Partner-Network-and-Agent-Gateway-to-Power-the-Next-Generation-of-Human-and-Digital-Workforces)
- [Workday Agent System of Record](https://blog.workday.com/en-us/managing-ai-powered-future-of-work.html)
- [Workday and Pipedream](https://www.techzine.eu/blogs/applications/137466/workdays-platform-ai-transformation-with-pipedream-sana-and-flowise) †
- [Glean connectors](https://docs.glean.com/connectors/about)
- [Glean indexing permissions](https://developers.glean.com/libraries/indexing-sdk/permissions)

**Integration and automation**
- [Workato Enterprise MCP](https://www.workato.com/the-connector/workato-mcp/)
- [Workato product update, January 2026](https://www.workato.com/product-hub/product-scoop-january-2026/)
- [Boomi product update, September 2026](https://boomi.com/product-updates/sep-2026/)
- [Boomi Agent Control Tower](https://boomi.com/resources/resources-library/agent-control-tower/)
- [Kong MCP OAuth2 policy](https://developer.konghq.com/ai-gateway/policies/ai-mcp-oauth2/)
- [Kong secure MCP gateway cookbook](https://developer.konghq.com/cookbooks/secure-internal-mcp-gateway/)
- [WSO2 Identity Server: MCP](https://is.docs.wso2.com/en/next/guides/agentic-ai/mcp/)
- [WSO2 Agent Manager](https://infoq.com/news/2026/09/ws02-agent-manager) †
- [Nango on open-source integration platforms](https://nango.dev/blog/best-open-source-api-integration-platforms-for-ai-agents)
- [Composio on agent authentication platforms](https://composio.dev/content/ai-agent-authentication-platforms)
- [agentgateway](https://agentgateway.dev/docs/about/introduction)
- [Microsoft MCP Gateway](https://microsoft.github.io/mcp-gateway/)
- [n8n review](https://www.eesel.ai/blog/n8n-review) †
- [UiPath agentic platform](https://siliconangle.com/2025/04/30/uipath-plunges-agentic-ai-development-orchestration-platform/) †
- [Automation Anywhere 2026 platform](https://automationanywhere.com/company/press-room/automation-anywhere-unveils-2026-platform-enhancements-run-ai-driven-processes)
- [Pega Agentic Process Fabric](https://www.businesswire.com/news/home/20250602953139/en/pega-agentic-process-fabric-reliably-orchestrates-end-to-end-ai-automation)
- [Arazzo specification deep dive](https://swagger.io/blog/the-arazzo-specification-a-deep-dive/)
- [Arazzo and MCP](https://nordicapis.com/how-arazzo-could-help-mcp-servers-orchestrate-apis-for-ai-consumers/) †

**Security, standards and infrastructure**
- [MCP enterprise-managed authorization explained](https://workos.com/blog/mcp-enterprise-managed-authorization-id-jag) †
- [MCP's enterprise authorization layer](https://thenewstack.io/mcp-gets-its-missing-enterprise-authorization-layer/) †
- [Linux Foundation: A2A at one year](https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year)
- [CNCF: OpenFGA incubating](https://www.cncf.io/blog/2025/11/11/openfga-becomes-a-cncf-incubating-project/)
- [OPA after Styra](https://cloudnativenow.com/editorial-calendar/best-of-2025/apple-buys-styra-brains-opa-remains-open-2/) †
- [OpenBao adoption](https://www.techtarget.com/searchitoperations/news/366644831/Nvidia-adopts-OpenBao-open-source-fork-of-HashiCorps-Vault) †
- [OpenBao 2.7](https://infoq.com/news/2026/11/vault-fork-openbao-27) †
- [Palo Alto and CyberArk](https://www.constellationr.com/research/blog/platform-story-meets-privilege-reality-cyberark-palo-altos-missing-control-plane) †
- [Identity vendors and agent security](https://guptadeepak.com/identity-giants-bought-ai-agent-security/) †
- [OWASP agentic risks and MCP attacks](https://www.penligent.ai/hackinglabs/ja/agentic-security-initiative-securing-agent-applications-in-the-mcp-era/) †
- [DBOS: durable workflow comparison](https://www.dbos.dev/blog/durable-execution-coding-comparison)
- [DBOS and Temporal](https://dbos.dev/compare/dbos-vs-temporal)
- [MIT pilot failure report explained](https://ai2.work/blog/mit-says-95-of-ai-pilots-fail-the-enterprise-reality-check-explained) †
