---
name: add-graph-node
description: Use when adding or changing a node, edge, or routing logic in the LangGraph StateGraph under src/neuron_agent/graphs/, or extending MainGraphState.
---

# Add Graph Node

The graph in `src/neuron_agent/graphs/` is intentionally simple (`ARCHITECTURE.md`: `START -> agent -> END`). Any change here should stay deliberate — this skill sequences the requirements from `DEVELOPMENT.md` and `AGENTS.md` so state scope and docs don't drift.

## Steps

1. **Extend `MainGraphState` only with fields the graph actually owns.** Don't add fields for data that belongs in `services/` or a tool's own return value — state fields are for what the graph itself routes or persists on (`DEVELOPMENT.md`).

2. **Keep business logic out of the graph** where practical — put it in `services/` or a domain module, and have the node call into that (`DEVELOPMENT.md`, `ARCHITECTURE.md` component responsibilities table).

3. **Add explicit edges or conditional routing** — no implicit fallthrough. If routing depends on state, make the condition function testable in isolation.

4. **Add graph tests** in `tests/graph/` covering:
   - Happy path
   - Failure path (the node's error handling / `AppError` classification)
   - State transitions (fields set/cleared as expected across the edge)

5. **Update `ARCHITECTURE.md`**: the graph flow diagram (the `flowchart LR` under "Graph Flow") and, if state fields changed, the "State Model" section.

6. **Check for architectural creep**: if this change introduces retrieval, a queue, custom persistence, or a subgraph, stop — `AGENTS.md` requires a concrete requirement and an ADR update under `docs/decisions/` before adding any of those, not just a graph change.

7. **Run the quality gates**: `make format lint typecheck test`.

## Common mistakes

- Adding a state field "just in case" it's useful later — state is typed and shared across the graph; scope creep here is expensive to unwind.
- Routing logic embedded directly in a node function instead of an isolated, testable condition.
- Forgetting to update `ARCHITECTURE.md`'s Mermaid diagram, so the doc silently drifts from the actual graph shape.
