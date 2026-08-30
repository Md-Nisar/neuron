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
