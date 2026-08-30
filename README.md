# Neuron Agent

Neuron Agent is a production-oriented Python baseline for a LangChain/LangGraph agent service. It provides a small deployable graph, typed configuration, a FastAPI API, structured logging, bounded tools, security checks, deterministic tests, and documentation for operating and extending the system.

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

```bash
uv sync
cp .env.example .env
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

LangGraph local server:

```bash
make run
```

## Quality Gates

```bash
make format
make lint
make typecheck
make test
make security
```

Integration tests are separated because live LLM calls require credentials and cost controls.

Live OpenAI smoke test:

```bash
export OPENAI_API_KEY=your-key
uv run pytest tests/integration/test_live_openai_smoke.py -m integration -q
```

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md)
- [DEVELOPMENT.md](DEVELOPMENT.md)
- [OPERATIONS.md](OPERATIONS.md)
- [SECURITY.md](SECURITY.md)
- [EVALUATION.md](EVALUATION.md)
- [AGENTS.md](AGENTS.md)

## Deployment

The repository includes `langgraph.json` for LangGraph Agent Server/LangSmith deployment and a Dockerfile for self-hosted HTTP deployment. Production deployments must provide secrets through environment-specific secret management, not source control.
