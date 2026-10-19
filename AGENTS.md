# Coding Agent Instructions

## Architecture Rules

- Keep HTTP concerns in `api/`.
- Keep request orchestration in `services/`.
- Keep graph construction and node routing in `graphs/`.
- Keep provider and LangChain harness construction in `models/`.
- Keep prompts under `prompts/`.
- Do not scatter environment reads outside `config/`. The one exception is `observability/langsmith_governance.py`, which overwrites LangSmith's own `LANGSMITH_*`/`LANGCHAIN_*` variables because the library reads them itself (ADR 0007, section 5).
- Do not add retrieval, queues, custom persistence, or subgraphs without a concrete requirement and ADR update.

## Commands

Run before delivery:

```bash
make format
make lint
make typecheck
make test
make security
```

## Forbidden Patterns

- No raw `eval` or shell execution tools.
- No committed secrets.
- No live LLM calls in unit tests.
- No mutating tools without authorization, idempotency, and tests.
- No prompt-only security controls.

## Framework Upgrades

Before changing LangChain or LangGraph versions, re-check official docs, update `uv.lock`, run all quality gates, and add regression tests for graph state and structured output behavior.

## Verifying AI-Generated Code

Follow `docs/AI_CODE_VERIFICATION.md`. In short: keep changes small (under 400 lines where possible), write tests that fail without the change, never add a dependency without stating why and confirming it is the intended PyPI project, fill in the PR template's AI assistance, risk tier and verification sections, and keep the `Co-Authored-By:` commit trailer. AI review comments are advisory; a human approves every merge.
