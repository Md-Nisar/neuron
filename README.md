# Neuron Agent

Neuron Agent is a production-oriented Python baseline for a LangChain/LangGraph agent service. It provides a small deployable graph, typed configuration, a FastAPI API, structured logging, bounded tools, security checks, deterministic tests, and documentation for operating and extending the system.

![Neuron Agent — AI and LangGraph architecture](assets/neuron-readme-hero.png)

## Architecture Summary

The application uses a single LangGraph `StateGraph` with one agent node. The node invokes a LangChain `create_agent` harness configured with:

- a versioned system prompt in `src/neuron_agent/prompts/system/main.md`
- read-only tools: `utc_now` and `calculator`
- a structured output schema: `AgentAnswer`

The API layer validates HTTP input and delegates to `AgentService`; the graph does not know about HTTP objects.

## Prerequisites

- Python 3.13
- `uv` 0.11 or newer
- Optional: `OPENAI_API_KEY` for live model calls

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

Set `OPENAI_API_KEY` in `.env` before live model execution. Without a key, development and test environments use a fake local chat model so health checks and deterministic tests still run.

## Running

```bash
make api
```

Health endpoints:

- `GET /health/live`
- `GET /health/ready`

Invoke:

```bash
curl -X POST http://127.0.0.1:8000/v1/agent/invoke \
  -H "Content-Type: application/json" \
  -d '{"message":"What is 19 * 3?"}'
```

## Request Limits

The `/v1/agent/invoke` endpoint enforces, before model execution:

- request body size, via `APP_MAX_REQUEST_BODY_BYTES` (default 65536 bytes; rejected with `413`)
- message length, via `APP_MAX_PROMPT_CHARS` (default 12000 characters; rejected with `400`)
- `thread_id` (max 255 chars) and `user_id` (max 128 chars)
- unknown request fields and malformed JSON (rejected with `422`)
- empty, whitespace-only, or control-character-containing messages (rejected with `400`)

Error responses return a stable `{"detail": "<error_code>"}` shape and never include internal validation details.

LangGraph local server:

```bash
make run
```

## Reliability Configuration

All reliability settings are `APP_`-prefixed environment variables read once in `config/settings.py::Settings` (see `.env.example` for the full annotated list). Defaults, in the order a request passes through them:

| Setting | Env var | Default | Behavior when exceeded |
| --- | --- | --- | --- |
| Rate limit | `APP_RATE_LIMIT_ENABLED`, `APP_RATE_LIMIT_REQUESTS_PER_WINDOW`, `APP_RATE_LIMIT_WINDOW_SECONDS`, `APP_RATE_LIMIT_BURST` | enabled, 60/60s, burst 20 | `429` with `Retry-After` header |
| Request body size | `APP_MAX_REQUEST_BODY_BYTES` | 65536 bytes | `413` |
| Prompt length | `APP_MAX_PROMPT_CHARS` | 12000 chars | `400 validation_error` |
| Provider request timeout | `APP_REQUEST_TIMEOUT_SECONDS` | 60s | `504 provider_timeout_error` |
| Tool call timeout | `APP_TOOL_TIMEOUT_SECONDS` | 20s | `502 tool_execution_error` (never user-visible detail) |
| Provider retries | `APP_PROVIDER_MAX_RETRIES` | 2 (3 attempts total) | exponential backoff + jitter, then the original provider error propagates |
| Agent loop iterations | `APP_MAX_AGENT_ITERATIONS` | 5 | `500 agent_execution_error` (recursion limit) |

See `ARCHITECTURE.md`'s Failure Handling and Rate Limiting sections for the full mechanics, and `OPERATIONS.md` for production configuration guidance.

## Quality Gates

```bash
make format
make lint
make typecheck
make test
make security
```

`make test` never makes live network calls — it only runs `tests/unit`, `tests/graph`, `tests/security`, `tests/resilience`, and the deterministic subset of `tests/evals`. Tests that call a real model provider live in `tests/integration` (`make test-integration`) and the credentialed subset of `tests/evals` (`make eval`); both require `OPENAI_API_KEY` and are skipped automatically without it, so they never run unintentionally in CI or on a fresh clone. See `EVALUATION.md` for the evaluation dataset and live agent-quality checks.

Live OpenAI smoke test (Unix):

```bash
export OPENAI_API_KEY=your-key
uv run pytest tests/integration/test_live_openai_smoke.py -m integration -q
```

Live OpenAI smoke test (PowerShell):

```powershell
$env:OPENAI_API_KEY = "your-key"
uv run pytest tests/integration/test_live_openai_smoke.py -m integration -q
```

## Troubleshooting

- **No `OPENAI_API_KEY` locally**: expected. `development`/`test` fall back to a fake local chat model (`create_chat_model` in `models/factory.py`); health checks and `make test` still pass. Only live calls (`make test-integration`, `make eval` with a key, or `make api` without a key against a real request) need one.
- **Settings fail to construct with a provider-key error**: `APP_ENV=staging` or `production` require `OPENAI_API_KEY`/`APP_OPENAI_API_KEY` to be set — this is `Settings.require_provider_key_outside_tests` failing fast on purpose.
- **Unexpectedly hitting `429 rate_limited` while testing locally**: the default limiter allows a burst of 20 and 60/min thereafter per client IP; set `APP_RATE_LIMIT_ENABLED=false` or raise the limits in `.env` for local load testing.
- **`mypy`/`ruff` failures on a fresh clone**: run `uv sync` first so the dev dependency group (ruff, mypy, bandit) is installed; `make format lint typecheck` assume `uv run` resolves against the synced `.venv`.
- **A test hangs instead of failing**: check whether it's unintentionally exercising the real `ChatOpenAI` client (a credential is set in the shell/`.env` where a test expected the fake model) — `APP_REQUEST_TIMEOUT_SECONDS`/`APP_TOOL_TIMEOUT_SECONDS` only bound the agent's own calls, not an unrelated hang in test setup.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [DEVELOPMENT.md](DEVELOPMENT.md)
- [OPERATIONS.md](OPERATIONS.md)
- [SECURITY.md](SECURITY.md)
- [EVALUATION.md](EVALUATION.md)
- [AGENTS.md](AGENTS.md)

## Deployment

The repository includes `langgraph.json` for LangGraph Agent Server/LangSmith deployment and a Dockerfile for self-hosted HTTP deployment. Production deployments must provide secrets through environment-specific secret management, not source control.
