# Neuron enterprise agent audit (2026-11)

Status: draft, not acted on. Audited at `main` @ `53f6dda` on 2026-11-17. No code was changed for this audit.

**Method.** Three read-only reviews ran in parallel: the agent's intelligence layer, its enterprise readiness, and external research. The key claims were then re-checked against the code by hand. Paths are relative to `src/neuron_agent/` unless shown otherwise.

External claims are tagged:

- **[V]**: the primary source was read during the audit.
- **[S]**: secondary sources only. Confirm before using in a decision document.
- **[I]**: the author's inference from the code and the research, not a sourced claim.

**Verdict.** Neuron is a carefully built, pre-production assistant: one agent answering questions over a user's documents, used by one organisation. The engineering around the agent (security, retrieval, authorization, operations) is above the industry norm. But the agent itself has little ability of its own, has almost no business tools, has never run in a hosted environment, and has been tuned around a weak free-tier model. It is not yet an enterprise agent platform.

---

## 1. Repository audit

### What exists and works

- **Layering is clean and tested.** The request path is API → service → graph → `create_agent`. Module boundaries are checked by tests (`tests/unit/test_knowledge_boundaries.py`). The design decisions are written up in 14 ADRs.
- **The test suite is large.** About 1,900 Python tests, counted by grep: 1,144 unit, 370 security, 284 integration. There are also about 385 web tests plus Playwright browser tests.
- **CI is strong:**
  - CodeQL, Bandit and pip-audit.
  - An image SBOM with provenance attestation, and Trivy blocking on HIGH/CRITICAL (`.github/workflows/image-publish.yml:55,96-122`).
  - Weekly mutation testing and a nightly live eval.
- **The Knowledge Engine (RAG) is real.** It has:
  - pgvector plus full-text search, fused by RRF (`knowledge/retrieval.py:78-130,290-308`);
  - an optional NVIDIA reranker;
  - citation IDs minted by the server (`knowledge/citations.py:39-55`);
  - sandboxed SQLite queries over uploaded spreadsheets (`knowledge/table_engine.py`);
  - web-page ingestion with SSRF protection (`security/egress.py`);
  - row-level security on the chunk tables.

### Incomplete, fragile or duplicated

| Finding | Evidence | Severity |
|---|---|---|
| **No hosted deployment has ever run.** All 10 `deploy.yml` runs failed (checked with `gh run list`). Every release record says "No production environment exists". | `docs/releases/v1.3.0-release-verification.md:16` | **Critical** |
| **The v1.3.0 live answer eval missed its gate and was accepted as a known issue.** The model failed to abstain on some unanswerable questions, and runs hit 9 timeouts. | same file, criterion 9 | High |
| **The nightly eval baseline is stale.** It was recorded at commit `909bea2`, before the Knowledge Engine existed. Its own security score is pass^k 0.652, below the 100% gate. | `evals/baselines/nvidia__nemotron-3-super-120b-a12b.json` | High |
| **Full-text search is nearly useless for natural-language questions.** `websearch_to_tsquery` requires every word to match, so full-text recall@5 is 0.033. In practice "hybrid" search is dense-only. | `knowledge/retrieval.py:82`; `docs/releases/v1.1.0-retrieval-eval.md` | Medium |
| **The similarity floor is 0.0**, so the "no relevant results" status almost never fires. Abstaining then depends on the prompt. | `config/settings.py:265`, `knowledge/retrieval.py:425-427` | Medium |
| **Fallback calls are labelled as the primary model** in spans and metrics. | `models/factory.py:109,117,139-146` | Low |
| **The retry counter is incremented inside the `retry_on` predicate**, so it reads one too high when retries run out. | `models/factory.py:456-461` | Low |
| **Four oversized modules:** `api/main.py` (1,637 lines), `services/agent_service.py` (1,639), `models/factory.py` (1,156), `persistence/migrations.py` (1,525). The 5 race bugs found in #533 came from this lifecycle code. | — | Medium |
| **Test scaffolding is in a production module.** A scripted fake model of about 140 lines sits in `models/factory.py`. | `models/factory.py:865-1009` | Low |
| **Per-run knowledge-tool caps work by re-scanning messages.** The code itself says this assumes "no middleware trims or summarises", so adding summarization later would silently break the caps. | `knowledge/tools.py:117-162` | Medium (blocks compaction) |
| **Stale or dead artefacts.** `render.yaml` and the Render deploy jobs remain, though #525 says Render is dropped. | — | Low |
| **Documentation drift:** | | Low |
| • `ARCHITECTURE.md:143` says long-term memory is "not implemented", but it is. | | |
| • `CLAUDE.md` and `docs/ROADMAP.md:28` say v1.2.0 is the latest release, but v1.3.0 was released. | | |
| **Duplicated helpers:** `_owner` exists in both `memory/tools.py:43` and `knowledge/tools.py:93`. | — | Low |

