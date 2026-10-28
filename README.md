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
- Optional: `OPENAI_API_KEY`, or `NVIDIA_API_KEY` for free-tier development models, for live model calls

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

For development you can use a model from NVIDIA's API catalog instead (`build.nvidia.com`, which offers OpenAI-compatible models on a free tier): set `NVIDIA_API_KEY` and `APP_DEFAULT_MODEL=nvidia:<model-id>`, such as a model ID from the catalog's model list. The app calls NVIDIA's OpenAI-compatible endpoint (`https://integrate.api.nvidia.com/v1`) through the same client, retries and error handling. The model must support tool calling. The free tier is for development and evaluation; keep real user data off it.

Anthropic is a third provider (`ANTHROPIC_API_KEY` or `APP_ANTHROPIC_API_KEY`, `APP_DEFAULT_MODEL=anthropic:<model-id>`). It is covered by unit tests with fakes only: v0.7.0 has no funded Anthropic key, so it has **not been run against the live API**. Without a key, development and test fall back to the local fake model, like the other providers.

To keep answering when the default model is down or unavailable to the account, list fallbacks: `APP_FALLBACK_MODELS='["anthropic:<model-id>"]'`. They are tried in order after the default model's own retries; each switch is logged and counted by model id.

## Authentication

Every `/v1/*` route requires an OAuth 2.0 / OIDC bearer access token (a signed JWT) when `APP_AUTH_MODE=jwt`, which staging and production enforce (ADR 0006). The token's verified issuer and subject identify the caller and own their threads; scopes grant permissions:

| Scope | Allows |
| --- | --- |
| `agent:invoke` | `POST /v1/agent/invoke`, `POST /v1/agent/stream` |
| `agent:approve` | `GET /v1/threads/{id}/approval` (read the pending approval), `POST /v1/threads/{id}/approvals/{approval_id}` (decide a tool call that needs approval) |
| `threads:read` | `GET /v1/threads/{id}/messages`, `GET /v1/me/threads`, `GET /v1/me/export` |
| `threads:delete` | `DELETE /v1/threads/{id}`, `DELETE /v1/me/threads` |
| `memories:read` | `GET /v1/me/memories` |
| `memories:write` | `DELETE /v1/me/memories/{id}`, `DELETE /v1/me/memories` |
| `tools:calculator` | lets the agent use the `calculator` tool |
| `tools:mcp.<server>.<tool>` | lets the agent use that MCP tool |

### Approving a tool call

A tool whose risk is `mutating` (an MCP tool configured that way, or a future built-in) never runs without a human decision. When the model calls one, `POST /v1/agent/invoke` returns `200` with `"status": "approval_required"` and the call exactly as the model made it:

```json
{"status": "approval_required", "request_id": "...", "thread_id": "...",
 "approval": {"approval_id": "...", "actions": [{"name": "...", "args": {}}],
              "allowed_decisions": ["approve", "reject"]}}
```

The run has ended; nothing was done. Decide it with `POST /v1/threads/{thread_id}/approvals/{approval_id}` and `{"decision": "approve"}` or `{"decision": "reject"}` (scope `agent:approve`). That starts a new run, with its own rate limit, token budget and timeout, and returns the usual answer (or another `approval_required`). You cannot edit the call; reject and ask again. A client that reloaded can read the pending approval again with `GET /v1/threads/{thread_id}/approval` (scope `agent:approve`: only someone who can decide it sees the arguments); it returns the same `approval_required` object, or the same `404 approval_not_found` when nothing is pending. A decision is single-use: an unknown, someone else's or already-decided approval is the same `404 approval_not_found`. While a decision is pending the thread refuses new messages with `409 approval_pending`. Approvals need thread persistence (not `APP_CHECKPOINTER=none`). Over SSE, `POST /v1/agent/stream` ends with an `approval_required` event (same `approval` object) instead of `final`, and `POST /v1/threads/{thread_id}/approvals/{approval_id}/stream` decides it and streams the continuation. `tool_call` events still carry only the tool name; the arguments appear only in the approval.

`.env.example` starts in `APP_AUTH_MODE=none`, a development-only mode with no authentication in which every caller is the same untrusted local identity. To run locally with real tokens and no identity provider, use the development token tools (development only; they refuse to run unless `APP_ENV=development`):

```bash
make dev-auth >> .env   # once: creates a signing key in .dev/ and appends the jwt settings
make dev-jwks           # terminal 1: serves the public key on http://127.0.0.1:8765/jwks.json
make api                # terminal 2: the API, now in jwt mode
TOKEN=$(make -s dev-token)   # terminal 3: a 1-hour token for subject dev-user with every scope
```

`uv run python scripts/dev_token.py --sub alice --scope "agent:invoke threads:read"` mints a token for another subject or with fewer scopes. To connect a real identity provider, see `OPERATIONS.md#identity-provider`.

Errors: a missing, expired or otherwise invalid token gets `401 authentication_error` with `WWW-Authenticate: Bearer error="invalid_token"`; a valid token without the route's scope gets `403 authorization_error`; if the identity provider's keys can't be fetched, `503 authentication_unavailable`.

