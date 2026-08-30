# ADR 0002: Persistence and Memory

## Status

Accepted.

## Decision

The application distinguishes three forms of state:

- Graph state: per-run and per-thread fields such as messages, request ID, thread ID, and normalized answer.
- Short-term memory: delegated to LangGraph Agent Server persistence when deployed through LangSmith/LangGraph infrastructure.
- Long-term memory/domain persistence: not implemented because no product requirement exists.

Local direct invocation compiles the graph without a custom checkpointer. This avoids presenting in-memory persistence as production durability. Production deployment should use Agent Server managed persistence or an explicitly selected checkpointer/store.

## Consequences

Local tests stay deterministic and simple. Multi-container resumability depends on the documented deployment path rather than hidden process memory.
