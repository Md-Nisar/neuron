# Enterprise Domain Adaptation Strategy

| | |
| --- | --- |
| Date | 2026-11-10 |
| Package | Document 6 of 14 |
| Evidence | External references are in document 2. The design is mine [I] and is untested. Section 9 says how to test it. |

## 1. The problem

Neuron must work with a CRM, an HR system and a hospital system without a hand-built agent for each, and without confusing them. A customer is not a patient. A purchase order is not a prescription. An employee is not an account holder.

Two failure modes to avoid:

- **Over-generalising.** Treating every "person-like" record as the same thing, so the agent applies CRM habits to patient data.
- **Over-building.** Requiring an ontology project before any value appears. Palantir's Ontology shows the power of a full semantic layer and also its cost: modelling work led by specialists [I, from its high-touch delivery model].

## 2. What can be discovered, and what cannot

"Discover the application automatically" covers two different things.

| Layer | Can a machine discover it? | From what | Reliability |
| --- | --- | --- | --- |
| **Technical interface:** endpoints, parameters, types, authentication scheme | Yes | OpenAPI, GraphQL introspection, MCP tool lists | High when a specification exists and is current. Many internal APIs have none, or an outdated one. |
| **Data model:** entities, fields, required values, enumerations | Mostly | Schemas in the specification; sample responses | Medium. Field names like `status2` or `flag_a` carry no meaning. |
| **Relationships** between entities | Partly | Foreign-key-like field names, nested paths, link objects | Medium to low. Usually needs confirmation. |
| **Permissions** | Rarely | OAuth scopes in the specification | Low. Row and field rules live in application code. Discovered only by calling as a given user. |
| **Business operations:** "approve a leave request" as opposed to `PATCH /leaves/{id}` | Partly | Operation summaries, user documentation | Medium with documentation, low without. |
| **Business meaning and rules:** what "active customer" means, when a refund is allowed | No | Only from people and documents | Requires human input. |
| **Workflows:** the usual order of operations | Partly | Documentation; Arazzo files where they exist (rare) | Low. |

**Conclusion.** A model can produce a good *draft* of an application's description from its specification and documents. A person who knows the application must review it. The design goal is to make that review fast, not to remove it.

## 3. Approaches considered

