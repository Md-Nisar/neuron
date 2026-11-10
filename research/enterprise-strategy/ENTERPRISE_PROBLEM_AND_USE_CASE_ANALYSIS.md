# Enterprise Problem and Use Case Analysis

| | |
| --- | --- |
| Date | 2026-11-10 |
| Package | Document 3 of 14 |
| Evidence | This document is analysis [I], informed by the product research in document 2. No customer interviews were done. Benefits are stated without numbers because none were measured. |

## How to read this document

Section 2 lists thirty problems as cards. Each card names the split of work between three kinds of actor:

- **D** deterministic code, rules or the application's own workflow
- **A** agent reasoning
- **H** a human decision

Ratings:

- **Automation suitability:** High (the agent can complete most cases after a confirmation), Medium (the agent prepares, a person decides), Low (mostly rules or people; the agent adds little).
- **Complexity** for Neuron: S, M, L, relative to each other.
- **Priority:** P0 to P3, by value to the recommended positioning and by how early the roadmap can support it. P0 problems are the first three use cases.

## 1. What the thirty problems have in common

Before the list, the patterns that matter for the architecture:

1. **Most value sits in reading across systems, not in writing.** Twelve of the thirty (1, 2, 3, 9, 12, 13, 14, 16, 19, 26, 27, 28) are lookup, summary, investigation or drafting with no write, or with a single draft handed to a person. Most of the rest are the same reading work followed by one write. Reads are also the safest place to start.
2. **Writes are usually one small, well-defined action** at the end of a long reading task: create a ticket, add a note, submit a request, post a credit note.
3. **The approval usually already exists in a system of record.** Neuron should submit into that process, and add its own approval only where none exists.
4. **Identity matching across systems is the hard part of every cross-application problem.** "The same customer" in CRM, ERP and helpdesk needs a declared key.
5. **Three problems need no agent at all** (8, 15, 30 are mostly rules, statistics or screen automation). They are listed so the roadmap does not chase them.

## 2. The thirty problems

### A. Knowledge and information

**1. Information scattered across applications**
- Departments: all. Applications: CRM, ERP, helpdesk, project tool.
- Manual today: open three systems, search each, copy into a message.
- Agentic workflow: A plans lookups; D executes scoped API reads under the user's credential; A answers with links to each record.
- Integrations: read APIs of each application. Data: record identifiers, cross-application keys.
- Security: user-delegated credentials; no cached copies of records.
- Benefit: less time per lookup; fewer wrong answers from stale copies.
- Suitability: High. Approval: none (read-only). Complexity: M. Priority: P0.

**2. Policy and procedure questions**
- Departments: HR, IT, finance, legal. Applications: document stores, intranet, HRMS.
- Manual today: ask a colleague or search a shared drive.
- Agentic workflow: A retrieves from shared knowledge bases with citations; where the answer depends on the person (their leave policy), D reads their record.
- Integrations: Knowledge Engine with sharing; HRMS read. Data: policy documents, employee attributes.
- Security: document access by group; employee data only for the asker.
- Benefit: fewer repetitive queries to HR and IT staff.
- Suitability: High. Approval: none. Complexity: S (the Knowledge Engine exists; sharing does not). Priority: P0.

**3. Recurring report preparation**
- Departments: operations, finance, sales management. Applications: ERP, CRM, project tool.
- Manual today: export, paste into a spreadsheet, write commentary.
- Agentic workflow: D runs saved queries on a schedule; A writes commentary and flags changes; H reviews before distribution.
- Integrations: read APIs, scheduler. Data: aggregates, prior reports.
- Security: the report runs as its owner; recipients must be entitled to the content.
- Benefit: hours per report cycle returned.
- Suitability: Medium. Approval: owner review before sending. Complexity: M (needs scheduled runs). Priority: P2.