## Running

```bash
make api
```

Health endpoints (never authenticated):

- `GET /health/live`
- `GET /health/ready`

Invoke:

```bash
curl -X POST http://127.0.0.1:8000/v1/agent/invoke \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"What is 19 * 3?"}'
```

In `APP_AUTH_MODE=none`, leave out the `Authorization` header.

### Conversations

Every response returns a `thread_id`. Send it back to continue the same conversation, and the agent sees the earlier turns:

```bash
THREAD=$(curl -s -X POST http://127.0.0.1:8000/v1/agent/invoke \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"My name is Ada."}' | jq -r .thread_id)

curl -s -X POST http://127.0.0.1:8000/v1/agent/invoke \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"message\":\"What is my name?\",\"thread_id\":\"$THREAD\"}"
```

Thread rules:
- Thread IDs are server-minted UUIDs. Omit `thread_id` to start a new conversation.
- A thread belongs to the token subject that created it. Anyone else gets `404 thread_not_found`, exactly as for a thread that doesn't exist.
- A second request on a thread while a run is still in flight gets `409 thread_busy`.

Read or delete a thread, and list, export or erase all of your threads:

```bash
AUTH="Authorization: Bearer $TOKEN"
curl -s "http://127.0.0.1:8000/v1/threads/$THREAD/messages?limit=50" -H "$AUTH"
curl -s -X DELETE "http://127.0.0.1:8000/v1/threads/$THREAD" -H "$AUTH"   # 204
curl -s "http://127.0.0.1:8000/v1/me/threads?limit=50&offset=0" -H "$AUTH"
curl -s "http://127.0.0.1:8000/v1/me/export?limit=5&offset=0&message_limit=20&message_offset=0" -H "$AUTH"
curl -s -X DELETE "http://127.0.0.1:8000/v1/me/threads" -H "$AUTH"
```

The messages endpoint also returns each assistant tool call as `tool_calls`: `name`, a bounded `summary` of the arguments (at most 200 characters, built by the server) and a `status` of `pending` (waiting for an approval), `completed`, `failed` or `rejected`. Tool output is never returned.

Export returns only user and assistant text and is bounded by `APP_USER_DATA_EXPORT_MAX_BYTES` (default 5 MB); use the returned pagination fields to fetch further threads/messages. Listing returns summaries without conversation content. See `SECURITY.md` for retention and coverage limitations.

Persistence is selected with `APP_CHECKPOINTER`:
- `auto` (the default) keeps threads in memory in development and test. They're lost on restart.
- `postgres` is the setting for anything durable: see `OPERATIONS.md#thread-persistence-postgres`, or run `docker compose up` for a local API backed by Postgres.

### Streaming

`POST /v1/agent/stream` takes the same body as `/invoke` and streams server-sent events: `run_started`, then `token` events (answer text deltas) and `tool_call` events (tool names only), then `final` (the same fields as the `/invoke` response) or `error`, and finally `done`.

```bash
curl -N -X POST http://127.0.0.1:8000/v1/agent/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message":"What is 19 * 3?"}'
```

The browser's `EventSource` can't send a body or an `Authorization` header, so read the stream with `fetch`. This minimal reader works in browsers and Node 18+. A browser page on another origin also needs that origin in `APP_CORS_ALLOWED_ORIGINS`:

```javascript
const token = process.env.TOKEN; // in a browser, the access token from your OIDC client
const response = await fetch("http://127.0.0.1:8000/v1/agent/stream", {
  method: "POST",
  headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
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

Treat `token` events as a live preview. The `final` event carries the validated answer. Authentication, validation and authorization failures, `404`, `409`, `429` and `503` are ordinary HTTP errors returned before the stream starts. A token that expires mid-stream doesn't end the stream; it's checked once, at the start.

## Memory (optional)

With `APP_MEMORY_ENABLED=true` the assistant can keep notes for each user, only when the user asks and only after they approve (ADR 0009). The `remember` tool saves only words the user wrote; `recall` reads them back; `forget` deletes one (scopes `tools:remember`, `tools:recall`, `tools:forget`). Users see and control their notes without the model: `GET /v1/me/memories` lists them, `DELETE /v1/me/memories/{id}` and `DELETE /v1/me/memories` delete them, `GET /v1/me/export` includes them on its first page, and `DELETE /v1/me/threads` (erase my data) deletes them with the threads (`erased_memory_count`). Deleting a single thread does not delete memories. Memories are stored per user (the owner key, never the raw identity) with the limits `APP_MEMORY_MAX_ITEMS`, `APP_MEMORY_MAX_CHARS` and `APP_MEMORY_TTL_DAYS`. Run `setup` after enabling it on Postgres. Not available through Agent Server.

## MCP tools (optional)

The agent can use read-only tools from an [MCP](https://modelcontextprotocol.io) server you run or trust (ADR 0009). Nothing is loaded unless you set `APP_MCP_SERVERS`.

1. Start a server. For a local try-out: `uv run python scripts/mcp_reference_server.py` (a unit converter on `http://127.0.0.1:8765/mcp`).
2. Pin it: `uv run neuron-mcp-pin http://127.0.0.1:8765/mcp --name units`. It prints each tool's description (read it) and a config entry with a SHA-256 pin of the tool's name, description and input schema.
3. Save the entry in a file as `{"servers": [ ... ]}`, set `"risk": "read"` for tools that change nothing, and point `APP_MCP_SERVERS` at it. A remote server must be `https`; give it a token with `APP_MCP_BEARER_TOKENS='{"units": "<token>"}'` (or `"auth": "none"`).
4. Grant the scope `tools:mcp.<server>.<tool>` to the users who may use it (development with `APP_AUTH_MODE=none` grants all).

