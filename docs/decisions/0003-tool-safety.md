# ADR 0003: Tool Safety Model

## Status

Accepted.

## Decision

The initial approved tool set is read-only:

- `utc_now`: current UTC timestamp.
- `calculator`: bounded arithmetic evaluator with AST validation and no `eval`.

Tool authorization is enforced outside the model loop through `require_allowed_tool`. High-impact tool names are explicitly blocked until a human approval workflow and idempotency strategy are implemented.

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
