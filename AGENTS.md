# Coding Agent Instructions

## Architecture Rules

- Keep HTTP concerns in `api/`.
- Keep request orchestration in `services/`.
- Keep graph construction and node routing in `graphs/`.
- Keep provider and LangChain harness construction in `models/`.
- Keep prompts under `prompts/`.
- Do not scatter environment reads outside `config/`.
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