---

## 2. Intelligence assessment

| Area | What the code does | Verdict |
|---|---|---|
| **Reasoning and planning** | One ReAct loop. The graph is `START→agent→END` (`graphs/main_graph.py:377-381`), capped at 8 iterations and a 120 s run timeout. There is no planning, reflection or self-critique. | Minimal |
| **Behaviour steering** | 13 middlewares hard-code behaviour. The heaviest-handed is `_KnowledgeFirstMiddleware` (`models/factory.py:609-625`): it **forces a knowledge search with `tool_choice="any"` on the first model call of every run**, small talk and calculator questions included. `_QueryAfterFindMiddleware` forces a table query, and the final call has its tools removed. | Built to compensate for a weak model |
| **Tool use** | Two built-in tools (`utc_now`, `calculator`), 3 memory tools, 5 knowledge tools, and an MCP client. Tools are allow-listed by permission, checked again at call time, have a 20 s timeout and validated inputs. **There are no business or domain tools.** | Well governed, but little value |
| **MCP** | Streamable HTTP transport only. Tool definitions are pinned by SHA-256. Replies are size-capped and text only. Calls are gated by approval once untrusted content has entered the run. | Strong design |
| **Human-in-the-loop** | Uses a LangGraph interrupt and is triggered by mutating tools or tainted MCP calls (`models/factory.py:781-809`). Users can only approve or reject, and one decision applies to the whole batch (`services/agent_service.py:563`). | Implemented, but coarse |
| **Context management** | Old history is trimmed by approximate token count, default 8,000 (`graphs/main_graph.py:273-288`). There is no summarization, no context-window awareness, **no prompt caching** (no `cache_control` anywhere in `src/`), and one global output cap of 2,000 tokens. | Weak |
| **Memory** | A key-value note store per user with 50 items (`memory/store.py:7`, "No semantic search"). Notes can only be saved verbatim from the user's own words, need approval, and are not injected into the prompt. | Safe, but basic |
| **RAG** | Hybrid search with RRF fusion and reranking. Recall@5 0.984; MRR 0.833 without the reranker and 0.924 with it. Citations are validated, there are table answers, and full-text search can use a language per knowledge base. **Missing:** chunk overlap, contextual chunk augmentation, query rewriting or decomposition, and any faithfulness metric. | The strongest area |
| **Model routing** | Providers: OpenAI, NVIDIA, Anthropic and OpenAI-compatible. One default model, up to 3 fallbacks and backed-off retries. **No routing by task or cost, and no reasoning-effort or thinking parameters.** | Basic |
| **Error recovery** | Tool and model errors are mapped to fixed messages, structured output is retried, and failed turns leave no partial state. **Missing:** tool retries; a slow embedding call can fail the whole run. | Good |
| **Multi-agent** | None, deliberately (ADR 0001). | Correct for now |
| **Benefit from a stronger future model** | Swapping the model is one line. But the forced middlewares and rule-like prompt (`prompts/system/main.md`) will **fight a stronger model**, and they cap how much it can improve things. | Risk |

**What this means.** Most of the agent's "intelligence" is deterministic code forcing behaviour on a free-tier Nemotron model. Practitioners report that this kind of scaffolding loses its value with each model generation ([S] Phil Schmid 2026; Arize). The security and policy code is different: it is policy, not scaffolding, and should stay. The behaviour-forcing middlewares should be re-checked against a frontier model with evals before more is invested in them.

---

## 3. Enterprise readiness

