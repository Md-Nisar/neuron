# Development

## Setup

Unix (bash/zsh):

```bash
uv sync
cp .env.example .env
```

Windows (PowerShell):

```powershell
uv sync
Copy-Item .env.example .env
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

| Command | Scope | Needs `OPENAI_API_KEY` |
| --- | --- | --- |
| `make test` | `tests/unit tests/graph tests/security tests/resilience tests/evals` — deterministic only | no |
| `make test-integration` | `tests/integration` — live provider calls | yes (skipped without it) |
| `make eval` | `tests/evals -m eval` — live agent-quality regression | yes (skipped without it) |
| `make security` | `bandit -r src` | no |

Run a single test directly, e.g. `uv run pytest tests/unit/test_calculator.py::test_name -q` (PowerShell: same command, no shell-specific syntax needed).

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

## Troubleshooting

See `README.md`'s Troubleshooting section for the common local issues (missing provider key, rate limiting during manual testing, fresh-clone lint/type failures). Additionally, when developing:

- A changed `MainGraphState` field must be supplied by every direct graph-state construction in tests (`tests/graph/test_main_graph.py`, `tests/integration/test_live_openai_smoke.py`) — `AgentService.invoke` always supplies the full state, but tests that call `build_graph`/`call_agent` directly do not get it for free.
- `uv.lock` conflicts after a dependency bump: resolve by re-running `uv sync` and committing the regenerated lockfile rather than hand-editing it.
