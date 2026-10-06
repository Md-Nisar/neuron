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

Every tool call is additionally bounded by `APP_TOOL_TIMEOUT_SECONDS` (default `20`s) and wrapped so a tool bug can never crash the agent loop or surface an unclassified error: an exceeded timeout or any non-`AppError` exception is reclassified as `ToolExecutionError` (never user-visible detail, logged as `tool_name`/`duration_ms`/`error_code` only). See `ARCHITECTURE.md`'s Failure Handling section (`models/factory.py::tool_timeout_middleware`, `tool_failure_isolation_middleware`) for the full mechanics.