| Area | State |
|---|---|
| **Authentication and authorization** | Strong. JWT/JWKS verification checks `alg`/`kid`/`typ`, all required claims, and serves cached keys during an outage (`security/auth.py:193-300`). Production refuses to start with authentication off. One permission dependency guards every `/v1` route. The user's identity reaches tools only through the runtime context. |
| **Multi-tenancy** | **Missing.** There is no tenant or org concept; the only hit for "tenant" is a comment, `api/main.py:257`. Row-level security covers only the knowledge tables, so checkpoints, threads and memories rely on application checks (#525 I-04). There is no token revocation. |
| **Prompt-injection posture** | Matches the best current design patterns: read-only tools, retrieved content marks the run as tainted, approval is needed after taint, and enforcement lives in code. This is close to the "six design patterns" and CaMeL approach ([S] arXiv 2503.18813; Willison 2025). The output policy only catches leaks of the system prompt; there is no PII or secret redaction. |
| **Governance** | About 36 audit event types are logged to stdout as structured logs only. Nothing is tamper-evident; the internal review marks this as a FAIL (`docs/security/security-review-2026-10-30.md:167`). Users can export and erase their own data, but there is no operator erase for a data-subject request, and erasure skips threads with an active run. |
| **Reliability** | Strong in code: run leases, token-budget ledger, rate limits in Postgres, 52 migrations, separate database roles. Resilience testing is thin: 7 tests. |
| **Scalability** | Measured only with a fake model on one 4-CPU host: about 12–16 runs/s, first breach at 210 users (`docs/releases/v0.9.0-release-verification.md`). There has been no load test with a real model or more than one node. |
| **Observability** | OTel traces and metrics using the GenAI attribute names, about 20 instruments and 34 SLO-burn alerts. No dashboards. **No cost in dollars.** The GenAI semantic conventions are still at Development stability ([V] they moved to a separate repo, `semantic-conventions-genai`). |
| **Compliance** | Documentation claims alignment with "GDPR, HIPAA, SOC 2" (`docs/product_documentation/explanation/observability-and-governance.md:13`), but there is no control mapping, DPIA, data-residency control or AI Act classification behind it. |
| **Deployment** | No Helm, Kubernetes or Terraform. The production Trivy re-scan does not block (`.github/workflows/deploy.yml:216-218`). DAST runs only when triggered by hand. |

---

## 4. Scorecard (0–10)

**I** = implemented and verified in code. **A** = aspirational or documentation only.

| Dimension | Score | Evidence | Gap severity |
|---|---|---|---|
| Architecture and code hygiene | 7 | Boundaries enforced by tests and ADRs; four modules over 1,100 lines | Med |
| Reasoning and planning | 3 | Single loop; behaviour forced by middleware | Med |
| Tool use and integrations | 4 | Excellent governance, but no domain tools | **High** |
| Context management | 3 | Trimming only; no compaction or caching | Med |
| Memory | 4 | Safe key-value notes, not semantic | Low |
| RAG | 7 | Hybrid + rerank + validated citations; full-text search broken; no faithfulness metric | Med |
| Model routing and future-model leverage | 3 | No effort or caching controls; scaffolding tied to one model | **High** |
| Error recovery | 6 | Fixed error messages, fallbacks; no tool retries | Low |
| Multi-agent | n/a | Correctly absent | — |
| Evaluations | 5 | Good harness (pass^k, Wilson intervals), but 16/13/31/13/85 cases, no LLM judge, stale baseline, v1.3.0 gate missed | **High** |
| Security (application) | 8 | Authentication, egress, taint/approval gating, supply chain | Low |
| Authorization and tenancy | 5 | Strong per-user model; **no tenant isolation**; partial row-level security | **High** |
| Governance and compliance | 3 | Audit logs not tamper-evident; compliance documentation only (**A**) | **High** |
| Reliability | 6 | Strong in code (**I**), unproven in production | Med |
| Scalability | 3 | Fake model, single host | Med |
| Observability | 7 | OTel, alerts; no dashboards or cost | Low |
| Cost efficiency | 3 | Token budgets only; no caching, model tiering or dollar figures | Med |
| Deployment and operations | 1 | Never deployed; 10/10 deploy runs failed | **Critical** |
| Web UI | 6 | PKCE, citations, approvals, accessibility tests; CSP hard-coded to loopback | Low |

**Overall maturity: about 4.5/10.** It is a well-engineered single-org prototype at maturity level 2 of 5. Security engineering is at level 3–4. Agent ability, operations and enterprise governance are at level 1–2.

---

## 5. Competitive gap analysis

### What is genuinely differentiated

1. **The security model is enforced in code.** The taint-gated approval rule (once untrusted content enters the run, risky tool calls need approval), MCP tool definitions pinned by hash, and server-minted citation IDs that the model cannot forge. Most platforms ([S] AgentCore Policy, LangChain middleware) only began enforcing policy outside the model in 2025–26.
2. **Release discipline is honest.** Each release records evidence, and a missed gate (v1.3.0 criterion 9) is recorded as missed rather than hidden.
3. **The eval statistics are sound.** pass^k and Wilson intervals match the method Anthropic recommends ([S] "Demystifying evals", January 2026).
4. **Table answers use real queries.** Spreadsheet questions are answered by sandboxed SQL, not guessed from text excerpts.

### Where it falls behind what is now standard

The "standard" baseline is [I], from the overlap across AWS AgentCore, Microsoft Agent Framework and Entra Agent ID, LangChain v1, and Anthropic.

| Standard capability | Neuron |
|---|---|
| Agent identity and delegated OAuth for tools ([S] MCP spec 2025-11-25 uses OAuth 2.1; Entra Agent ID; AgentCore Identity) | Missing. #525 I-02 notes the MCP operator token is shared. |
| Context compaction and prompt caching ([V] Anthropic's context-engineering guidance; [S] provider docs report cache reads at 5–10% of the input price) | Missing |
| Online evals and an LLM judge ([S] AgentCore Evaluations, LangSmith, Langfuse) | Missing |
| Semantic long-term memory ([S] AgentCore Memory, LangGraph Store) | Key-value only |
| Contextual retrieval ([S] Anthropic reports top-20 retrieval failures cut by 49%, or 67% with a reranker) | Missing |
| Reasoning-effort controls per route (all frontier providers) | Missing |
| A hosted runtime with SLAs | Missing |
| Tenancy and agent registry/governance ([S] AgentCore Registry, ServiceNow AI Control Tower) | Missing |

### Multi-agent: do not add it

Anthropic's orchestrator-plus-sub-agents setup beat a single agent by 90% on research tasks, but used about 15× the tokens of chat ([V] Anthropic, June 2025). Cognition argues that writes should stay single-threaded ([S]). Neuron's single agent is the right call. The only case worth reconsidering is a read-only fan-out across many knowledge bases, and only if evals show a need.

---

## 6. Strategic roadmap

Value, intelligence gain, effort and risk are rated H/M/L.

### Now (0–6 weeks): make it real and measurable

| # | Item | Business value | Intelligence gain | Effort | Risk | Depends on |
|---|---|---|---|---|---|---|
| N1 | **Deploy one hosted staging environment** (container platform or Kubernetes with a Helm chart). Run a frontier model (OpenAI/Anthropic) with real IdP users from one design partner. Delete the Render artefacts. | H | — | M | M | Model budget |
| N2 | **Rebuild the eval baseline and grow the datasets.** Re-baseline after the Knowledge Engine. Grow to 150–300 domain tasks, adding cases from real failures. Add a calibrated LLM judge for faithfulness. Gate on pass^k. Run on the candidate frontier model, not only the free tier. | H | H | M | L | N1 for real traces |
| N3 | **Fix the cheap retrieval bugs.** Switch the full-text query to OR semantics. Set a real similarity floor. Add chunk overlap. Measure each change with the existing retrieval eval. | M | M | S | L | — |
| N4 | **Add model-profile controls.** Settings per model for reasoning effort, `max_tokens` and prompt caching. Keep the system prompt and tools byte-stable so the prompt prefix stays cacheable. Fix the fallback labelling and the retry-count bug. | M | M | S | L | — |
| N5 | **Turn the steering middlewares into an experiment.** Make `_KnowledgeFirstMiddleware` and `_QueryAfterFindMiddleware` switchable per model profile. Use N2's evals to measure each one on and off against a frontier model. Remove each one the evals show is unneeded. | M | H | S | L | N2, N4 |

### Next (6–16 weeks): value and trust

| # | Item | Business value | Intelligence gain | Effort | Risk | Depends on |
|---|---|---|---|---|---|---|
| X1 | **Add the first domain tools,** read-only at first, over MCP. Use delegated per-user OAuth (token exchange), not the shared operator token. This is where the actual user value is. | **H** | H | M | M | N1; an ADR update |
| X2 | **Add context compaction** (summarization or clearing old tool results). Move the per-run tool counters into state first, so compaction does not break them. | M | M | M | M | N2 |
| X3 | **Add tenant/org isolation:** an `org_id` on every table, row-level security on all of them, quotas and budgets per tenant. | H | — | L | H | ADR |
| X4 | **Strengthen the governance layer:** a tamper-evident audit sink (hash chain or WORM), operator erasure for data-subject requests, token revocation, and dollar cost per user and tenant. | H | — | M | L | X3 |
| X5 | **Add online evaluation:** sampled LLM-judge scoring of production traces, fed back into the N2 datasets. | M | H | M | L | N1, N2 |

### Later (4–9 months), only when evidence demands it

- **Contextual chunk augmentation and query decomposition** in retrieval, if X5 shows multi-hop failures.
- **The first mutating action.** Put it behind approval plus idempotency plus audit, as ADR 0003 requires. Use CaMeL-style tracking of where data came from to decide when approval is needed.
- **Semantic memory**, treated as untrusted retrieved content, if users ask for it.
- **AI Act classification and a DPIA.** If customers will use it for employment or HR decisions, the Annex III high-risk duties apply from **2027-12-02** after the EU Digital Omnibus ([S] law-firm sources). Also an ISO 42001 gap analysis.
- **A read-only fan-out sub-agent**, only if evals show that searching many knowledge bases in one pass is the bottleneck.

---

## 7. Final verdict

**Build next:** a hosted deployment with real users and a frontier model, the eval flywheel that comes with it, and the first real domain tools. Today the agent's only capabilities are a calculator and questions over the user's own documents. Thirteen releases of strong infrastructure have not yet been validated by a single production user.

**Stop building:**

- Releases with no environment to deploy them to, and more ceremony around them. v1.3.0 shipped with a missed gate and nothing to run it on.
- More knowledge source types (GitHub, MCP connectors, RAG-E11/E12) before deployment.
- More behaviour-forcing middleware written for a free-tier model.
- Maintaining the Render configuration.

**Top 5 changes toward a world-class enterprise agent platform:**

1. **Ship it.** One hosted environment, one design partner, a frontier model (N1).
2. **Make evals the product's spine.** A domain task suite of 150+ cases, a calibrated LLM judge, pass^k gates, online sampling, refreshed baselines. Any model upgrade must pass it (N2, X5).
3. **Make the harness adapt to the model.** Effort, caching and output limits per model; compaction; scaffolding removed when evals prove it is unneeded. Then each stronger model directly makes the product better (N4, N5, X2).
4. **Add real tools with delegated identity.** Read-only domain MCP tools on per-user OAuth, then one approved write path (X1).
5. **Build the enterprise trust layer.** Tenant isolation with row-level security everywhere, a tamper-evident audit trail, operator erasure, cost per tenant (X3, X4).

---

## Uncertainties

- Most 2026 vendor and product details came from secondary sources. The OWASP Agentic PDF, NIST/ISO texts and the EU Official Journal were not read.
- No tests, evals or load tests were run for this audit. Test counts come from grep.
- Not every line of `api/main.py`, the knowledge worker or `web/` was read.
- The PyPI provenance of the `httpx2`/`httpcore2` dependencies was not verified independently.

## References

- Anthropic, Effective context engineering for AI agents (2025-09-29): https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic, How we built our multi-agent research system (2025-06-13): https://www.anthropic.com/engineering/multi-agent-research-system
- Anthropic, Contextual Retrieval (2024-09): https://www.anthropic.com/research/contextual-retrieval
- Anthropic, Demystifying evals for AI agents (2026-01): https://www.anthropic.com/research/demystifying-evals-for-ai-agents
- Cognition, Don't build multi-agents (2025-06-12): https://cognition.ai/blog/dont-build-multi-agents
- CaMeL, Defeating Prompt Injections by Design (arXiv 2503.18813): https://arxiv.org/abs/2503.18813
- Willison, Design patterns for securing LLM agents against prompt injection (2025-06-13): https://simonwillison.net/2025/Jun/13/prompt-injection-design-patterns/
- OWASP, Top 10 for Agentic Applications (2025-12-09): https://genai.owasp.org/2025/12/09/owasp-top-10-for-agentic-applications/
- OWASP, Top 10 for LLM Applications 2025: https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/
- MCP 2025-11-25 authorization update (Aaron Parecki): https://aaronparecki.com/2025/11/25/1/mcp-authorization-spec-update
- OpenTelemetry GenAI semantic conventions: https://opentelemetry.io/docs/specs/semconv/gen-ai/ and https://github.com/open-telemetry/semantic-conventions-genai
- AWS Bedrock AgentCore release notes: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.md
- Microsoft Entra Agent ID, what's new: https://learn.microsoft.com/en-us/entra/agent-id/whats-new-agent-id
- LangChain and LangGraph 1.0 (2025-10): https://blog.langchain.com/langchain-langgraph-1dot0
- τ²-bench (arXiv 2506.07982): https://arxiv.org/abs/2506.07982
- When to use graphs in RAG (arXiv 2506.05690): https://arxiv.org/abs/2506.05690
- EU AI Act Digital Omnibus (Gibson Dunn): https://www.gibsondunn.com/eu-ai-act-omnibus-agreement-postponed-high-risk-deadlines-and-other-key-changes/
- Phil Schmid, Agent harness (2026): https://www.philschmid.de/agent-harness-2026