**4. Extracting document content into systems**
- Departments: finance, operations, claims. Applications: ERP, document management, claims system.
- Manual today: read a PDF, retype fields.
- Agentic workflow: D parses the document; A maps fields to the target entity and marks low-confidence values; H confirms; D writes once.
- Integrations: document parser (exists), target create API. Data: document, entity schema.
- Security: uploaded files are untrusted; the write needs confirmation.
- Benefit: less keying; fewer transcription errors.
- Suitability: Medium. Approval: user confirmation of extracted values. Complexity: M. Priority: P1.

**5. Inconsistent records across systems**
- Departments: operations, finance, data stewardship. Applications: CRM, ERP, billing.
- Manual today: found by accident, fixed by email.
- Agentic workflow: D compares records by declared keys; A explains each mismatch and proposes the correction; H decides which system is right.
- Integrations: read APIs of both systems, update API of one. Data: key mappings.
- Security: corrections are writes to master data; steward approval.
- Benefit: fewer downstream errors (wrong address, wrong price).
- Suitability: Medium. Approval: data steward. Complexity: L. Priority: P3.

### B. Operations

**6. Purchase request to purchase order**
- Departments: every requester, procurement, finance. Applications: ERP or procurement, vendor master, budget.
- Manual today: fill a form, wait, answer clarifying emails.
- Agentic workflow: A turns a plain request into a structured requisition; D checks budget and preferred vendor; D submits into the ERP's approval workflow; A reports status.
- Integrations: ERP requisition API, vendor and budget reads. Data: catalogue, cost centres.
- Security: requester's own ERP permissions; amount thresholds stay in the ERP.
- Benefit: shorter request cycle; fewer incomplete requisitions.
- Suitability: Medium. Approval: user confirms; the ERP's approvers approve. Complexity: M. Priority: P1.

**7. Invoice exception handling**
- Departments: accounts payable. Applications: ERP, procurement, email.
- Manual today: a clerk investigates why invoice, order and receipt disagree.
- Agentic workflow: D detects the mismatch; A gathers the order, receipt and correspondence and proposes a cause and resolution; H decides; D posts.
- Integrations: ERP reads and posting, event or queue of exceptions. Data: three-way match records.
- Security: financial posting; separation of duties.
- Benefit: faster exception clearing; payment discounts kept.
- Suitability: Medium. Approval: accounts payable approver; second approver above a threshold. Complexity: L. Priority: P2.

**8. Reconciliation**
- Departments: finance. Applications: ERP, bank feeds.
- Manual today: matching in spreadsheets.
- Agentic workflow: D matches by rule (this is the bulk); A only explains the unmatched remainder.
- Integrations: ERP, bank data. Data: transactions.
- Security: financial data; read-only for the agent.
- Benefit: small beyond what rule-based tools already give.
- Suitability: Low. Approval: n/a. Complexity: M. Priority: P3.

**9. Delayed approvals**
- Departments: all managers. Applications: any with an approval queue.
- Manual today: requesters chase; approvers open each item cold.
- Agentic workflow: D lists pending items; A writes a decision summary for each with the relevant facts; H approves in the source system or through Neuron's inbox.
- Integrations: approval queue APIs. Data: request details, history.
- Security: only the entitled approver sees and decides.
- Benefit: shorter approval latency.
- Suitability: High for the summary. Approval: the approval itself is the human step. Complexity: M. Priority: P1.

**10. Order exception handling**
- Departments: supply chain, customer service. Applications: order management, warehouse, carrier portals.
- Manual today: someone notices a late order, checks systems, emails the customer.
- Agentic workflow: D raises an event on delay; A investigates cause and options; H chooses; D updates the order and notifies.
- Integrations: events, order and shipment APIs. Data: order lines, stock, carrier status.
- Security: customer data; outbound communication needs confirmation.
- Benefit: earlier customer notice; fewer escalations.
- Suitability: Medium. Approval: agent confirmation for changes. Complexity: L. Priority: P2.

