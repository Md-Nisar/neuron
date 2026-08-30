# Development

## Setup

```bash
uv sync
cp .env.example .env
```

Use Python 3.13. The local machine may have newer Python versions, but CI and deployment metadata target 3.13 for framework compatibility.

## Commands

```bash
make format
make lint
make typecheck
make test
make test-integration
make eval
make security
make api
make run
```

## Adding a Tool

1. Add the tool under `src/neuron_agent/tools/`.
2. Define a narrow input contract and bounded side effects.
3. Add authorization requirements to `security/input_policy.py`.
4. Wire it in `agents/factory.py`.
5. Add unit, failure, and security tests.
6. Update `SECURITY.md` and the relevant ADR if the tool mutates external state.

## Adding a Graph Node

1. Extend `MainGraphState` only with fields the graph owns.
2. Keep business logic in services or domain modules when practical.
3. Add explicit edges or conditional routing.
4. Add graph tests for happy path, failure path, and state transitions.
5. Update `ARCHITECTURE.md`.

## Changing Prompts

Prompts live under `src/neuron_agent/prompts/`. Prompt changes should include eval cases for the intended behavior and security regression cases for injection resistance.

## Debugging

Run `make api` for HTTP debugging or `make run` for LangGraph Studio-compatible local development. Do not add provider secrets to source control.
