# Threat model (v0.9.0)

ADR 0012 decision 6, issue #330. This maps every entry of the two OWASP lists to a control, a
test, or a known issue, for Neuron as it is at v0.9.0: one agent behind a FastAPI API, a React
browser app, Postgres, an identity provider (OIDC/JWT), an optional MCP server list and per-user
memory. It extends `SECURITY.md`, which stays the list of controls; this file is the coverage
check against the two lists.

**Sources.** Entry IDs and titles are copied from the OWASP GenAI Security Project documents
fetched on 2026-10-28: *OWASP Top 10 for LLM Applications 2026* (released 2026-08-03,
`genai.owasp.org/home/resources/owasp-genai-llm-top-10-2026/`) and *OWASP Top 10 for Agentic
Applications for 2026* (released 2025-12-09,
`genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/`). The descriptions
below are this project's own one-line reading of each entry, not OWASP's text; read the OWASP
document for the definition.

**Scope.** Everything here was checked on the local reference stack and in unit, graph, security
and eval tests. No hosted deployment, real browser or external penetration test has been run
(owner decision, 2026-10-27); those are listed as limits where they matter.

**Status values.** *Covered*: a control exists and a named test fails if it is removed.
*Partial*: a control exists, but part of the entry is not tested or not enforced. *Not
applicable*: the capability does not exist in this system, and an ADR forbids adding it without a
new design. *Open*: no control or test; filed as an issue.

## Assets and trust boundaries

| Asset | Where it lives | Who may touch it |
| --- | --- | --- |
| Conversations (threads, history) | Postgres checkpoint tables, owner key = HMAC of `(iss, sub)` | The owner only (404 for others) |
| Memories (notes) | Postgres `store` table | The owner only; written after approval |
| Access token | Browser memory (private field), `Authorization` header | The signed-in user |
| Identity hash key, DSNs, provider keys | Environment of the deployment | The operator |
| Tool set | Registry in code, MCP pins | The operator; the model only requests calls |

Boundaries: browser to API (untrusted client), API to model provider (untrusted output), agent to
tools (the model is not a security boundary), tools to MCP servers (pinned definitions, untrusted
results), API to Postgres (two roles: migrator and app), API to identity provider (JWKS).

## OWASP Top 10 for LLM Applications 2026

