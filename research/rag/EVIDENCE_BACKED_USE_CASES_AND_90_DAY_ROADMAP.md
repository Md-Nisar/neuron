# Enterprise AI Agents — Evidence-Backed Use Cases & 90-Day Roadmap

Oct 18, 2026 · @Md Nisar Ahmed

## Executive summary

**Bottom line:** enterprise AI agents pay off today in narrow, high-volume, knowledge-grounded workflows that have a human fallback. Autonomous agents running end-to-end processes in ERP, finance or procurement are still mostly pilots. Their reported outcomes are almost entirely self-reported by vendors or customers.

We reviewed about 50 named deployments and 30 independent studies, benchmarks and incident reports, published 2022–2026 (mostly 2024–2026). Not one agent outcome metric from a vendor or customer has been independently audited. The strongest causal evidence covers *assistive* AI, not autonomous agents:

- **Customer support:** +14–15% issues resolved per hour across 5,000 agents.
- **Developers:** +26% tasks completed in three field experiments.
- **Microsoft Security and identity tools:** randomized trials, but written by Microsoft.

**What is proven (evidence grade B or better, in production at scale):**

- **Contact-center agent assist.** One peer-reviewed field study; Verizon reports sales by its 28,000 service reps up nearly 40% since deployment.
- **Knowledge assistants for advisors and staff.** Morgan Stanley: 98% of financial-advisor teams adopted. JPMorgan: more than 200,000 LLM Suite users.
- **SOC triage and identity-ops agents.** Microsoft's randomized trials show 22–48% gains in speed or accuracy.
- **Long-tail supplier negotiation.** Walmart with Pactum closed deals with 64–68% of suppliers, at 1.5–3% average savings.

**What is promising but vendor-reported (grade C):**

- **Customer self-service agents** resolve 50–90% of chats without a human (Salesforce, OpenTable, Reddit, Heathrow, Siemens).
- **Legacy-code modernization agents.** Amazon estimates 4,500 developer-years and $260M a year saved.
- **IT service-desk agents.** Mobileye reports about 66% of tickets automated.

**What is mostly claims (grade D):**

- Autonomous finance-close, cash-management, accounts-payable and supply-chain agents.
- Packaged SAP Joule agents, whose figures SAP itself labels estimates. A German SAP user-group survey (DSAG, 2026) found only 3% of members use SAP Business AI productively.

**Counter-evidence a CIO must price in:**

- **Benchmarks:** the best agents complete about 30% of realistic office tasks (TheAgentCompany) and about 35% of multi-turn CRM tasks (CRMArena-Pro).
- **Field experiment:** a 2026 randomized study of 680,676 Taobao customer-service chats found customer ratings *fell* on chats eligible for the AI agent.
- **Reversal:** Klarna began rehiring human agents in 2025 after saying AI did the work of 700.
- **Security:** critical prompt-injection exfiltration flaws were found in all three major platforms in 2025 (EchoLeak, ForcedLeak, GeminiJack).

**Recommendations:**

1. Start with three bounded use cases: contact-center agent assist, an IT service-desk agent with human handoff, and security alert triage. Each has measurable baselines and reversible actions.
2. Fund a shared agent platform before scaling past three use cases. It needs an identity and permissions model, a tool gateway, an evaluation harness, tracing and cost controls.
3. Do not count headcount savings until a 90-day controlled comparison shows them. Measure resolution quality and customer ratings, not only containment.
4. Treat every agent with write access as a privileged identity. Gate irreversible actions behind human confirmation.

## Methodology and evidence grades

Every metric here was taken from a page we opened, not from a search snippet. Executives are named by role only. Where a figure is projected, estimated or correlational, it is labelled that way.

| Grade | Definition | Typical source | How to use it |
| --- | --- | --- | --- |
| A | Independent or peer-reviewed causal study, or a figure in an audited or SEC-filed document | Journal RCTs, 10-K/F-1, SEC-filed investor deck | Can anchor a business case |
| B | Vendor-run RCT, or a company-attributed primary statement with specific metrics | Earnings calls, company press releases, Reuters interviews | Directionally reliable; validate locally |
| C | Vendor case study with metrics, no stated method or baseline | Vendor customer-story pages, vendor blogs | Hypothesis only; expect lower results |
| D | Announcement, target or projection; no measured outcome | Launch releases, "expects" or "up to" claims | Ignore for ROI |

**Status labels:** *Production* means at scale for its stated scope. *Limited* means one channel, region or segment. *Pilot* means a proof of concept or trial. *Claim* means announced only.

**Known biases:**

- **Survivorship.** Vendors publish their wins.
- **Inconsistent definitions.** "Resolution", "deflection" and "supported by AI" are each defined differently, sometimes within one vendor: Salesforce's own help-site resolution rate dropped from 84% to 63% between pages.
- **Platform confounds.** Some gains come from a platform migration rather than from the AI. Microsoft attributes its 31% first-call-resolution gain to moving onto Dynamics 365.

## Top 20 evidence-backed use cases

The table ranks use cases by strength of evidence first, then by business value. Customer service and IT operations dominate the top. ERP, finance and supply-chain agents rank lowest because almost none publish measured outcomes. Grades refer to the best evidence for the use case, not every example in it.