| Approach | What it is | Strength | Weakness | Verdict |
| --- | --- | --- | --- | --- |
| **Hardcoded agent per industry** | Prompts and tools written for "healthcare", "banking" | Works well for the cases anticipated | The thing the vision rules out; does not match any real customer's configuration | Reject |
| **Prompt-only adaptation** | Paste documentation into the system prompt | Trivial | Unbounded context, no structure to test or version, no place for rules | Reject as the mechanism; fine as one input |
| **Full ontology or knowledge graph** | A typed graph of all entities and relations across applications, in a graph database | Precise cross-application reasoning | Heavy to build and maintain; new infrastructure; value arrives late | Defer. Reconsider when a customer has more than about ten connected applications with real cross-links |
| **Semantic layer in the analytics sense** | Governed definitions of measures and dimensions | Proven for reporting questions | Covers reading aggregates, not actions | Borrow the idea for measures inside a domain pack |
| **Skills** | Folders of instructions loaded on demand (the pattern in Anthropic's agent products, see prior research) | Cheap, composable, progressive loading keeps context small | Unstructured; no entity model | Adopt as the format for instructions |
| **Domain pack** | A versioned, declarative bundle per application: glossary, entity model, capability annotations, instructions, evaluation cases | Structured enough to test and review; plain relational storage | Still needs a human reviewer | **Recommend** |

## 4. The recommended design: domain packs

A domain pack is data. It contains no code. It is stored in Postgres and versioned.

### 4.1 Contents

| Part | What it holds | Example | Used when |
| --- | --- | --- | --- |
| **Namespace** | A short unique prefix for the application | `crm`, `hrms`, `his` | Always |
| **Glossary** | Terms with definitions as this organisation uses them | "Active customer: an account with an order in the last 12 months" | Loaded when the term or its entity appears |
| **Entity model** | Entities, key fields, human-readable field descriptions, data labels per field | `hrms.Employee.salary`: label `restricted` | Loaded for capabilities that touch the entity |
| **Relationships** | Links between entities in the same application | `crm.Contact` belongs to `crm.Account` | With the entity |
| **Identity links** | Declared equivalences across applications, with the key that joins them | `crm.Account.erp_customer_no` = `erp.Customer.number` | Cross-application runs |
| **Capability annotations** | Business name and guidance per capability: when to use it, preconditions, what must be confirmed | "Submit leave request: check the balance first" | With the capability |
| **Measures** | Named, approved queries for reporting questions | "Open pipeline value" = a specific list call and sum | Reporting questions |
| **Rules of conduct** | Domain constraints stated for the model, each backed by a policy rule where it is enforceable | "Never state a diagnosis" | Always for that namespace |
| **Evaluation cases** | Questions and tasks with expected capability calls and answer criteria | "What is my leave balance?" must call `hrms.get_leave_balance` for the asker only | At verification and in CI |

### 4.2 Layers

Packs compose in three layers, later ones overriding earlier ones:

1. **Application pack:** describes the application product itself. Reusable by every organisation that runs the same product. Can be shared in a public repository.
2. **Organisation overlay:** this organisation's vocabulary, custom fields, measures and rules.
3. **Department overlay (optional):** narrower terms and defaults.

An optional **industry starter** is nothing more than a set of glossary entries and rules of conduct that a new application pack can copy from. It is content, kept outside the core.

### 4.3 How concepts stay distinct

| Rule | Effect |
| --- | --- |
| Every entity is namespaced | The agent sees `crm.Customer` and `his.Patient`. They are different types with different fields, labels and rules. No shared "Person" type exists unless someone declares it. |
| Cross-application equivalence is declared, never inferred | "The same organisation" in CRM and ERP exists only as an identity link with a named key, added by a person. Without a link, the agent is instructed to say it cannot match records and to ask. |
| Data labels travel with fields | `his.Patient.*` is labelled as health data. The policy engine uses the label regardless of what the model thinks the field is. |
| Rules of conduct attach to the namespace | Hospital rules load only when hospital capabilities are in play. |
| Homonyms are surfaced | When two loaded packs define the same term differently ("account" in CRM and in banking), both definitions are shown with their namespaces. |

### 4.4 How a pack reaches the model

Loading everything would exhaust the context. The pattern is progressive disclosure, as in the prior research on skills and tool search:

1. **Always in context:** one short paragraph per connected application (what it is, what it is for), and the rules of conduct of any namespace whose capabilities are selected.
2. **On capability selection:** the selected capabilities' annotations and the entity descriptions they touch.
3. **On demand:** a `describe` capability the model can call for a glossary term, an entity or a measure.

The system prompt prefix stays stable across runs; pack content is appended, which preserves provider-side prompt caching (prior research, Manus and Codex findings).

## 5. Converting discovered capabilities into agent tools

An API with five hundred operations cannot become five hundred tools. The pipeline:

| Stage | Action | Who |
| --- | --- | --- |
| 1. Import | Parse the specification. One candidate per operation. Pin the hash. | Deterministic |
| 2. Filter | Drop deprecated, administrative and bulk-destructive operations by default. | Deterministic defaults, reviewer overrides |
| 3. Group | Cluster candidates by entity and propose business names. | Model drafts |
| 4. Describe | Write the model-facing description: purpose, when to use, when not to. | Model drafts from summaries and documentation |
| 5. Classify | Risk class from method and path, data labels from field names. Classification may only be raised automatically, never lowered. | Deterministic first, model suggests raises |
| 6. Simplify | Hide parameters the agent should not set (internal flags, tenant ids). Bind identity parameters (the user's id) from the principal, not from the model. | Reviewer |
| 7. Review | Enable capabilities one by one or by group. | Reviewer |
| 8. Test | Each enabled capability gets at least one evaluation case. | Reviewer, with drafted cases |

At run time, capabilities are selected per run:

- An agent definition names a capability set (by application, entity or tag).
- If the set is large, only a search capability and the most-used entries are loaded, and the rest are found through catalogue search. Tool definitions are added between runs or as deferred definitions, not swapped mid-run (prior research, section 6).

**Composite capabilities.** Where a business operation always needs the same two or three calls (look up the id, then update), define it once as a composite with a fixed sequence, in the manifest. The OpenAPI Initiative's Arazzo format describes such sequences and is a reasonable interchange format to accept [S]. It is rare in the wild today, so Neuron should not depend on receiving it.

## 6. Enterprise context and knowledge layer

What the agent needs to know, and where each piece comes from:

| Context | Source | Delivered |
| --- | --- | --- |
| Application context | Application pack | Summary always; detail on selection |
| Business entity context | Entity model; live reads through capabilities | On demand |
| User context | Token claims (name, department, roles); the user's own record in an application through a capability bound to the principal | At run start (claims); on demand (record) |
| Department and organisation context | Organisation directory; overlays | At run start |
| Document knowledge | Knowledge Engine, with sharing by group | Through the search capability, cited |
| Operational history | Thread history; prior run summaries; audit for "what did the agent do" | Thread history at run start; rest on demand |
| Cross-application relationships | Identity links | With cross-application runs |

**Preserving source permissions:**

- **Application records** are never copied. They are read live with the user's credential, so the application enforces its own rules.
- **Documents** in the Knowledge Engine are filtered by the grants table (which exists in the schema and is unused today) joined to the user's groups, in SQL and by row-level security, as now.
- **Documents synced from an external source** (later) must carry the source's access list and be re-synced on a stated interval. Until that exists, shared bases are populated only by upload, with explicit grants.
- **Domain packs** themselves can be sensitive (salary field descriptions are not; a glossary of unreleased products might be). Overlays inherit the organisation boundary; department overlays are visible to that department.

## 7. Agent capability layer

How agents are created and configured without code:

| Concept | Definition |
| --- | --- |
| **Agent definition** | A versioned record: name, owner, purpose, instructions, capability set, knowledge bases, model choice, limits (steps, tokens, time), approval overrides (may only tighten). |
| **Agent template** | A definition with placeholders: "application assistant" (read plus low-risk writes on one application), "service desk", "cross-application investigator". Shipped as content. |
| **Specialisation** | Achieved by capability set and pack selection, not by separate code paths. |
| **Reusable skills** | Instruction modules (how to write a status summary, how to handle a refund request) referenced by definitions. |
| **Dynamic tool selection** | Section 5. |
| **Sub-agent delegation** | Deferred. The prior research supports only a read-only, context-isolated sub-agent, behind an evaluation. Not needed for the first three use cases. |
| **Model selection** | Per definition, within an operator allow-list. Cheap model for classification and titles, stronger model for planning. |
| **Lifecycle** | Draft, published, deprecated, retired. A run records the definition version it used. |

A default agent per application can be generated at publish time from the "application assistant" template, so a newly onboarded application is usable immediately.

## 8. Model-assisted drafting, safely

Drafting packs and descriptions with a model saves most of the onboarding time, and it introduces a risk: the specification and documentation are untrusted input, and a poisoned description would be loaded into every future run.

Controls:

1. Drafting runs as an offline job with no capabilities. It can only produce text.
2. Drafts are stored as drafts. Activation is a human action recorded in the audit ledger.
3. Activated pack text is treated like tool definitions: pinned by hash, and changes require re-review.
4. Pack text is framed in context as configuration from the operator, and it is scanned for instruction-like content at review time. It never raises privileges: policy is separate data.

## 9. How to test whether the design works

The claim "domain-agnostic" is tested by distance between domains and by absence of core changes.

| Test | Pass condition |
| --- | --- |
| Three applications from different domains (CRM, HR, a cross-application finance flow) | All run on one core version with only manifests, packs, policies and agent definitions differing |
| Homonym test | With CRM and a banking-style application loaded, a question about "the account" is answered with a clarification or the right namespace, per evaluation cases |
| Leakage test | Rules of conduct and restricted labels from one namespace do not apply to, or leak into, another |
| No-link test | Without an identity link, the agent refuses to match a CRM customer to an ERP customer by name alone |
| Cold onboarding | The acceptance criterion in `DOMAIN_AGNOSTIC_INTEGRATION_ARCHITECTURE.md`, section 14 |
| Draft quality | Share of drafted descriptions accepted without edits, recorded per onboarding. This number says how much the model-assisted step really saves. |

## 10. What is deliberately left out

- A graph database. Relationships and identity links fit in relational tables at the expected scale (tens of applications, hundreds of entities).
- Automatic entity resolution across applications. Matching records by similarity is error-prone and consequential.
- Fine-tuning a model per domain.
- A marketplace for packs. A public repository of application packs is enough until there is a community.