**11. Vendor onboarding**
- Departments: procurement, finance, compliance. Applications: vendor master, document management, sanctions screening.
- Manual today: collect documents by email, check completeness, key into ERP.
- Agentic workflow: A checks submitted documents against a checklist and extracts fields; D runs screening; H approves; D creates the vendor.
- Integrations: document parser, ERP vendor API, screening service. Data: tax and bank documents.
- Security: bank details are a fraud target; two-person approval for creation and changes.
- Benefit: shorter onboarding; fewer incomplete files.
- Suitability: Medium. Approval: two-party. Complexity: L. Priority: P3.

### C. Decision-making

**12. Ad-hoc questions over operational data**
- Departments: managers in every function. Applications: ERP, CRM, HRMS reporting APIs.
- Manual today: ask an analyst; wait for a report.
- Agentic workflow: A turns the question into calls to approved, parameterised queries (not free SQL); D executes; A explains the result and its limits.
- Integrations: list and report APIs. Data: the domain pack's definitions of measures.
- Security: row-level limits come from the user's credential.
- Benefit: answers in minutes; analysts freed for harder work.
- Suitability: Medium (wrong aggregates are a real risk). Approval: none. Complexity: M. Priority: P1.

**13. Anomaly investigation**
- Departments: finance, operations, IT. Applications: ERP, monitoring, ticketing.
- Manual today: a person pulls data from several places and forms a theory.
- Agentic workflow: D detects (statistics, not the model); A gathers related records and proposes ranked explanations with evidence; H judges.
- Integrations: read APIs, event trigger. Data: time series, change records.
- Security: read-only.
- Benefit: shorter time to a first hypothesis.
- Suitability: Medium. Approval: none. Complexity: M. Priority: P2.

**14. Account briefing before a meeting**
- Departments: sales, account management, service. Applications: CRM, helpdesk, ERP (orders, invoices).
- Manual today: click through the account in each system.
- Agentic workflow: A compiles open deals, recent tickets, overdue invoices and last contact, each linked to its source.
- Integrations: CRM, helpdesk and ERP reads. Data: account key mapping.
- Security: the briefing contains only what the user can already see.
- Benefit: preparation time; fewer surprises in meetings.
- Suitability: High. Approval: none. Complexity: S to M. Priority: P0.

**15. Forecasting**
- Departments: finance, supply chain. Applications: ERP, planning tools.
- Manual today: statistical tools and judgement.
- Agentic workflow: none worth building. A can explain a forecast produced elsewhere.
- Suitability: Low. Complexity: n/a. Priority: not planned.

### D. Customer-facing

**16. Support ticket triage and draft reply**
- Departments: customer support. Applications: helpdesk, knowledge base, CRM.
- Manual today: read, classify, look up the customer, write a reply.
- Agentic workflow: D triggers on a new ticket; A classifies, retrieves relevant articles and account context, drafts a reply; H edits and sends.
- Integrations: helpdesk webhook and API, knowledge base. Data: ticket text (untrusted), articles.
- Security: ticket content is attacker-controlled; the run is tainted from the start.
- Benefit: handling time; consistency.
- Suitability: High for drafting. Approval: agent sends. Complexity: M. Priority: P1.

**17. Complaint resolution across systems**
- Departments: customer service, finance, logistics. Applications: helpdesk, CRM, ERP (orders, invoices, credit notes).
- Manual today: an agent checks the order, the delivery and the invoice, asks a supervisor, issues a credit, updates three systems.
- Agentic workflow: A assembles the case and proposes a resolution within policy; D applies thresholds; H approves; D posts the credit note, updates the ticket and logs a CRM note, each step idempotent.
- Integrations: helpdesk events, CRM, ERP posting. Data: customer key mapping, refund policy.
- Security: financial write; approval tier by amount; separation of duties.
- Benefit: resolution time; fewer hand-offs.
- Suitability: Medium. Approval: supervisor above a threshold. Complexity: L. Priority: P0 (the cross-application validation case).

**18. Customer onboarding with document checks**
- Departments: operations, compliance (banking, insurance). Applications: core system, document management, identity verification.
- Manual today: collect and check documents, re-request missing ones.
- Agentic workflow: A checks completeness and consistency, drafts follow-up requests; D runs verification services; H makes the compliance decision.
- Integrations: document parser, core system API, verification services.
- Security: regulated personal data; the compliance decision must stay human.
- Benefit: shorter onboarding.
- Suitability: Medium. Approval: compliance officer. Complexity: L. Priority: P3.

