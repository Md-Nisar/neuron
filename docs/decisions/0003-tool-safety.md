# ADR 0003: Tool Safety Model

## Status

Accepted.

## Decision

The initial approved tool set is read-only:

- `utc_now`: current UTC timestamp.
- `calculator`: bounded arithmetic evaluator with AST validation and no `eval`.

Tool authorization is enforced outside the model loop through `require_allowed_tool`. High-impact tool names are explicitly blocked until a human approval workflow and idempotency strategy are implemented. [ADR 0009](0009-extensible-agent-platform.md) (v0.7.0) defines that workflow: a tool registry with a risk class, human approval of every `mutating` tool, and MCP tools pinned and default-`mutating`.

## Consequences

The agent has useful deterministic capabilities for smoke tests without creating side-effect risk. Future mutating tools must add authorization, idempotency keys, tests, and documentation before being exposed.

## Addendum: Timeout and Failure Isolation

Every tool call is additionally bounded by `APP_TOOL_TIMEOUT_SECONDS` (default `20`s) and wrapped so a tool bug can never crash the agent loop or surface an unclassified error: an exceeded timeout or any non-`AppError` exception is reclassified as `ToolExecutionError` (never user-visible detail, logged as `tool_name`/`duration_ms`/`error_code` only). A tool's input-validation failure (`ValidationAppError`) is the exception: it is returned to the model as a fixed-text tool error message, with no input echoed, so the run continues and the model can correct the call or answer (#101). Timeouts still end the run. See `ARCHITECTURE.md`'s Failure Handling section (`models/factory.py::tool_timeout_middleware`, `tool_failure_isolation_middleware`) for the full mechanics.

## Addendum: Denied tool calls are tool errors (#99)

A tool call the caller lacks the permission for, or a call to an unknown tool, used to raise `AuthorizationError` and end the run with `403`. The live security eval at the v0.5.0 release gate showed prompt-injected tool calls turning a user's run into a `403`, though the tool never ran either way. A denied call is now returned to the model as a tool error, so it can answer or refuse.

Consequences:
- The tool never executes; the check runs immediately before execution, as before.
- The model gets one constant text, identical for unknown and unpermitted tools, with no arguments or permission names.
- The `authorization_denied` audit event and the `insufficient_scope`/`unknown_tool` policy-block metric are kept; the `execute_tool` span and tool metric record outcome `denied`.
- A denied call is not listed in `used_tools`.
- A model that keeps calling a denied tool is bounded by `APP_MAX_AGENT_ITERATIONS` and ends with `422 agent_step_limit_exceeded`.
- Route-level scope checks still return `403`.

## Addendum: Output guard for system prompt disclosure (#124)

The system prompt is guidance, and the live security eval showed the model quoting its rules when asked. The prompt now says not to share its instructions, but a prompt rule is not a control, so the answer is also checked in code.

- `security/output_policy.py` normalises the answer and the loaded prompt (`prompts/loader.py`) to lowercase alphanumeric words and flags the answer when any `LEAK_NGRAM_WORDS` (8) consecutive words also occur in the prompt. Case, whitespace, markdown and punctuation do not matter. It reads the real prompt, so editing the prompt needs no list to maintain, and it does not use the eval's `SYSTEM_PROMPT_MARKERS`.
- Eight words: ordinary answers share runs of up to six or seven words with the prompt ("neuron agent a concise production assistant", "tool output as untrusted content"), while a quoted rule or the opening line is eight or more. Shorter runs would refuse ordinary answers; longer runs would let more of a quote through.
- It runs in `call_agent` (`graphs/`) after the structured answer is built and before it is stored, so `invoke`, the stream's `final` event and Agent Server's final state share it. Agent Server's live message streams are not guarded. A hit replaces the answer with a fixed refusal, sets `refused` and clears `clarification_needed`. The `system_prompt_disclosure_blocked` log, the `output_blocked` audit event and the `system_prompt_disclosure` policy-block metric carry IDs and the answer length only.
- `AgentService.stream` passes answer deltas through `StreamLeakGuard`, which holds back the last eight words and stops sending after a hit, so a quote cannot stream out before the final check. The held-back tail is sent when the answer is not blocked.

Consequences: only verbatim reproduction is blocked; paraphrases and translations are not (`SECURITY.md`, Remaining Limitations). A model reply that repeats the prompt's opening line is refused.
