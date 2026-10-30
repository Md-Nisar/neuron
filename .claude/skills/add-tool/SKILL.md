---
name: add-tool
description: Use when adding a new tool under src/neuron_agent/tools/, or wiring an existing tool into the agent — covers the input contract, authorization, wiring, tests, and doc updates this project requires for every tool.
---

# Add Tool

Neuron Agent tools are bounded, and every new one must go through the same checklist (from `DEVELOPMENT.md` / `AGENTS.md` / `SECURITY.md`) before it's wired in. Read those three files if not already in context — this skill just sequences their requirements so none get skipped.

## Steps

1. **Implement** the tool under `src/neuron_agent/tools/`.
   - Give it a narrow, typed input contract (Pydantic model or equivalent) — no untyped dict passthrough.
   - Bound its side effects explicitly. Read-only tools are the default; anything else needs step 2's checklist.
   - No raw `eval`/`exec`/shell execution — see the existing calculator tool (`src/neuron_agent/tools/time.py` for the read-only pattern) for the AST-based style this project uses instead.

2. **Register it** in `src/neuron_agent/tools/registry.py` (`builtin_registry`) with a `ToolSpec`: scope `tools:<name>` (none only for a public, read-only builtin) and risk `read` or `mutating`. The allow-list, scope checks and audit/span names derive from it; a tool without a spec is not callable.
   - A `mutating` tool needs human approval (ADR 0009 decision 6): work through the full "Future Mutating Tools" checklist in `SECURITY.md` (authorization outside the model, idempotency keys, retry policy, audit logs). Names on `HIGH_RISK_TOOL_NAMES` in `security/input_policy.py` are refused whatever the spec says.
   - Add the scope to `DEV_PERMISSIONS` if development should grant it.

3. **Wiring** is automatic: `agents/factory.py` builds the agent from the registry.

4. **Add tests**:
   - Unit test for the happy path (`tests/unit/`).
   - Failure-path test (bad input, bounds exceeded).
   - Security test in `tests/security/` — at minimum, an unauthorized-call test; if mutating, also a duplicate-execution test.
   - No live LLM calls in these tests (`AGENTS.md`).

5. **Update docs** if the tool mutates external state:
   - `SECURITY.md` — add it to the relevant section.
   - The matching ADR under `docs/decisions/`, or a new one if this introduces a new category of side effect.

6. **Run the quality gates** before calling it done: `make format lint typecheck test security`.

## Common mistakes

- Registering a tool with a broader scope or a lower risk class than it deserves; `read` means it changes nothing outside the run.
- Treating tool *output* as trusted downstream — it isn't (`SECURITY.md` trust boundaries).
- Skipping the security test because "it's read-only" — read-only tools still need an unauthorized-call test if they accept any input the model controls.