**19. Service request status and follow-up**
- Departments: customer service, field service. Applications: helpdesk, order management.
- Manual today: customers call; staff look it up.
- Agentic workflow: A answers status from the systems of record and drafts proactive updates.
- Integrations: read APIs; outbound channel.
- Security: if customer-facing, the caller must be authenticated as the customer. Neuron today serves employees only.
- Benefit: fewer status calls.
- Suitability: High. Approval: none for status. Complexity: M. Priority: P2.

**20. Insurance claim intake**
- Departments: claims. Applications: claims system, policy administration, documents.
- Manual today: an adjuster keys the notice, checks cover, requests documents.
- Agentic workflow: A structures the notice, D checks policy cover by rule, A lists missing items; H decides.
- Integrations: claims and policy APIs, document parser.
- Security: personal and sometimes health data.
- Benefit: faster first response.
- Suitability: Medium. Approval: adjuster. Complexity: L. Priority: P3.

### E. Employee productivity

**21. HR self-service queries and requests**
- Departments: all employees, HR. Applications: HRMS, policy documents.
- Manual today: email HR or navigate the HR portal.
- Agentic workflow: A answers from the employee's own record and policy; for a leave request, A fills it, H confirms, D submits into the HRMS workflow.
- Integrations: HRMS API with employee-scoped access; knowledge base.
- Security: an employee sees only their own record; managers only their reports; salary fields restricted.
- Benefit: HR query volume.
- Suitability: High. Approval: user confirmation; the manager approves in the HRMS. Complexity: M. Priority: P0.

**22. Employee onboarding**
- Departments: HR, IT, payroll, facilities. Applications: HRMS, identity provider, ITSM, payroll.
- Manual today: a checklist spread over tickets and emails.
- Agentic workflow: D triggers on a new hire record and runs the fixed checklist; A handles the exceptions (missing data, non-standard role) and reports progress; H approves access grants.
- Integrations: HRMS events, IdP provisioning, ITSM ticket API.
- Security: granting access is high impact; role-to-access mapping is policy, not model judgement.
- Benefit: day-one readiness.
- Suitability: Medium (mostly deterministic). Approval: IT or manager for access. Complexity: L. Priority: P2.

**23. IT service desk requests**
- Departments: all employees, IT. Applications: ITSM, IdP, software catalogue.
- Manual today: raise a ticket, wait.
- Agentic workflow: A answers from the knowledge base or creates a complete ticket; D fulfils catalogue items that policy allows.
- Integrations: ITSM API, knowledge base.
- Security: access changes follow the ITSM approval.
- Benefit: ticket deflection.
- Suitability: High. Approval: per catalogue item. Complexity: M. Priority: P1. Note: the most crowded use case in the market.

**24. Meeting follow-up into tasks**
- Departments: all. Applications: project tool, calendar, notes.
- Manual today: someone writes actions and creates tasks.
- Agentic workflow: A extracts actions from notes; H confirms; D creates tasks.
- Integrations: project tool API.
- Security: low.
- Benefit: small per meeting, frequent.
- Suitability: High. Approval: user confirmation. Complexity: S. Priority: P2. Note: collaboration suites already do this.

**25. Employee offboarding**
- Departments: HR, IT, security. Applications: HRMS, IdP, each application's user administration.
- Manual today: a checklist; missed accounts are common.
- Agentic workflow: D triggers and runs the checklist; A finds accounts the checklist does not know by matching identities across applications and reports them; H confirms removal.
- Integrations: user administration APIs.
- Security: needs administrative credentials, so a dedicated agent with narrow scope and admin approval.
- Benefit: fewer orphaned accounts.
- Suitability: Medium. Approval: administrator. Complexity: L. Priority: P3.

### F. Technical and IT operations