| ID | Title | Status | Controls | Tests / evidence |
| --- | --- | --- | --- | --- |
| LLM01:2026 | Prompt Injection | Partial | The model is not a boundary: scopes, tool allow-list, approval of every mutating tool and owner isolation are enforced in code. Input policy (length, control characters); tool output and notes are framed as data. Direct and indirect injection cannot be prevented, only contained. | `test_input_policy`, `test_tool_denial`, `test_memory_tools`, `test_mcp_abuse`, security eval dataset v5. Limit: the eval cannot see an injected call to a tool the caller may use (`SECURITY.md`). |
| LLM02:2026 | Sensitive Information Disclosure | Covered | Logs carry IDs, names and codes only; telemetry allow-lists; trace content hidden unless approved; thread isolation; output policy for the system prompt; errors are fixed codes. | `test_telemetry_leaks`, `test_output_policy`, `test_conversation_security`, `test_multi_user_isolation`. |
| LLM03:2026 | Excessive Agency | Covered | Read-only tools by default; scope per tool; `mutating` tools need a human approval of the exact arguments, once, bound to owner and thread; high-impact names deny-listed; no shell or `eval` tools; recursion and iteration limits. | `test_tool_denial`, `test_approval_api`, `test_approval_stream`, `test_authorization`, graph `test_approvals`, `approval` eval. |
| LLM04:2026 | Supply Chain | Partial | `uv.lock` with `pip-audit` in `make security`; 90-day rule for new dependencies (Python and npm); image pinned by digest, scanned and attested; MCP tool definitions pinned by SHA-256, operator-only server list. | `check_new_dependencies`, `check_new_npm_dependencies`, `test_mcp_pins`, `test_mcp_abuse`, the image-publish workflow. Limit: the attestation was never verified on a deployed image. |
| LLM05:2026 | Data and Model Poisoning | Partial | No training or fine-tuning, and no retrieval corpus. The writable stores are memory (user's own words, approved, per-user) and threads. A provider model is trusted as a supplier. | `test_memory_tools`, `test_memory_api`, memory security cases. Limit: no check on the provider's model. |
| LLM06:2026 | Unbounded Consumption | Covered | Token-bucket rate limit, per-user concurrent runs and rolling token budget (Postgres-shared), request body and prompt limits, provider and tool timeouts, run timeout, capped retries, stream cap, pool limits. v0.9.0 adds a measured load baseline. | `test_rate_limit_keys`, `test_shared_rate_limit`, `test_resource_limits`, `test_request_body_limit`, `test_token_attacks`; `docs/releases/v0.9.0-gate/load-baseline.json`. |
| LLM07:2026 | Misinformation | Partial | Structured answers with `refused` and `clarification_needed`; the quality eval suite. Correctness of a model's content is not guaranteed and the UI shows the model's words as text. | `tests/evals/test_agent_quality.py`, live eval baseline. Limit: live runs use the development model only. |
| LLM08:2026 | Hidden Context Exposure | Partial | System prompt is a versioned asset and never carries secrets; an output guard blocks a verbatim run of eight words of it; secrets stay in settings, not prompts. | `test_output_policy`, prompt-leak security cases. Limit: the guard is verbatim only (`SECURITY.md`). |
| LLM09:2026 | Vector and Embedding Weaknesses | Not applicable | There is no retrieval, embedding or vector store. ADR 0001, 0002 and 0005 forbid adding one without a requirement and a new ADR. | No test keeps retrieval out; the control is the ADR requirement in `CLAUDE.md` and `AGENTS.md`. Revisit if retrieval is ever added. |
| LLM10:2026 | Improper Output Handling | Covered | The API returns structured JSON and typed SSE events; the browser renders Markdown as React elements (no raw HTML, no images, restricted links) under a strict CSP; the approval card is built from the validated event only. | `Markdown.test.tsx`, `ChatScreen.test.tsx`, `ApprovalCard.test.tsx`, `test_web_headers`, `test_http_hardening`. Limit: the CSP was never enforced by a real browser (deferred). |

## OWASP Top 10 for Agentic Applications for 2026

| ID | Title | Status | Controls | Tests / evidence |
| --- | --- | --- | --- | --- |
| ASI01 | Agent Goal Hijack | Partial | As LLM01: injected text cannot widen scopes or tools; approval shows the exact arguments; tool output and notes are data. Once a thread has read an MCP result or the user's notes, every further MCP call (`read` included) needs approval, or is refused where no run can pause (`taints_run`, ADR 0009 amendment). | As LLM01, plus `approval` and security evals, `test_tainted_egress`. Limits: no quarantined reader model; MCP output reaches the model unwrapped (security review 2026-10-30). |
| ASI02 | Tool Misuse and Exploitation | Covered | Scope per tool; `mutating` default for MCP tools; MCP arguments checked against the pinned schema before the server is contacted (local `$ref`s only, no server-written regex run here); approval, also for MCP calls after untrusted or private data; size and time caps; `approval_when` refuses calls that cannot be valid (`remember` quotes the user). | `test_mcp_abuse`, `test_mcp_client`, `test_tainted_egress`, `test_approval_api`, `test_memory_tools`, `test_tool_egress`. |
| ASI03 | Identity and Privilege Abuse | Partial | Identity only from a verified JWT; the model never sees identity; owner key in the runtime context; request `user_id` ignored; per-tool scopes; the app database role has DML only. | `test_authorization`, `test_agent_server_auth`, `test_multi_user_isolation`, role-grant tests in `test_migrations_policy`. Limits: no token revocation (`SECURITY.md`); MCP calls use one operator token per server, not the caller's (no on-behalf-of exchange); owner isolation is in application code, not database row-level security (security review 2026-10-30, R3 and R5). |
| ASI04 | Agentic Supply Chain Vulnerabilities | Partial | As LLM04; MCP: https to public hosts, no stdio, no sampling, no redirects off origin, definition pins; `neuron-mcp-pin` shows the description and input schema for review. | `test_mcp_pins`, `test_mcp_abuse`, `test_mcp_wiring`. Limit: a pinned tool proves the definition, not the server's behaviour. |
| ASI05 | Unexpected Code Execution (RCE) | Covered | No tool executes code or a shell; dangerous names are deny-listed; the image runs as a non-root user; Bandit in CI. | `test_tool_denial` (deny-list), `make security` (Bandit). |
| ASI06 | Memory & Context Poisoning | Covered | Notes are the user's own words, approved, per-user, size-limited, escaped as data, listable and deletable; thread history is owner-scoped. | `test_memory_tools`, `test_memory_api`, `approval` eval. Limit: the item limit can be exceeded by concurrent writes. |
| ASI07 | Insecure Inter-Agent Communication | Not applicable | One agent, no agent-to-agent messages. ADR 0001 forbids multi-agent orchestration without an ADR. | None needed; revisit with any multi-agent design. |
| ASI08 | Cascading Failures | Partial | Timeouts and bounded retries, a run lease and per-user caps, fail-closed limiter, readiness gates, model fallback, no unbounded queues. The load baseline records the failure mode one step past the knee. | `test_resource_limits`, `test_shared_rate_limit`, resilience tests; the load baseline. Limit: nothing tested on a hosted multi-service deployment. |
| ASI09 | Human-Agent Trust Exploitation | Covered | The user approves exact arguments; the model cannot edit them; invisible characters are made visible; over-long arguments cannot be approved; the outcome comes from the click and the HTTP result. | `test_approval_api`, `test_approval_stream`, `ApprovalCard.test.tsx`, `ChatApproval.test.tsx`. |
| ASI10 | Rogue Agents | Partial | One agent whose tools, scopes and prompts are fixed in code and versioned; every tool call, denial and approval is audited; the allow-list stops new tools appearing at run time. | `test_tool_denial`, audit tests in `test_approval_api`. Limit: no runtime behavioural monitoring beyond the `NeuronDeniedToolCallsSpike` alert example. |

## Surfaces added in v0.7.0 and v0.8.0

| Surface | Main threats | Where covered |
| --- | --- | --- |
| Memory (v0.7.0) | Poisoning, cross-user recall, injection through a note, bulk write | ASI06 above; `test_memory_api`, `test_memory_tools`, security dataset v5 |
| Approvals and mutating tools (v0.7.0) | Forged, replayed or cross-user decision; approving something unread | ASI09, LLM03 above; `test_approval_api`, `ApprovalCard.test.tsx` |
| Browser and OIDC (v0.8.0) | Script injection, token theft, sign-in CSRF and mix-up, clickjacking, third-party calls | `SECURITY.md`, "Browser Application"; `session.test.ts`, `network.test.tsx`, `test_web_headers` |

## Known gaps and where they are filed

| Gap | Why it stays | Owner decision |
| --- | --- | --- |
| The CSP, silent renew and sign-in were never run in a real browser or against a real Keycloak (#290, #293) | Deferred until after v1.0.0 | 2026-10-27 |
| No external penetration test | After v1.0.0 | ADR 0012 open question 2 |
| Injected calls to permitted tools are invisible to the security eval | Needs a trace-level assertion in the harness | filed as an issue, `deferred:post-1.0` |
| Verbatim-only output guard (LLM08) | A semantic guard needs a design | `SECURITY.md` limitation, `deferred:post-1.0` |
| No token revocation (ASI03) | Local verification by design (ADR 0006) | `SECURITY.md` limitation |
| MCP calls use the operator's token, not the caller's; no database row-level security (ASI03) | Needs an identity-provider token-exchange design and an ADR | `docs/security/security-review-2026-10-30.md`, R3 and R5 |
| Concurrent memory writes can exceed the item limit (ASI06) | Check-then-write | `SECURITY.md` limitation, `deferred:post-1.0` |

The DAST scan (#331) adds runtime evidence for the API surface; its report is linked from the
v0.9.0 release verification.
