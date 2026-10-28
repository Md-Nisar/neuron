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
| `make security` | `bandit -r src`, then `pip-audit` of every package locked in `uv.lock` (queries PyPI advisories, see `SECURITY.md`) | no |

Run a single test directly, e.g. `uv run pytest tests/unit/test_calculator.py::test_name -q` (PowerShell: same command, no shell-specific syntax needed).

## Token Usage Report

Session transcripts exist only in the session container. Before a session ends, and again at release time, run the report and commit it (counts only, no prompt or response text):

```bash
uv run python scripts/token_report.py <transcript-dir> -o docs/releases/<version>-token-usage.md
```

It sums input, output, cache-read and cache-write tokens per agent, grouped by issue number (the most frequent `#<number>` in the agent prompt; otherwise "unattributed") and by role (implement, review, CI fix, other, from prompt keywords). It reports tokens, not money. Record each merged issue's tokens, review rounds and CI re-pushes in the tracker row (#161).

## Adding a Tool

1. Add the tool under `src/neuron_agent/tools/`.
2. Define a narrow input contract and bounded side effects.
3. Register it in `tools/registry.py` (`builtin_registry`) with a `ToolSpec`: its scope (`tools:<name>`, or none for a public read-only builtin) and risk class (`read` or `mutating`). The allow-list, scope checks, audit names and span names all derive from the spec; a tool without one is not offered or callable. A `mutating` tool needs human approval (ADR 0009 decision 6) and the agent refuses to build without it until that is wired. Names on `HIGH_RISK_TOOL_NAMES` in `security/input_policy.py` are always refused.
4. Add the scope to `DEV_PERMISSIONS` if development should grant it.
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

The default `APP_AUTH_MODE=none` needs no token. To exercise real JWT authentication locally, run `make dev-auth >> .env` once, keep `make dev-jwks` running, and send `Authorization: Bearer $(make -s dev-token)` (README "Authentication"). These tools refuse to run unless `APP_ENV=development`. Tests never use them: they mint tokens with the `make_token` fixture in `tests/conftest.py`.

## Troubleshooting

See `README.md`'s Troubleshooting section for the common local issues (missing provider key, rate limiting during manual testing, fresh-clone lint/type failures). Additionally, when developing:

- A changed `MainGraphState` field must be supplied by every direct graph-state construction in tests (`tests/graph/test_main_graph.py`, `tests/integration/test_live_openai_smoke.py`) — `AgentService.invoke` always supplies the full state, but tests that call `build_graph`/`call_agent` directly do not get it for free.
- `uv.lock` conflicts after a dependency bump: resolve by re-running `uv sync` and committing the regenerated lockfile rather than hand-editing it.