**26. Incident investigation**
- Departments: IT operations, engineering. Applications: monitoring, logs, ITSM, deployment history.
- Manual today: an engineer queries several tools under time pressure.
- Agentic workflow: D triggers on an alert; A gathers recent changes, related alerts and matching runbooks and proposes likely causes; H acts.
- Integrations: monitoring and log query APIs (often through vendor MCP servers), ITSM.
- Security: read-only by default; logs can contain attacker-controlled text.
- Benefit: time to first hypothesis.
- Suitability: Medium. Approval: any remediation. Complexity: M. Priority: P2. Note: observability vendors ship this themselves.

**27. Change request preparation**
- Departments: IT. Applications: ITSM, configuration database.
- Manual today: write the description, impact and rollback by hand.
- Agentic workflow: A drafts from the change details and affected items; H edits; D submits into the change process.
- Integrations: ITSM API.
- Security: low; the change board still approves.
- Benefit: better-prepared changes.
- Suitability: High. Approval: user confirmation. Complexity: S. Priority: P2.

**28. Access review support**
- Departments: security, managers, audit. Applications: IdP, application user lists.
- Manual today: managers approve long lists without context.
- Agentic workflow: D compiles entitlements; A highlights unusual or unused access with reasons; H certifies.
- Integrations: user administration reads.
- Security: administrative read access; no write.
- Benefit: more meaningful reviews.
- Suitability: Medium. Approval: the certification is the human step. Complexity: M. Priority: P3.

### G. Domain validation and legacy

**29. Hospital administrative coordination (non-clinical)**
- Departments: front desk, scheduling, billing. Applications: hospital management system, billing.
- Manual today: staff look up appointments, eligibility and bills in separate screens.
- Agentic workflow: A answers staff questions about appointments and billing status and prepares rescheduling; H confirms.
- Integrations: hospital system API (often HL7 FHIR). Data: appointments, encounters.
- Security: protected health information; clinical decisions excluded; minimum-necessary access; no payload logging.
- Benefit: staff time.
- Suitability: Medium. Approval: user confirmation for any change. Complexity: L. Priority: P2 as a domain-distance test, P3 commercially.

**30. Work in a legacy application with no API**
- Departments: any. Applications: terminal, desktop or old web applications.
- Manual today: staff key data into screens.
- Agentic workflow: none inside Neuron. An RPA robot or a database view exposed as a tool can be called by the agent.
- Integrations: RPA vendor API, or a read-only database adapter.
- Security: robots usually run with shared credentials; treat as an elevated connection.
- Benefit: depends entirely on the wrapper.
- Suitability: Low. Approval: user confirmation. Complexity: L. Priority: P3.

## 3. Priority summary

| Priority | Problems | Why |
| --- | --- | --- |
| P0 | 1, 2, 14, 17, 21 | Together they form the first three use cases (`FIRST_THREE_ENTERPRISE_USE_CASES.md`): read across systems, document plus record answers, one cross-application write with approval. |
| P1 | 4, 6, 9, 12, 16, 23 | High frequency, one application each, modest writes. They reuse what the P0 cases build. |
| P2 | 3, 7, 10, 13, 19, 22, 24, 26, 27, 29 | Need scheduling, events or deeper workflows, or are well served by incumbents. |
| P3 | 5, 8, 11, 18, 20, 25, 28, 30 | Regulated decisions, administrative credentials, or little need for an agent. |
| Not planned | 15 | Not an agent problem. |

## 4. Where deterministic logic, approvals and reasoning coexist

One rule covers all thirty cards:

| Part of the work | Who does it |
| --- | --- |
| Detecting that something happened (a new record, a threshold crossed, a mismatch) | Deterministic: an event from the application or a rule |
| Finding and reading the relevant records | Deterministic calls, chosen by the agent |
| Interpreting, explaining, drafting, proposing | Agent |
| Deciding whether an amount, role or policy allows the action | Deterministic policy |
| Deciding to proceed with a consequential action | Human |
| Executing the action exactly once | Deterministic, with an idempotency key |

A design that puts the model in the third row only is easier to secure and to evaluate than one that lets it roam across all six.