| # | Use case | Domain | Best evidence (org: outcome) | Status | Grade |
| --- | --- | --- | --- | --- | --- |
| 1 | Contact-center agent assist (answers, drafts, summaries) | Customer service | 5,000-agent field study: +14–15% issues resolved per hour, largest gains for novices. Verizon: sales by 28,000 service reps up nearly 40% since deployment. Microsoft CSS: 13% fewer days to solution | Production | A |
| 2 | Firm-wide knowledge assistant on a multi-model gateway | Cross-functional | JPMorgan: >200,000 LLM Suite users, \~100 GenAI solutions in production. McKinsey Lilli: 72% of firm active, "up to 30%" time saved (self-reported) | Production | A−/B |
| 3 | Advisor research and meeting-notes agent | CRM / wealth | Morgan Stanley: 98% of advisor teams adopted; notes saved to Salesforce after advisor review. JPMorgan Coach AI: "up to 95% faster" retrieval | Production | B |
| 4 | SOC investigation copilot | Cybersecurity | Microsoft RCT: experienced analysts 22% faster, 7% more accurate. Observational: 30% lower incident mean time to resolve (89 vs 88 orgs) | Production | B |
| 5 | Phishing / alert triage agent | Cybersecurity | Microsoft RCT (167 analysts): 6.5× true positives per analyst-minute, F1 0.53→0.93; but analysts over-trusted the agent's misses | Production | B |
| 6 | Identity-policy (Conditional Access) optimization agent | Cybersecurity / ITSM | Microsoft RCT (162 admins): +48% accuracy, −43% time | Production | B |
| 7 | Long-tail supplier negotiation agent | Procurement | Walmart + Pactum: deals with 64% (pilot) then 68% of suppliers; 1.5% then 3% average savings; 11-day turnaround | Limited | B+ |
| 8 | Knowledge-grounded customer self-service agent with handoff | Customer service | Salesforce help site: >5M conversations, 63% "resolved instantly". OpenTable 73%; 1-800Accountant 70%; Eneco 40%→67% | Production | C |
| 9 | Transactional service agent (rebook, cancel, schedule) | Customer service | Engine: 50% of chats resolved, CSAT +16%. Klarna: 2.3M chats in first month, then rehired humans for quality | Production | B/C |
| 10 | Voice intent-routing agent replacing keypad phone menus | Customer service | Siemens: 90% of inbound calls resolved or correctly routed. AT&T: \~$150M annual savings. Toyota NA: −20% call handling time | Production | C |
| 11 | Legacy code modernization agent | IT / engineering | Amazon: \~4,500 developer-years and $260M/yr (estimate). Thomson Reuters: 1.5M lines/month, 4× velocity. AWS Transform customers: 700,000 hours | Production | B−/C |
| 12 | Developer coding agents and assistants | IT / engineering | 3 RCTs (4,867 devs): +26% tasks. METR RCT: experienced devs 19% *slower*. JPMorgan: 40K+ engineers equipped | Production | A (mixed) |
| 13 | IT service-desk resolution agent | ITSM | Mobileye: \~66% of tickets automated, response hours→\~1 min. ServiceNow Now on Now: 37% of support workflows end-to-end. BofA: IT desk calls −50% (scripted assistant) | Production | C (BofA B) |
| 14 | Engineering on-call / internal Q&A agent | ITSM | Uber Genie: 70,000+ questions, \~13,000 hours saved, but only 48.9% rated helpful | Production | B− |
| 15 | HR employee self-service agent | HR | Microsoft: 300,000+ users across Workday, SuccessFactors, ServiceNow; 40% deflection is a target only. LC Waikiki: HR cycle times −40–60% (SAP estimate) | Production | C/D |
| 16 | Recruiting screening and scheduling agent | HR | Workday internal: 24,000 hours recovered, recruiter capacity +\~40% (sponsored article) | Production | C/D |
| 17 | Seller and web-sales agents | CRM / sales | Microsoft "Ask Microsoft": up to 70% fewer human-handled chats. Fujitsu: proposals 67% more productive. Lumen: 4 hrs/week, \~$50M (estimate) | Production | C |
| 18 | Shopping and seller-operations agents | Commerce | Amazon Rufus: 250M customers; $10B incremental sales is a projection. Seller Assistant: 230,000 monthly users | Production | B/C |
| 19 | Sourcing / RFP and spend agents | Procurement | Coupa: Xylem "up to 15%" RFP savings; Jabil \~$13M spend-savings value | Production | C |
| 20 | Finance back-office agents (invoice audit, cash, VAT, disputes) | Finance / ERP | Dow freight-invoice audit: "millions" projected (pilot). PwC VAT agent: 60% more efficient (SAP). SAP Cash Mgmt "up to 70%" (estimate) | Pilot / Limited | D |

## Organization case studies

The two sets of SEC filings (JPMorgan, Klarna) and the Walmart negotiation study are the hardest evidence. Most other rows are vendor-published. Each organization name links to the page the figures came from.

### Vendors' own deployments ("customer zero")

