# ADR 0009: Extensible Agent Platform (v0.7.0)

## Status

Proposed. Inputs: `docs/research-notes.md` ("v0.7.0 Research" and its addendum). Supersedes
one clause of ADR 0005 (decision 6). Production deployment stays configured but is not
exercised or tested until after v1.0.0 (owner decision, 2026-10-27); every check in this
release runs locally, on the NVIDIA development model, with fakes where a provider has no
key.

## Context

The roadmap theme for v0.7.0 is "Tools + models + HITL + memory". ADR 0001, 0002 and 0003
deferred memory, retrieval, human approval and mutating tools until a product requirement
exists. None was written down, so the owner asked for one to be chosen.

**Product requirement (chosen for the owner to confirm).** A personal assistant that
remembers what a user explicitly asks it to remember, and does so only with the user's
approval:

1. A user can say "remember that I prefer metric units", and the agent can use that in a
   later thread.
2. Nothing is stored until the user has seen the exact text and approved it.
3. A user can list, delete and export their memories, and erasing a user erases them.
4. Operators can add read-only tools from MCP servers, for example a unit converter that
   makes (1) visible end to end.
5. The model provider is a setting: NVIDIA (development), OpenAI, Anthropic, with an
   optional fallback chain.

It is small on purpose. It needs approvals (a real mutating tool), per-user storage, the
tool registry, MCP and a second provider, and it needs nothing else: no retrieval, no
embeddings, no background jobs. Anything beyond it needs a new requirement and ADR.

## Decisions

1. **Order of work.** (0) Framework bump. (A) Provider-neutral models. (B) Tool registry
   and MCP. (C) Approvals. (D) Memory. A, then B, are independent of the product
   requirement; C needs B; D needs C. Each is its own set of issues and PRs, under 400
   changed lines where possible.

2. **Framework bump first, on its own.** `langchain>=1.4.7`, `langgraph` 1.2.18,
   `langchain-core` 1.7.0 (the scratch lock resolves cleanly). Per AGENTS.md: re-check the
   upstream docs, update `uv.lock`, run all gates, and add regression tests for graph
   state and structured output before merging. It brings per-call interrupts and `v3`
   streaming, which this ADR does not adopt (decision 6 uses the batched mode).

3. **Models.** Providers `openai`, `nvidia` and `anthropic` (`langchain-anthropic`).
   - `classify_agent_error` maps the provider-neutral `langchain-core` types
     (`ModelRateLimitError`, `ModelAuthenticationError`, `ModelNotFoundError`, and the
     rest) first, then the `openai.*` classes as now, so a second provider does not fall
     through to `agent_execution_error`.
   - `APP_FALLBACK_MODELS` (a list, default empty) installs `ModelFallbackMiddleware`.
     Each fallback use is logged and counted (`neuron.model.fallbacks`, by from/to), with
     no content. The eval harness runs with an empty list and never falls back, so a
     lost model shows as an error, not a quiet switch.
   - The invalid-`AgentAnswer` retry is bounded (at most two retries), then fails with
     `422 structured_output_error` instead of running until `run_timeout`.
   - Token accounting records cache read and write tokens where a provider reports them.
   - **Estimated cost is dropped from v0.7.0** (third deferral): there is no verifiable,
     dated price data, and the development model is free. It returns with production.
   - The Anthropic path is tested with fakes and recorded responses only; it is not
     verified live and the release notes say so.

4. **Tool registry.** One `ToolSpec` per tool in `tools/registry.py`: name, the tool, the
   required scope (`tools:<name>`), a risk class (`read` or `mutating`), and its source
   (`builtin` or `mcp`). The allow-list, scope checks, approval configuration and span
   names derive from the registry; `HIGH_RISK_TOOL_NAMES` becomes a defence-in-depth test
   that no mutating tool is registered without approval. A tool without a spec is not
   callable.

5. **MCP (in scope, tightly bounded).** Through `langchain.mcp` (`MCPAdapter`, beta), a
   new dependency tree of 28 packages (research notes, addendum). Rules:
   - **Transport:** Streamable HTTP only. stdio is refused: it starts a subprocess from
     configuration, which is code execution (OWASP ASI05). SSE and WebSocket are refused.
   - **Configuration:** servers come only from `APP_MCP_SERVERS` (a file path to JSON),
     never from a request or the model. Each entry has a name, a URL, the tools to expose
     with a pinned SHA-256 of each tool's name, description and input schema, and a risk
     class per tool (default `mutating`). A tool not listed, or whose definition no longer
     matches its pin, is not registered and is logged (rug-pull defence). The tool list is
     read once at start-up; `list_changed` notifications are ignored.
   - **Trust:** annotations (`readOnlyHint` and the rest) are untrusted and never decide
     authorization. Tool names are prefixed `mcp_<server>_`; scope is
     `tools:mcp.<server>.<tool>`.
   - **Network:** a URL must pass `validate_safe_url` and be `https`; loopback `http` is
     allowed only in `development` and `test`. The client sends the configured bearer
     secret for that server, never the user's token (MCP security page: no token
     passthrough). Sampling, roots and elicitation are disabled.
   - **Results:** text content only, capped at `APP_MCP_MAX_OUTPUT_BYTES`; other content
     types are an error. A result is untrusted tool output, like any other. The existing
     tool timeout and failure isolation apply.
   - **Reference server:** an in-repo test server (`convert_units`) over loopback, so
     tests and evals run offline.

