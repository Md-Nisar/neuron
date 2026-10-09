# Neuron Agent

Neuron Agent is a production-oriented Python baseline for a LangChain/LangGraph agent service. It provides a small deployable graph, typed configuration, a FastAPI API, structured logging, bounded tools, security checks, deterministic tests, and documentation for operating and extending the system.

![Neuron Agent — AI and LangGraph architecture](assets/neuron-readme-hero.png)

## Architecture Summary

The application uses a single LangGraph `StateGraph` with one agent node. The node invokes a LangChain `create_agent` harness configured with:

- a versioned system prompt in `src/neuron_agent/prompts/system/main.md`
- read-only tools: `utc_now` and `calculator`
- a structured output schema: `AgentAnswer`

The API layer validates HTTP input and delegates to `AgentService`; the graph does not know about HTTP objects.

Since v0.3.0, conversations are stateful and responses can be streamed (ADR 0005, `docs/decisions/0005-conversation-state-and-streaming.md`):
- **Persistence.** Thread history is persisted by a LangGraph checkpointer: in memory for local development, Postgres for production.
- **Streaming.** `POST /v1/agent/stream` returns server-sent events.

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

### Conversations

Every response returns a `thread_id`. Send it back to continue the same conversation, and the agent sees the earlier turns:

```bash
THREAD=$(curl -s -X POST http://127.0.0.1:8000/v1/agent/invoke \
  -H "Content-Type: application/json" \
  -d '{"message":"My name is Ada.","user_id":"user-123"}' | jq -r .thread_id)

curl -s -X POST http://127.0.0.1:8000/v1/agent/invoke \
  -H "Content-Type: application/json" \
  -d "{\"message\":\"What is my name?\",\"thread_id\":\"$THREAD\",\"user_id\":\"user-123\"}"
```

Thread rules:
- Thread IDs are server-minted UUIDs. Omit `thread_id` to start a new conversation.
- A supplied `thread_id` must belong to a thread created with the same `user_id`; otherwise the response is `404 thread_not_found`.
- A second request on a thread while a run is still in flight gets `409 thread_busy`.

Read or delete a thread. `user_id` goes in the `X-User-Id` header:

```bash
curl -s "http://127.0.0.1:8000/v1/threads/$THREAD/messages?limit=50" -H "X-User-Id: user-123"
curl -s -X DELETE "http://127.0.0.1:8000/v1/threads/$THREAD" -H "X-User-Id: user-123"   # 204
curl -s "http://127.0.0.1:8000/v1/me/threads?limit=50&offset=0" -H "X-User-Id: user-123"
curl -s "http://127.0.0.1:8000/v1/me/export?limit=5&offset=0&message_limit=20&message_offset=0" -H "X-User-Id: user-123"
curl -s -X DELETE "http://127.0.0.1:8000/v1/me/threads" -H "X-User-Id: user-123"
```

The `/v1/me/*` routes require `threads:read` for listing/export and `threads:delete` for bulk erasure in JWT mode. Export returns only user and assistant text and is bounded by `APP_USER_DATA_EXPORT_MAX_BYTES` (default 5 MB); use the returned pagination fields to fetch further threads/messages. Listing returns summaries without conversation content. See `SECURITY.md` for retention and coverage limitations. In local no-auth mode, `X-User-Id` is the development identity.

Persistence is selected with `APP_CHECKPOINTER`:
- `auto` (the default) keeps threads in memory in development and test. They're lost on restart.
- `postgres` is the setting for anything durable: see `OPERATIONS.md#thread-persistence-postgres`, or run `docker compose up` for a local API backed by Postgres.

### Streaming

`POST /v1/agent/stream` takes the same body as `/invoke` and streams server-sent events: `run_started`, then `token` events (answer text deltas) and `tool_call` events (tool names only), then `final` (the same fields as the `/invoke` response) or `error`, and finally `done`.

```bash
curl -N -X POST http://127.0.0.1:8000/v1/agent/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"What is 19 * 3?"}'
```

The browser's `EventSource` only supports `GET`, so read the stream with `fetch`. This minimal reader works in browsers and Node 18+:

```javascript
const response = await fetch("http://127.0.0.1:8000/v1/agent/stream", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ message: "What is 19 * 3?" }),
});
if (!response.ok) throw new Error(`HTTP ${response.status}: ${await response.text()}`);

const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
let buffer = "";
for (;;) {
  const { value, done } = await reader.read();
  if (done) break;
  buffer += value.replaceAll("\r\n", "\n");
  let end;
  while ((end = buffer.indexOf("\n\n")) !== -1) {
    const block = buffer.slice(0, end);
    buffer = buffer.slice(end + 2);
    const event = block.match(/^event: (.*)$/m)?.[1];
    const data = block.match(/^data: (.*)$/m)?.[1];
    if (!event) continue; // heartbeat comment
    const payload = JSON.parse(data);
    if (event === "token") process.stdout.write(payload.text); // in a browser, append to the page
    if (event === "final") console.log("\nfinal:", payload.answer);
    if (event === "error") console.error("\nerror:", payload.code, "retryable:", payload.retryable);
  }
}
```

Treat `token` events as a live preview. The `final` event carries the validated answer. Validation failures, `404`, `409`, `429` and `503` are ordinary HTTP errors returned before the stream starts.

## Request Limits

The `/v1/agent/invoke` and `/v1/agent/stream` endpoints enforce, before model execution:

- request body size, via `APP_MAX_REQUEST_BODY_BYTES` (default 65536 bytes; rejected with `413`)
- message length, via `APP_MAX_PROMPT_CHARS` (default 12000 characters; rejected with `400`)
- `thread_id` must be a UUID, and `user_id` is at most 128 chars
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
| Whole-run budget | `APP_RUN_TIMEOUT_SECONDS` | 120s | `504 run_timeout`, or a stream `error` event with `run_timeout` |
| Concurrent streams | `APP_MAX_CONCURRENT_STREAMS` | 100 per process | `503 too_many_streams` |
| Model history budget | `APP_MAX_HISTORY_TOKENS` | 8000 tokens | the oldest turns are left out of the model input |
| Stored history | `APP_MAX_THREAD_MESSAGES` | 200 messages | the oldest whole turns are evicted |
| Thread retention | `APP_THREAD_RETENTION_DAYS` | 30 days | `make prune-threads` deletes inactive threads |

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
- [Architecture decisions](docs/decisions/), including [ADR 0005: conversation state and streaming](docs/decisions/0005-conversation-state-and-streaming.md)

## Deployment

The repository includes `langgraph.json` for LangGraph Agent Server/LangSmith deployment and a Dockerfile for self-hosted HTTP deployment. Production deployments must provide secrets through environment-specific secret management, not source control.

- **Self-hosted (FastAPI):** set `APP_CHECKPOINTER=postgres` with `APP_POSTGRES_DSN`, and run `make db-setup` once per schema version. Staging and production default to stateless (`none`) unless configured.
- **Agent Server:** the exported graph has no checkpointer of its own. Agent Server provides persistence, threads and streaming through its own API, and the `/v1/threads/*` endpoints and `APP_CHECKPOINTER` don't apply there. See `OPERATIONS.md`.