| Organization | Platform | What the agent does | Measured outcome (exact) | Status | Source date | Grade |
| --- | --- | --- | --- | --- | --- | --- |
| [Microsoft — Security Copilot RCT](https://www.benedelman.org/randomized-controlled-trial-for-microsoft-security-copilot/) | Security Copilot | Incident summary, script analysis, reports | Experienced analysts "22% faster", "7% more accurate" | Production | Dec 2023, rev. Mar 2024 | B |
| [Microsoft — Phishing Triage Agent RCT](https://arxiv.org/html/2511.13860v1) | Security Copilot agent | Autonomous email-phish verdicts | 6.5× true positives per analyst-minute; F1 0.53→0.93; time on full corpus not significant (p=0.471) | Production | 17 Nov 2025 | B |
| [Microsoft — Conditional Access Agent RCT](https://arxiv.org/html/2511.13865v1) | Entra agent | Identity-policy analysis and merge | Accuracy +48%, time −43% (162 admins) | Production | Oct 2025 | B |
| [Microsoft — Customer support (CSS)](https://news.microsoft.com/wp-content/uploads/prod/sites/658/2024/05/How-Microsoft-is-reinventing-Customer-Service-and-Support-with-Microsoft-Copilot.pdf) | Dynamics 365 + Copilot | Case summaries, drafts, knowledge answers | 13% fewer days to solution; 9% faster first response (9,900 agents, Apr–Sep 2023) | Production | \~May 2024 | C |
| [Microsoft — Employee Self-Service agent](https://www.microsoft.com/insidetrack/blog/deploying-the-employee-self-service-agent-our-blueprint-for-enterprise-scale-success) | Copilot Studio | HR, IT, facilities questions and tickets | Return-to-office content satisfaction 85%→98%; deflection only a 40% target | Production | 12 Mar 2026 | C/D |
| [Microsoft — "Ask Microsoft" sales agent](https://www.microsoft.com/customers/story/26166-microsoft-microsoft-copilot-studio) | Copilot Studio + Foundry | Web pre-sales, cart recovery | "Up to 70%" fewer human-handled chats; +16% Azure trial starts | Production | 27 Feb 2026 | C |
| [Salesforce — help.salesforce.com](https://www.salesforce.com/agentforce/use-cases/customer-zero/) | Agentforce | B2B support self-service, 7 languages | ">5 million" conversations, ">63% resolved instantly" (earlier page said 84%) | Production | Page modified 30 Sep 2026 | C |
| [Salesforce — support headcount](https://www.theregister.com/2025/09/02/salesforce_4000_jobs_ai) | Agentforce | Support workforce effect | CEO: support cut "from 9,000 heads to about 5,000"; disputed by a former employee | Claim | 2 Sep 2025 | D |
| [ServiceNow — Now on Now](https://www.servicenow.com/jp/workflow/now-on-now/next-evolution-customer-self-service.html) | ServiceNow AI Platform | Customer self-service and support cases | "37% of support case workflows end to end"; "$10.5 million in realized AI value" (method not shown) | Production | 7 Apr 2026 | C |
| [Amazon — Java upgrades](https://aws.amazon.com/blogs/devops/amazon-q-developer-just-reached-a-260-million-dollar-milestone) | Q Developer transformation agent | Java 8/11→17 migration | "4,500 years of development work", "$260 million" a year; estimated from proxies | Production | 1 Aug 2024 | C |
| [Amazon — Rufus](https://www.fool.com/earnings/call-transcripts/2025/10/31/amazon-amzn-q3-2025-earnings-call-transcript/) | In-house | Shopping assistant | 250M customers; users "60% more likely" to buy (correlational); ">$10 billion" annualized sales (projected) | Production | 30 Oct 2025 | B |
| [Google — Ads support and sales](https://cxtoday.com/alphabet-bets-on-gemini-ai-customer-experience) | Gemini | Advertiser support | Agents "autonomously address 75% of support queries" (Q2 2026 earnings remark) | Production | 23 Jul 2026 | B−/C |
| [Workday — recruiting](https://diginomica.com/hiring-results-we-measured-when-we-deployed-agentic-ai) | Workday Recruiting Agent | Resume screening, scheduling | 24,000 hours recovered in 9 months; recruiter capacity +\~40% (sponsored) | Production | 29 Jul 2026 | C/D |

### Enterprise customers

| Organization | Platform | What the agent does | Measured outcome (exact) | Status | Source date | Grade |
| --- | --- | --- | --- | --- | --- | --- |
| [JPMorgan Chase](https://www.sec.gov/Archives/edgar/data/19617/000001961725000483/investordaypresentation.htm) | LLM Suite (in-house) | Firm-wide assistant, coding, operations | ">200,000 users"; "\~100 GenAI solutions in production"; operations ">40% productivity vs. 2024" (not attributed to AI alone) | Production | May 2025 | A−/B |
| [Klarna](https://www.sec.gov/Archives/edgar/data/2003292/000162828025012824/klarnagroupplcf-1.htm) | OpenAI | Service chats, refunds, returns | 2.3M chats in month one, "\~700 FTE" equivalent; service and ops cost $240M (2023)→$203M (2024) per F-1, not attributed to AI; [rehired humans](https://www.entrepreneur.com/business-news/klarna-ceo-reverses-course-by-hiring-more-humans-not-ai/491396) May 2025 | Production + human fallback | 2025 | A− (costs) / B |
| [Walmart](https://www.pon.harvard.edu/daily/negotiation-skills-daily/chatbot-negotiations-what-can-ai-do-for-you) | Pactum | Negotiates with long-tail suppliers within set limits | Pilot: 64% of 89 suppliers closed, 1.5% savings, 11 days; expansion: 68%, 3% (HBR data) | Limited | HBR Nov 2022 | B+ |
| [Morgan Stanley](https://www.morganstanley.com/press-releases/ai-at-morgan-stanley-debrief-launch) | OpenAI | Advisor Q&A over \~100K docs; Debrief meeting notes to Salesforce | "98% of Financial Advisor teams" adopted; daily compliance regression tests | Production | 26 Jun 2024 | B |
| [Bank of America](https://newsroom.bankofamerica.com/content/newsroom/press-releases/2025/08/a-decade-of-ai-innovation--bofa-s-virtual-assistant-erica-surpas.html) | Erica (mostly scripted NLU) | Client banking assistant; employee IT help | >3B interactions; IT service-desk calls −50% | Production | 20 Aug 2025 | B |
| [Verizon](https://www.aol.com/news/verizon-says-google-ai-customer-120648406.html) | Google Gemini | Rep assistant over \~15,000 documents | Sales by 28,000-rep service team "up nearly 40%" (no baseline method) | Production | 9 Apr 2025 (Reuters) | B− |
| [AT&T](https://cloud.google.com/customers/att-gemini-enterprise-cx) | Google Gemini CX | Voice and chat agents with 60-day memory | +20% fully automated resolution; \~$150M annual savings | Production (implied) | Date not shown | C |
| [Siemens GBS](https://aws.amazon.com/blogs/contact-center/how-siemens-handles-90-of-calls-autonomously-with-amazon-connect-customer-ai-agents/) | Amazon Connect + AgentCore | Phone intent routing and knowledge answers | "90% of inbound calls autonomously" (resolved or routed; defined two ways) | Production | 7 Jul 2026 | C |
| [Thomson Reuters](https://aws.amazon.com/solutions/case-studies/thomson-reuters-case-study) | AWS Transform | .NET and Windows→Linux modernization | 1.5M lines/month, 4× velocity; 30% cost cut | Production | Updated 15 Oct 2026 | C+ |
| [Mobileye](https://aws-news.com/article/2026-08-05-how-mobileye-transformed-support-operations-using-amazon-bedrock-agentcore) | Bedrock AgentCore | Internal IT and engineering support | \~66% of tickets automated; "98%" accuracy (method not disclosed) | Production | 5 Aug 2026 | C |
| [OpenTable](https://www.salesforce.com/customer-stories/opentable/) | Agentforce | Restaurant and diner service agents | 73% resolution within 3 weeks of launch; 11K conversations/week | Production | 7 Aug 2025 | C |
| [1-800Accountant](https://salesforce.com/customer-stories/1800-accountant/) | Agentforce | Tax questions, appointment booking | 70% autonomous chat resolution; 50% fewer seasonal hires (prior bot: 10%) | Production | 19 Feb 2025 | C/B |
| [Reddit](https://www.salesforce.com/uk/customer-stories/reddit/) | Agentforce | Advertiser support | Chat resolution 8.9→1.4 min; deflection 46% (body text says 33%) | Production | 11 Sep 2025 | C |
| [Engine](https://www.salesforce.com/customer-stories/engine/agentic-service/) | Agentforce + Bedrock | Rebooks flights, cancels hotels and cars | 50% chats resolved; −15% handle time; CSAT +16% | Production | 4 Jun 2026 | C |
| [Heathrow](https://www.salesforce.com/customer-stories/heathrow-airport) | Agentforce | WhatsApp wayfinding and FAQs | "90%" chats without transfer | Production | Oct 2025 / May 2026 (dates conflict) | C |
| [Eneco](https://www.microsoft.com/en/customers/story/22686-eneco-microsoft-copilot-studio) | Copilot Studio | Multilingual web service agent | Resolved without handoff 40%→67%; 24,000 chats/month | Production | 5 Mar 2025 | C |
| [Uber](https://www.infoq.com/news/2024/10/uber-genie-rag-copilot) | In-house RAG (Genie) | Engineering on-call Q&A in Slack | 70,000+ questions; \~13,000 hours; 48.9% helpful | Production | 29 Oct 2024 | B− |
| [McKinsey — Lilli](https://www.mckinsey.com/capabilities/tech-and-ai/how-we-help-clients/rewiring-the-way-mcKinsey-works-with-Lilli) | In-house | Knowledge search and synthesis | 72% of firm active; >500,000 prompts/month; "up to 30%" time saved | Production | Date not shown | B− |
| [McKinsey — LegacyX client bank](https://www.mckinsey.com/about-us/new-at-mckinsey-blog/mckinseys-legacyx-rejuvenating-legacy-infrastructure-with-agentic-ai) | Agent squads (5×25) | SAS risk models→Python | "90%" conversion accuracy, "80%" faster (client unnamed) | Delivered project | 20 Mar 2025 | C |
| [Fujitsu](https://www.microsoft.com/customers/story/21885-fujitsu-azure-ai-foundry) | Azure AI Agent Service | Sales proposal generation | "67% more productive" (no baseline) | Production | 1 Mar 2025 | C |
| [Xylem, Jabil (Coupa)](https://www.coupa.com/newsroom/coupa-delivers-record-revenue-in-q4-with-300b-in-lifetime-customer-savings) | Coupa Navi | Sourcing and RFP agents | Xylem "up to 15%" on RFPs; Jabil \~$13M spend savings | Production | 25 Feb 2026 | C |
| [Aeropuertos Argentina, LC Waikiki (SAP)](https://news.sap.com/?p=246257) | SAP Business AI / Joule | Back office; HR processes | −16% direct cost, −90% admin effort; HR cycle −40–60%; SAP labels all "estimates" | Production (implied) | 20 Jul 2026 | C− |
| [Dow](https://www.microsoft.com/en-us/worklab/ai-impact-at-dow-copilot-identifies-millions-in-cost-savings) | Copilot Studio | Freight invoice anomaly detection | Expects "millions" saved in year one (projected) | Pilot | 13 Nov 2024 | D |
| [Deloitte — Zora AI](https://www.deloitte.com/us/en/about/press-room/deloitte-unveils-zora-ai-agentic-ai-for-tomorrows-workforce.html) | NVIDIA stack | Finance-function agents | Targets −25% cost, +40% productivity (projected) | Claim | 18 Mar 2025 | D |

**What the pattern shows.** Banks publish adoption counts, not outcomes. Vendors publish resolution rates, not quality. Only Walmart, Klarna and Microsoft's security trials report a controlled baseline.

## Architecture and workflows for the top 10 cases

The top 10 cases share one architecture. A narrowly scoped runtime sits between channels and systems of record. Every answer is grounded in curated knowledge. Every write goes through a scoped tool gateway, and there is a human exit. The differences between cases lie in which tools are called and where the human gate sits.

&#91;embedded content: Reference architecture · synthesized from the disclosed designs in the top 10 cases\]

The runtime (blue) is the only part that reasons. Everything around it exists to limit what that reasoning can touch.

| # | Use case (exemplar) | Workflow: trigger → steps → outcome | Tools and systems disclosed | Human gate | KPIs to instrument |
| --- | --- | --- | --- | --- | --- |
| 1 | Customer self-service (Salesforce, OpenTable, Engine) | Chat arrives → topic classified → RAG over knowledge base → answer, or call an action (create case, change booking) → handoff with transcript | Agentforce, Data 360 zero-copy (Snowflake, S3), Service Cloud, Amazon Connect, booking APIs, Bedrock (Engine) | Authenticate before account actions; low confidence → human | Verified resolution, CSAT, reopen rate, escalation quality |
| 2 | Contact-center agent assist (Verizon, Microsoft CSS) | Live contact → retrieve from \~15K docs → suggest answer and draft → after-call summary → write to CRM | Gemini (Verizon); Dynamics 365 consolidating 16 case systems (Microsoft) | Rep sends every reply | Handle time, first-contact resolution, resolutions/hour, conversion |
| 3 | Voice intent routing (Siemens) | Call → hierarchical intent classifier → Lambda calls CRM and directory via AgentCore Gateway as MCP tools → answer or route with context | Amazon Connect, Lex, Lambda, Bedrock AgentCore Gateway | Below confidence threshold → agent, with context | Correct-route rate, containment, abandon rate |
| 4 | IT service desk (Mobileye, ServiceNow) | Ticket or chat → classify → search knowledge → run approved automation → close or escalate | Bedrock AgentCore, Secrets Manager, MCP to on-prem ticketing (Mobileye); ServiceNow AI Search, Virtual Agent | Access grants and consequential changes need approval | End-to-end automation %, mean time to resolve, reopen % |
| 5 | HR self-service (Microsoft) | Question in M365/Teams → identity-aware policy retrieval → connector lookup → ticket → live HR handoff with history | Copilot Studio; Workday, SuccessFactors, ServiceNow, Dynamics 365 connectors; DLP | No write to records without confirmation; works-council review | Deflection, accuracy audit, CSAT |
| 6 | Security alert triage (Microsoft Phishing Triage) | User-reported email → analyze headers, URLs, attachments → verdict with rationale → auto-close benign, escalate malicious | Security Copilot, Defender | Analyst confirms remediation; sample-audit closures for over-trust | Precision and recall, analyst minutes per true positive, MTTR |
| 7 | Legacy code modernization (Amazon, Thomson Reuters, McKinsey LegacyX) | Repo intake → dependency discovery → plan → refactor in parallel jobs → build and test → pull request | Q Developer / AWS Transform; agent squads (5×25) for SAS→Python | Human pull-request review plus CI | Apps migrated, build pass rate, escaped defects, hours vs baseline |
| 8 | Tail-spend negotiation (Walmart + Pactum) | Buyer sets limits and tradeables → agent negotiates by chat → trades payment terms for discount → agreement within bounds | Pactum negotiation engine; procurement contract system | Buyer-set limits; out-of-bounds → buyer | Close rate, savings %, cycle days, supplier sentiment |
| 9 | Advisor knowledge and meeting notes (Morgan Stanley) | Question → RAG over \~100K documents → cited answer. Meeting → transcript → notes and email draft → advisor review → save to Salesforce | OpenAI GPT-4 and Whisper; Salesforce | Advisor approves; daily compliance regression evals | Adoption, time per meeting, eval pass rate |
| 10 | Freight-invoice audit (Dow, pilot) | Invoice PDFs from email → extract → compare with rates and shipments → flag anomalies | Copilot Studio autonomous agent | Humans investigate; no automatic payment or dispute | Confirmed anomalies, $ recovered, false-positive rate |

## Comparative assessment: value, feasibility, complexity

The best near-term bets combine high value, high feasibility and evidence graded B or better: agent assist, IT and security triage, and knowledge-grounded self-service. Transactional, finance and recruiting agents score high on value but low on feasibility today.

Scores are our analyst judgments on a 1–5 scale, informed by the cases above. **Value** reflects volume × unit-cost impact in a typical Fortune 500. **Feasibility** reflects data readiness, integration effort, error tolerance and regulatory exposure; 5 is easiest. Re-score these against your own baselines before committing budget.

| # | Use case | Value (1–5) | Feasibility (1–5) | Complexity | Typical time to first value | Evidence | Dominant risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Contact-center agent assist | 4 | 5 | Low | 6–10 weeks | A | Over-reliance by novice reps |
| 8 | Customer self-service with handoff | 5 | 4 | Medium | 8–12 weeks | C | CSAT erosion; ungrounded policy answers |
| 13 | IT service-desk agent | 4 | 4 | Medium | 8–12 weeks | C | Automation over-reach on access grants |
| 5 | Phishing / alert triage agent | 4 | 4 | Medium | 6–10 weeks | B | Analysts over-trust missed threats |
| 4 | SOC investigation copilot | 4 | 4 | Low | 4–8 weeks | B | Vendor-only evidence |
| 11 | Legacy code modernization | 5 | 3 | Medium | 10–16 weeks | B−/C | Hidden defects; weak test coverage |
| 2 | Knowledge assistant on model gateway | 4 | 4 | Medium | 8–12 weeks | A−/B | Prompt-injection data leakage |
| 7 | Tail-spend negotiation | 4 | 3 | Medium | 12–16 weeks | B+ | Contract-term misreads; supplier relations |
| 10 | Voice intent routing | 4 | 3 | Medium–High | 12–16 weeks | C | Accent and noise accuracy |
| 3 | Advisor research and notes | 3 | 4 | Medium | 8–12 weeks | B | Compliance recordkeeping |
| 6 | Identity-policy agent | 3 | 4 | Low | 4–8 weeks | B | Misconfigured access policies |
| 12 | Developer coding assistants | 3 | 5 | Low | 2–6 weeks | A (mixed) | Experienced developers may slow down |
| 17 | Seller and web-sales agents | 3 | 4 | Low–Medium | 6–10 weeks | C | Attribution of revenue |
| 15 | HR self-service agent | 3 | 3 | Medium | 10–14 weeks | C/D | Personal data; works-council approval |
| 19 | Sourcing / RFP agents | 3 | 3 | Medium | 10–14 weeks | C | Supplier data quality |
| 14 | Engineering on-call Q&A | 2 | 5 | Low | 4–6 weeks | B− | \~50% helpfulness ceiling |
| 9 | Transactional service agent | 5 | 2 | High | 16+ weeks | B/C | Irreversible wrong actions; fraud |
| 20 | Finance back-office agents | 4 | 2 | High | 16+ weeks | D | Controls and audit (SOX); no proof |
| 18 | Shopping / seller-ops agents | 4 | 2 | High | 16+ weeks | B/C | Scale and catalog data needed |
| 16 | Recruiting screening agent | 3 | 2 | High | 16+ weeks | C/D | EU AI Act high-risk; bias liability |

Time-to-value ranges are planning estimates from the disclosed rollout timelines, not measured benchmarks. OpenTable reported its result 3 weeks after launch; Verizon took about 6 months to reach full scale.

## Production reality, failures, security and governance

The independent evidence and the vendor evidence disagree sharply. Vendors report 50–90% autonomous resolution. Benchmarks show 30–35% success on realistic multi-step work. The one large randomized field test of an autonomous service agent found customer ratings went down. The gap is explained by scope: production agents succeed on narrow, FAQ-like tasks with handoff, and fail on open-ended work.

### Production vs pilot vs claim

| Signal | Finding | Source |
| --- | --- | --- |
| Scaling agents | \~20% of firms are scaling agents overall, and 40% of firms with >$1B revenue (n=1,719). 37% report any EBIT impact from AI | [McKinsey State of AI 2026](https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-state-of-ai), 25 Aug 2026 |
| Deployed agents | 53% of large US firms say agents are "deployed" (term undefined). Only 26% have real-time AI cost visibility | [KPMG AI Pulse Q2 2026](https://kpmg.com/us/en/media/news/q2-ai-pulse-2026.html), 24 Jun 2026 |
| Governance maturity | Only 21% of firms planning agents have a mature agent governance model | [Deloitte State of AI 2026](https://www.deloitte.com/us/en/about/press-room/state-of-ai-report-2026.html), 21 Jan 2026 |
| Expected ROI | 25% of AI initiatives delivered expected ROI; 16% scaled enterprise-wide (2,000 CEOs) | IBM CEO Study, IBM newsroom, 6 May 2025 |
| Cancellation | Gartner predicts >40% of agentic projects cancelled by end-2027; \~130 genuine agentic vendors ("agent washing") | [Gartner](https://www.gartner.com/en/newsroom/press-releases/2025-06-25-gartner-predicts-over-40-percent-of-agentic-ai-projects-will-be-canceled-by-end-of-2027), 25 Jun 2025 |
| Zero return | "95% of organizations are getting zero return." Weak method: 52 interviews, 153 surveys, self-described "preliminary" | MIT NANDA *GenAI Divide*, Jul 2025 ([critique](https://customerthink.com/the-great-genai-divide-debunking-the-myth-of-95-failure/)) |
| SAP agents | Only 3% of DSAG members use SAP Business AI productively; SAP's product head called Joule Studio adoption "minimal" | [CIO](https://www.cio.com/article/4170656/saps-ai-promises-last-year-most-are-still-rolling-out.html), 13 May 2026 |

### Capability ceiling (independent benchmarks)

- **[TheAgentCompany](https://arxiv.org/html/2412.14161v2)** (CMU, May 2025): the best agent fully completed 30.3% of 175 simulated office tasks. Finance and admin tasks were hardest; many models scored zero.
- **[CRMArena-Pro](https://arxiv.org/html/2505.18878v1)** (Salesforce AI Research, TMLR 2026): about 58% single-turn and about 35% multi-turn success on CRM tasks. Confidentiality awareness was "near-zero" by default.
- **[τ²-bench](https://arxiv.org/pdf/2506.07982)** (Sierra, Jun 2025): success fell sharply when the user also had to act; for example, o4-mini dropped from 67% to 42% on telecom tasks.
- **[Agentic AI and Human-in-the-Loop](https://arxiv.org/pdf/2605.14830)** (Alibaba/Taobao field RCT, May 2026; 680,676 chats): chats got shorter, but customer ratings fell substantially on AI-eligible chats. Earlier human takeover gave better outcomes.

### Incident log (newest first)

| Date | Incident | What failed | Control it argues for |
| --- | --- | --- | --- |
| Apr 2026 | [PocketOS](https://pointguardai.com/ai-security-incidents/ai-agent-deletes-production-database-in-nine-seconds-and-apologizes): coding agent used a stray cloud token to delete a production volume and its backups in 9 seconds | Credential scope; no confirmation | Scoped credentials; confirmation before irreversible actions |
| Dec 2025 | [GeminiJack](https://securityaffairs.com/185574/hacking/geminijack-zero-click-flaw-in-gemini-enterprise-allowed-corporate-data-exfiltration.html): poisoned Doc or invite made Gemini Enterprise leak Gmail and Docs data | Indirect prompt injection | Separate untrusted content from privileged context |
| Oct 2025 | [Deloitte Australia](https://www.news4jax.com/business/2025/10/07/deloitte-to-partially-refund-australian-government-for-report-with-apparent-ai-generated-errors/): A$440K government report with fabricated citations; partial refund | No source verification | Human verification of citations |
| Sep 2025 | [ForcedLeak](https://thehackernews.com/2025/09/salesforce-patches-critical-forcedleak.html) (CVSS 9.4): Agentforce exfiltrated CRM data via an expired allowlisted domain bought for \~$5 | Output egress | Maintained egress allowlists |
| Jul 2025 | [Amazon Q Developer extension](https://bleepingcomputer.com/news/security/amazon-ai-coding-agent-hacked-to-inject-data-wiping-commands): malicious pull request shipped a wiper prompt in v1.84.0; no customer impact reported | Agent supply chain | Signed builds; repo permission hygiene |
| Jul 2025 | [Replit](https://www.eweek.com/news/replit-ai-coding-assistant-failure/): agent deleted a production database during a code freeze | No dev/prod separation | Environment isolation; restorable backups |
| Jun 2025 | [EchoLeak, CVE-2025-32711](https://thehackernews.com/2025/06/zero-click-ai-vulnerability-exposes.html) (CVSS 9.3): zero-click email exfiltration from M365 Copilot | Scope violation | Content isolation; egress controls |
| May 2025 | [Klarna reversal](https://www.entrepreneur.com/business-news/klarna-ceo-reverses-course-by-hiring-more-humans-not-ai/491396): rehired humans after "lower quality" service | Over-automation | Always-available human; quality KPIs |
| May 2025 | [GitHub MCP exploit](https://invariantlabs.ai/blog/mcp-github-vulnerability): malicious issue made an agent leak private repo data | Tool over-permission | One-repo-per-session; runtime guardrails |
| Feb 2024 | [Moffatt v. Air Canada](https://decisions.civilresolutionbc.ca/crt/crtd/en/525448/1/document.do): airline liable for its chatbot's wrong refund policy | Ungrounded policy answer | Ground policy answers in source documents; the firm owns liability |

### Governance baseline

- **Threat model.** Use the OWASP Top 10 for LLM Apps 2025 together with the [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) (Dec 2025). The latter covers goal hijack, tool misuse, identity abuse, supply chain, memory poisoning, cascading failures and rogue agents.
- **Management system.** Use NIST AI RMF with the GenAI Profile (AI 600-1, Jul 2024), and ISO/IEC 42001:2023 for certification.
- **EU AI Act.** General-purpose AI obligations have applied since Aug 2025. The [Digital Omnibus](https://www.hunton.com/privacy-and-cybersecurity-law-blog/eu-digital-omnibus-on-ai-enters-into-force) (in force 27 Jul 2026) moves Annex III high-risk obligations to 2 Dec 2027; these cover HR, credit and similar decisions. HR-screening and credit agents must be designed for those obligations now.
- **Liability.** The deploying firm owns what its agent says (Air Canada). Policy answers must be grounded in source documents and logged.

## Prioritized opportunities and 90-day roadmap

In the first 90 days, put three agents into limited production: contact-center agent assist, an IT service-desk agent and a phishing/alert triage agent. Build them on one shared platform. Each has a measurable baseline, reversible actions and B-grade or better evidence for the pattern. Customer self-service has the highest value, but it waits for wave 2 because it touches customers directly. Its controls should first be proven on internal users.

&#91;embedded content: Analyst scoring · 20 use cases from the comparative table\]

The top-left quadrant is where most vendor pitches sit. Those agents need the platform controls built in wave 1 before they are safe to attempt.

| Wave | Timing | Use cases | Why now | Exit criterion |
| --- | --- | --- | --- | --- |
| 1 | Days 0–90 | Agent assist · IT service-desk agent · alert triage | Internal or human-reviewed users; reversible actions; strongest evidence | Measured KPI lift vs control group; no Sev-1 incident |
| 2 | Months 4–6 | Customer self-service with handoff · legacy code modernization · HR self-service | Reuses the wave-1 gateway, evals and handoff; higher value | Verified resolution ≥ prior bot, CSAT not below control |
| 3 | Months 7–12 | Transactional service actions · tail-spend negotiation · finance invoice audit | Needs proven write-action controls, approval workflows and audit trails | Finance and audit sign-off on controls; savings measured, not estimated |

&#91;embedded content: Recommended 90-day plan · wave 1\]

Each gate is a scale-or-stop decision, not a status meeting. The day-90 gate decides whether wave 2 is funded.

### What to measure (so the day-90 decision is credible)

- **Outcome:** verified resolution (sampled by humans), not containment. Also measure handle time, mean time to resolve and analyst minutes per true positive.
- **Quality:** CSAT against the control group, reopen and repeat-contact rates, wrong-answer rate from weekly sampled audits, and missed-threat rate for triage.
- **Safety:** prompt-injection test pass rate, blocked tool calls and permission denials, and count of irreversible actions taken without approval (target: zero).
- **Cost:** tokens and cost per resolved item against the human cost per item. 74% of large firms lack real-time AI cost visibility (KPMG, Jun 2026).

### Stop rules

- CSAT or quality falls below the control group for two consecutive weeks (the Klarna and Taobao pattern).
- Any Sev-1 data-exposure finding in red-team testing that is not fixed within the gate window.
- Cost per resolved item exceeds the human baseline with no path to parity.

### Platform decisions to make by day 30

1. **Build or buy per layer.** Buy the runtime where the system of record lives: Agentforce for Salesforce-centric service, ServiceNow for ITSM, Security Copilot or Google SecOps for the SOC. Own the model gateway, evaluation harness, identity model and tracing so agents stay portable. MIT NANDA's survey reports vendor-partnered builds reached deployment about twice as often as internal builds (about 67% vs 33%); that is self-reported and directional only.
2. **Pricing exposure.** Model per-action and per-conversation pricing at year-2 volumes before signing. Agentforce pricing changed in May 2025.
3. **Accountability.** Name a business owner for each agent's KPIs and a control owner for its permissions.

## Evidence quality by domain and research gaps

Evidence is strongest where it matters least for autonomy. Assistive AI in customer service, security and coding has causal studies. Autonomous agents in ERP, finance and supply chain have almost no measured outcomes.

| Domain | Strongest evidence | Grade | Main weakness |
| --- | --- | --- | --- |
| Customer service | Peer-reviewed field study (agent assist); many vendor case studies (self-service) | A (assist) / C (autonomous) | "Resolution" undefined; quality and ratings rarely reported; Taobao RCT shows ratings drop |
| Cybersecurity | Three Microsoft RCTs plus observational studies | B | All vendor-authored; recruited subjects in sandboxes; no independent SOC study |
| ITSM | Vendor self-reports (ServiceNow, Mobileye); BofA press release | C | "Supported by AI" conflated with "resolved"; no error or reopen rates |
| Software / IT modernization | Developer RCTs (+26%; one shows −19%); Amazon estimates | A (assist) / C (agents) | Savings derived from proxies; no rework or defect data |
| CRM / sales | Morgan Stanley adoption; vendor seller stories | B/C | Adoption counts, not revenue causality |
| Procurement | HBR study of Walmart–Pactum | B+ | Data from 2021–22, long-tail only; no 2025–26 update |
| HR | Microsoft and Workday self-reports; SAP estimates | C/D | Deflection targets only; EU AI Act high-risk for hiring |
| Finance / ERP | SAP and Deloitte projections; Dow pilot | D | No named customer with a measured, realized outcome |
| Supply chain | Amazon forecasting model (not an agent) | D | No agentic deployment with published outcomes found |

### Research gaps

1. **No independent audit of any agent outcome metric.** Every resolution, deflection and savings figure is self-reported.
2. **No published RCT of agents in finance operations, procurement or supply chain.** A UK financial-regulatory agent RCT (about 2,000 staff) is [registered](https://www.socialscienceregistry.org/trials/17902) but has no results yet.
3. **Quality and error data is missing.** Almost no case reports wrong-answer rates, reopen rates, human override rates or rework.
4. **Total cost of ownership is opaque.** No case discloses model, platform, integration and run costs against savings. Pricing changed mid-stream: Agentforce moved from $2 per conversation to $0.10 per action in May 2025.
5. **Long-run effects are unknown.** Most metrics come from the first weeks or months, with no 12–24 month follow-up on CSAT, churn or skill erosion.
6. **Workforce attribution is contested.** Headcount claims from Salesforce and Klarna are unaudited, and Klarna partly reversed.
7. **Benchmark validity is weak.** OSWorld-style scores are self-reported and reportedly include broken or ambiguous tasks. Treat leaderboard results as directional only.

**Unverified items we excluded:**

- Dell'Acqua's "40% higher quality" figure.
- McKinsey 2025's "23% scaling agents."
- Google SecOps "30 minutes to 60 seconds": no customer named, no method.
- Commerzbank "$30M" and Hitachi "400%": secondary reporting with no primary link.
- Wells Fargo, BDO and Grupo Bimbo figures: mentioned in a Microsoft blog, primary stories not opened.

## Sources

This list adds the academic, analyst and market sources not already linked in the case tables above. All pages were opened on 18 Oct 2026, except where a row notes a secondary summary.

| Source | Type | Published |
| --- | --- | --- |
| [Generative AI at Work (arXiv)](https://arxiv.org/abs/2304.11771v1); published in *QJE* 2025, DOI 10.1093/qje/qjae044 | Peer-reviewed field study | Apr 2023; QJE 2025 |
| [Navigating the Jagged Technological Frontier (HBS WP 24-013)](https://www.hbs.edu/faculty/Pages/item.aspx?num=64700) | Preregistered experiment, 758 consultants | Sep 2023 |
| [Effects of GenAI on High-Skilled Work (Management Science)](https://pubsonline.informs.org/doi/fpi/10.1287/mnsc.2025.00535) | 3 field RCTs, 4,867 developers | 2025 (inferred from DOI) |
| [METR experienced developer RCT](https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/) | RCT, 16 developers (read via secondary summary) | 10 Jul 2025 |
| [Security Copilot RCT for IT admins](https://arxiv.org/html/2411.01067v2) | Vendor RCT, 181 subjects | Oct 2024 |
| [Security Copilot live-operations study 2024](https://arxiv.org/html/2411.03116v2) | Vendor observational | Nov 2024 |
| [Security Copilot live-operations study 2025](https://arxiv.org/html/2504.08805v1) | Vendor observational | Mar 2025 |
| [Collaborating with AI Agents](https://arxiv.org/pdf/2503.18238) | Randomized, 2,234 participants | v3 Feb 2026 |
| [AgentDojo](https://arxiv.org/html/2406.13352v3) | Prompt-injection benchmark | Nov 2024 |
| [OSWorld-Verified leaderboard](https://leaderboard.steel.dev/leaderboards/osworld.md) | Self-reported leaderboard | Updated 11 Oct 2026 |
| Gartner: half of firms planning AI-driven service staffing cuts will abandon them by 2027 (Gartner newsroom) | Analyst prediction, 163 service leaders | 10 Jun 2025 |
| [BCG: The Widening AI Value Gap](https://media-publications.bcg.com/The-Widening-AI-Value-Gap-October-2025.pdf) | Consultancy survey, 1,250 executives | Oct 2025 |
| [McKinsey: One year of agentic AI — six lessons](https://www.mckinsey.com/capabilities/quantumblack/our-insights/one-year-of-agentic-ai-six-lessons-from-the-people-doing-the-work) | Practitioner lessons, 50+ builds | 12 Sep 2025 |
| [Salesforce Q4 FY26 earnings call](https://s205.q4cdn.com/626266368/files/doc_financials/2026/q4/Transcript-Salesforce-Inc-Q4-FY26-Earnings-Conference-Call-2-25-26.pdf) | Earnings transcript: Agentforce ARR \~$800M | 25 Feb 2026 |
| [Salesforce Flex Credits](https://www.salesforce.com/blog/flex-credits/) | Pricing change | 23 May 2025 |
| [SalesforceBen: Agentforce adoption](https://www.salesforceben.com/where-are-we-really-at-with-agentforce-adoption/) | Practitioner analysis: 9,500 of 18,500 deals paid | 17 Dec 2025 |
| [ServiceNow Q2 2026 results](https://s205.q4cdn.com/537566246/files/doc_news/ServiceNow-Reports-Second-Quarter-2026-Financial-Results-2026.pdf) | Earnings release: AI ACV >$1B | 22 Jul 2026 |
| [Kainos (ServiceNow)](https://www.servicenow.com/customers/kainos-now-assist.html) | Vendor case study | Date not shown |
| [Toyota NA (AWS)](https://aws.amazon.com/solutions/case-studies/innovators/toyota/) | Vendor case page | Updated 25 Sep 2026 |
| [Druva on AgentCore](https://aws.amazon.com/blogs/machine-learning/amazon-bedrock-agentcore-and-claude-transforming-business-with-agentic-ai) | Vendor blog: 58% faster resolution, up to 63% without humans | 17 Nov 2025 |
| [Amazon Seller Assistant (PYMNTS)](https://www.pymnts.com/amazon/2026/amazon-sellers-gain-sales-and-cut-costs-with-ai-tools/) | Secondary report | 30 Apr 2026 |
| [Google Customer Engagement Suite results](https://cloud.google.com/blog/products/ai-machine-learning/customer-engagement-suite-stronger-results-and-new-ai-features) | Vendor blog: TTEC, loveholidays, YouTube | 12 Mar 2025 |
| [Zenity: Copilot Studio data exfiltration](https://labs.zenity.io/p/a-copilot-studio-story-2-when-aijacking-leads-to-full-data-exfiltration-bc4a) | Security research | 7 Jul 2025 |
| [EchoLeak technical paper](https://arxiv.org/html/2509.10540v1) | Security research | 6 Sep 2025 |
| [ServiceNow customer-claim critique (CX Foundation)](https://cxfoundation.com/news/servicenow-claims-ai-handles-90-percent-customer-service) | Trade press | 20 Jan 2026 |
| [UK & Ireland SAP User Group survey](https://itbrief.co.uk/story/most-sap-users-plan-ai-but-remain-cautious-on-real-benefits) | User-group survey, n=392 | 4 Dec 2025 |
| [Johnson & Johnson AI portfolio cut](https://www.deeplearning.ai/the-batch/johnson-johnson-reveals-its-revised-ai-strategy) | Secondary report | 7 May 2025 |
| [NIST AI 600-1](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf) | Standard (read via secondary summary) | Jul 2024 |