6. **Approvals (supersedes ADR 0005 decision 6).** `HumanInTheLoopMiddleware` in batched
   mode, configured from the registry: every `mutating` tool is gated, with
   `allowed_decisions=["approve", "reject"]` only (no `edit`, no `respond`).
   - The agent is compiled with `checkpointer=None`, inheriting the main graph's. The
     research spike showed `checkpointer=False` loses an approved call silently. Thread
     history stays user turns and final answers: the history, export and thread-summary
     routes read only `messages`, and a test asserts it. When `APP_CHECKPOINTER=none` the
     agent gets no gated tools.
   - A pause ends the run: the lease is released and tokens are settled. The response is
     `200` with `status: "approval_required"` and the pending action (tool name and
     arguments, shown in full). `POST /v1/agent/stream` sends an `approval_required` event.
   - `POST /v1/threads/{thread_id}/approvals/{approval_id}` with `decision` `approve` or
     `reject` is a new run with its own lease, rate limit, budget and timeout, scope
     `agent:approve`. A missing, foreign or already-decided approval is the same `404`;
     the decision is single-use and bound to the pending call.
   - A new message on a thread with a pending approval is refused (`409
     approval_pending`). There is no separate expiry store: the pending state lives in the
     thread and is removed by thread retention.
   - `call_agent` re-runs on resume, so anything it does before the agent call must be
     idempotent; tokens are counted per model call, and a test pins that a resumed run
     counts each model call once.
   - Audit events `approval_requested` and `approval_decided`; a span event and a metric
     by outcome. The tool must run exactly once after `approve` and never after `reject`;
     both have tests.

7. **Memory.** Behind `APP_MEMORY_ENABLED` (default false), on the FastAPI path only
   (Agent Server supplies its own store; memory is not offered there).
   - **Store:** LangGraph's `BaseStore`: `InMemoryStore` for the memory and none
     checkpointers, `AsyncPostgresStore` on the shared pool for `postgres`. Namespace
     `("memories", owner_key)`, with the HMAC owner key, never the raw subject.
   - **No semantic search.** No embedding provider, no `store_vectors`, no pgvector. A
     user's memories are few and short (`APP_MEMORY_MAX_ITEMS`, default 50;
     `APP_MEMORY_MAX_CHARS`, default 500), so `recall` returns them all, optionally
     filtered by substring. Semantic search needs a new ADR.
   - **Tools:** `remember(text)` and `forget(memory_id)` are `mutating`, so they need
     approval; `recall()` is `read`. The key is a hash of the normalised text, so
     `remember` is idempotent. Text passes the same input policy as a user message.
     Memories are written only from text the user sent, never from tool output.
   - **Not injected into the prompt.** `recall` returns the memories in a delimited
     block marked as untrusted data; they appear in the trajectory and in traces as a
     count, not text (OWASP ASI06). Injection into the system context is a later,
     measured change.
   - **User rights:** `GET /v1/me/memories`, `DELETE /v1/me/memories/{id}` and
     `DELETE /v1/me/memories` (scopes `memories:read`, `memories:write`); the export
     route includes memories and the erase routes delete them; the audit log records
     counts. `APP_MEMORY_TTL_DAYS` (default 0, off) uses the store's `expires_at`.
   - **Database:** `setup` (as the migrator) runs the store's `setup()`; the app role gets
     `SELECT, INSERT, UPDATE, DELETE` on `store` only, extending the #144 grant table and
     its tests. The store's index is built `CONCURRENTLY`, like the checkpointer's.

8. **Observability.** New names live in `observability/semconv.py`, marked neuron-specific:
   spans `approval` and `memory.<op>`, outcome `interrupted`, metrics for fallbacks,
   approvals by decision and memory operations by outcome. No prompt, answer, tool
   argument or memory text in telemetry (the v0.5.0 leak scan covers the new paths).

9. **Evaluation.** Every capability ships with its eval cases in the same PR, code-graded,
   on the NVIDIA model: approvals (reject means the tool did not run), memory (a second
   user never sees the first user's memories; injected text in a memory does not change
   behaviour), MCP (a changed tool definition is not callable; a poisoned description is
   inert), and provider fallback (a 404 model falls back and is counted). The security
   suite gains these as dataset v5. The nightly gate must be passing again first.

10. **Production.** Settings validation for staging and production is extended (MCP
    URLs `https` only, memory needs a Postgres store and the role grants, approvals need
    the Postgres checkpointer). It is covered by unit tests and not deployed.

## Consequences

- The agent can finally take an action, so ADR 0003's "no mutating tools" becomes "no
  mutating tool without approval", enforced by the registry and tests.
- Thread storage grows (internal steps are checkpointed), and a pause leaves state that
  only retention removes.
- `langchain.mcp` is beta and `fastmcp` brings a large tree; the pin, the audit and the
  start-up-only tool list limit the exposure, but an upgrade can break MCP. MCP is the
  first thing to cut if the schedule slips.
- The NVIDIA model's tool-calling quality bounds what the evals can show; a weak result
  is recorded as a model limit, not hidden.
- No second provider is verified live.

## Alternatives considered

- Keep `checkpointer=False` and build approvals outside LangGraph: more custom
  persistence, which ADR 0002 forbids.
- Semantic memory with pgvector: needs an embedding provider and a vector extension, and
  nothing in the requirement needs it.
- MCP over stdio, or tool lists fetched live: both turn configuration or a remote server
  into code or behaviour we did not review.
- Prompt-injected memory: better recall, larger poisoning surface; deferred.