A tool whose definition later differs from its pin, or that is not in the file, is not registered. Only Streamable HTTP is supported (no stdio). Tools are read once at start-up, so restart after changing the server or the file. Tools marked (or defaulting to) `mutating` are refused until human approval exists.

## Migrating from 0.3.x

0.4.0 replaces caller-chosen identity with verified tokens. Breaking changes:

- **Bearer tokens are required in staging and production.** Settings refuse to start there unless `APP_AUTH_MODE=jwt` with an issuer, audience, HTTPS JWKS URL and `APP_IDENTITY_HASH_KEY` (`OPERATIONS.md#identity-provider`). Send `Authorization: Bearer <token>` on every `/v1/*` request.
- **`user_id` and `X-User-Id` no longer identify the caller.** In jwt mode they are ignored: identity comes from the token's `(iss, sub)`. Remove them from clients. They still work in `APP_AUTH_MODE=none`, for local development only.
- **Existing threads aren't carried over.** Ownership is now an HMAC of the verified identity, so threads created under 0.3.x return `404` in jwt mode and expire through retention. `OPERATIONS.md#upgrade-from-v03-identity-to-jwt-ownership` has the rollout.
- **New error responses:** `401 authentication_error`, `403 authorization_error`, `503 authentication_unavailable`, `429 quota_exceeded` (per-user token budget) and `429 too_many_concurrent_runs` (per-user run cap). Both `429`s carry `Retry-After`.
- **Rate limits** key on the verified principal instead of the client IP; failed authentication is still limited per IP.
- **Responses** to `/v1/*` are `Cache-Control: no-store`, and `/docs`, `/redoc` and `/openapi.json` are hidden in staging and production unless `APP_EXPOSE_API_DOCS=true`.
- **Postgres:** re-run `make db-setup` to create the index behind `/v1/me/*`.

## Request Limits

The `/v1/agent/invoke` and `/v1/agent/stream` endpoints enforce, before model execution:

- request body size, via `APP_MAX_REQUEST_BODY_BYTES` (default 65536 bytes; rejected with `413`)
- message length, via `APP_MAX_PROMPT_CHARS` (default 12000 characters; rejected with `400`)
- `thread_id` must be a UUID (and, in `APP_AUTH_MODE=none` only, `user_id` is at most 128 chars)
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
| Agent loop iterations (model calls) | `APP_MAX_AGENT_ITERATIONS` | 8 | `422 agent_step_limit_exceeded` |
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

`make test` never makes live network calls — it only runs `tests/unit`, `tests/graph`, `tests/security`, `tests/resilience`, and the deterministic subset of `tests/evals`. Pytest deselects the `integration` and `eval` markers unless you select them with `-m`, and every other test runs with provider keys blanked, even if `.env` holds one. Tests that call a real model provider live in `tests/integration` (`make test-integration`) and the credentialed subset of `tests/evals` (`make eval`). They use `APP_DEFAULT_MODEL` and its provider key from the shell or `.env`, and are skipped when that key isn't set. See `EVALUATION.md` for the evaluation dataset and live agent-quality checks.

Live smoke test against the configured model (Unix). With the key and model in `.env`, the `export` lines aren't needed:

```bash
export OPENAI_API_KEY=your-key  # or NVIDIA_API_KEY plus APP_DEFAULT_MODEL=nvidia:<model-id>
uv run pytest tests/integration/test_live_openai_smoke.py -m integration -q
```

Live smoke test (PowerShell):

```powershell
$env:OPENAI_API_KEY = "your-key"  # or NVIDIA_API_KEY plus APP_DEFAULT_MODEL
uv run pytest tests/integration/test_live_openai_smoke.py -m integration -q
```

## Troubleshooting

- **No `OPENAI_API_KEY` locally**: expected. `development`/`test` fall back to a fake local chat model (`create_chat_model` in `models/factory.py`); health checks and `make test` still pass. Only live calls (`make test-integration`, `make eval` with a key, or `make api` without a key against a real request) need one.
- **Settings fail to construct with a provider-key error**: `APP_ENV=staging` or `production` require the selected provider's key (`OPENAI_API_KEY`/`APP_OPENAI_API_KEY`, `NVIDIA_API_KEY`/`APP_NVIDIA_API_KEY` for `nvidia:` models, or `ANTHROPIC_API_KEY`/`APP_ANTHROPIC_API_KEY` for `anthropic:` models) to be set — this is `Settings.require_provider_key_outside_tests` failing fast on purpose.
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

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) and [NOTICE](NOTICE) files for details.
