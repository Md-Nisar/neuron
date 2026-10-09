# Architecture

## Problem

Provide a maintainable AI agent application baseline that can be run locally, tested without provider credentials, and deployed through LangGraph-compatible infrastructure.

## Requirements

- LangChain/LangGraph agent orchestration.
- Typed request/response and graph state schemas.
- Centralized environment configuration.
- Bounded tool surface with explicit safety model.
- Structured logs and request/thread correlation.
- CI-ready linting, typing, tests, and security scanning.

## System Diagram

```mermaid
flowchart TD
    Client[Client] -->|POST /v1/agent/invoke JSON| API[FastAPI API]
    Client -->|POST /v1/agent/stream SSE| API
    Client -->|GET/DELETE /v1/threads/id| API
    API --> Service[AgentService]
    Service --> Graph[LangGraph StateGraph]
    Graph --> Agent[LangChain create_agent Harness]
    Agent --> Model[Configured Model Provider]
    Agent --> Tools[Read-only Tools]
    Graph --> State[Typed Graph State]
    Graph --> Checkpointer[Checkpointer: memory / Postgres / none]
    Service --> Checkpointer
    API --> Logs[Structured Logs]
    Graph --> LangSmith[LangSmith Tracing when enabled]
```

Request flow:
- **`/invoke`** returns one JSON response.
- **`/stream`** runs the same graph through a producer task and relays `astream` output as server-sent events (see Streaming).
- **Shared preparation:** both go through `AgentService.prepare`, which validates the request, resolves and authorizes the thread, and claims the run lease before any model call. Both commit the turn to the thread's checkpoint the same way.

## Graph Flow

```mermaid
flowchart LR
    START --> AgentNode[agent]
    AgentNode --> END
```

The graph is intentionally simple. It uses LangGraph for explicit state and deployment compatibility, while LangChain's agent harness owns the model/tool loop.

## Component Responsibilities

- `api/`: HTTP transport, health endpoints, HTTP error mapping.
- `services/`: application use cases and request normalization.
- `graphs/`: LangGraph construction and node behavior.
- `agents/`: high-level agent composition and approved tool wiring.
- `models/`: LangChain `create_agent` boundary, provider configuration, and provider/harness exception classification.
- `tools/`: bounded tool implementations.
- `state/`: graph state type definitions.
- `persistence/`: checkpointer construction and lifecycle (`APP_CHECKPOINTER`), plus the `setup` operator command.
- `schemas/`: public API and structured output contracts.
- `security/`: input, URL, and tool policy checks.
- `observability/`: structured logging setup.
- `prompts/`: versionable prompt assets.
- `errors/`: shared `AppError` taxonomy and HTTP/retry/visibility metadata.

## State Model

`MainGraphState` contains:
- message history (`messages`), the thread's persisted conversation;
- per-run fields, overwritten every turn: request ID, run ID, `user_message`, answer, and error;
- the thread ID;
- the optional owner value, which records the thread's owner. `AUTH_MODE=none`
  stores the v0.3.0 `user_id_hash`; JWT mode stores the HMAC owner key derived
  from the verified principal under ADR 0006.

Request-provided user IDs are hashed only in `AUTH_MODE=none`. JWT mode ignores
request identity fields and stores neither the raw principal claims nor the raw
request user ID.

A turn is committed atomically (ADR 0005). `AgentService` passes the new user text as `user_message` with an empty `messages` input. The `agent` node sends `history + HumanMessage(user_message)` to the agent and, only on success, appends that `HumanMessage` and the final `AIMessage` to `messages` while clearing `user_message`. A failed run leaves `messages` unchanged. Its `user_message` does remain in that run's checkpoint until the next turn overwrites it. History is only ever read from `messages`, so the stale value is never replayed. Like every turn's input, it is part of the stored checkpoint history, which is user data removed by thread deletion and retention (ADR 0005, decision 7). The agent's intermediate tool-call and tool-result messages are not persisted. Inputs that already carry the user turn in `messages`, as Agent Server and LangGraph Studio send them, still work: the node appends only the answer.

## Persistence

Thread persistence and streaming are governed by ADR 0005 (`docs/decisions/0005-conversation-state-and-streaming.md`): checkpointer selection per environment (`memory`, `postgres`, `none`), thread ID and ownership rules, atomic turn commits, history trimming, the SSE event protocol, and the reject-on-busy concurrency policy. The graph exported to `langgraph.json` is compiled without a checkpointer, because Agent Server supplies its own persistence.

`persistence/checkpointer.py::build_persistence` selects the backend from `APP_CHECKPOINTER`:
- `auto` is the default. It resolves to `memory` in development and test and to `none` in staging and production, so an upgrade never breaks an unconfigured deployment.
- `none` keeps v0.2.0's stateless behaviour.
- `memory` (`InMemorySaver`) is rejected in staging and production.
- `postgres` uses `AsyncPostgresSaver` over a `psycopg_pool.AsyncConnectionPool` sized by `APP_POSTGRES_POOL_MAX_SIZE` and `APP_POSTGRES_POOL_TIMEOUT_SECONDS`.

`AgentService` passes the checkpointer to `build_graph`. The FastAPI `lifespan` opens the pool on startup and closes it on shutdown. Schema creation is explicit: `make db-setup`, or `APP_CHECKPOINTER_SETUP_ON_STARTUP=true` for local use. `/health/ready` returns `503 {"status": "not_ready"}` while the database is unreachable. A `psycopg` failure during a run is classified as `PersistenceError` (`503 persistence_error`, retryable, detail hidden from clients). The DSN is a `SecretStr` and is never logged.

Thread rules (`AgentService._resolve_thread`):
- A request without `thread_id` starts a new thread with a server-minted UUIDv4.
- A supplied `thread_id` must be a UUID (`422 validation_error` otherwise) and is normalized to its canonical lowercase form.
- With persistence enabled, a supplied `thread_id` must name an existing thread
  whose stored owner value matches the effective caller. In `AUTH_MODE=none`
  this is the request-derived `user_id_hash`; JWT mode uses the principal HMAC
  owner key. A missing thread and another user's thread both return
  `404 thread_not_found`.
- With `none`, a supplied `thread_id` is only a correlation ID.

History bounds (`graphs/main_graph.py`, ADR 0005 decision 3):
- **Model input:** before each agent call, `bound_model_history` trims the thread to `APP_MAX_HISTORY_TOKENS` (default `8000`, approximate token count) with `trim_messages`. It keeps the newest messages as a contiguous suffix that starts on a `HumanMessage`, so a tool call is never separated from its result. The current user turn is always sent, even when it alone exceeds the budget; `APP_MAX_PROMPT_CHARS` bounds it instead. Trimming logs `history_trimmed` with message counts only.
- **Storage:** after each successful turn, `evict_oldest_turns` removes the oldest whole turns, through `RemoveMessage`, so a thread holds at most `APP_MAX_THREAD_MESSAGES` messages (default `200`).
- **No summarization:** `SummarizationMiddleware` is deliberately not used (ADR 0005), so no model-written summaries are persisted. Long-term memory (LangGraph `Store`) and domain persistence are not implemented because there is no product requirement yet.

## Streaming

`POST /v1/agent/stream` takes the same `AgentRequest` body as `/v1/agent/invoke` and returns `text/event-stream` (ADR 0005, decision 4). It is rate-limited and body-size-limited like `/invoke`.

- **Before the first byte:** `AgentService.prepare` validates the message and resolves the thread. Those failures (`422`, `400`, `404 thread_not_found`, `429`, `413`) are ordinary HTTP responses.
- **After the stream starts:** `AgentService.stream` drives `graph.astream(stream_mode=["messages", "updates"], subgraphs=True)`. `subgraphs=True` is required because `create_agent` runs as a nested graph inside the `agent` node; without it, LangGraph drops the model's token events.
- **Token filtering:** only `AIMessageChunk`s from the nested `model` node become `token` and `tool_call` events. The outer node's own output, which repeats the user turn and the final answer, is ignored.

Event protocol, version 1. Each event is an SSE `event:` name with a JSON `data:` payload:

| Event | Data | When |
| --- | --- | --- |
| `run_started` | `request_id`, `thread_id`, `run_id` | always first |
| `token` | `text` | answer delta; zero or more |
| `tool_call` | `name` | a real tool call starts; never arguments or results |
| `final` | `request_id`, `thread_id`, `answer`, `used_tools`, `confidence` | success; same shape as the `/invoke` response |
| `error` | `code`, `retryable` | failure after start; replaces `final` |
| `done` | `{}` | always last |

`token` deltas come from `services/streaming.py::AnswerTokenExtractor`:
- For JSON structured output, whether in message content or in the `AgentAnswer` tool-call arguments, it re-parses the partial JSON on each chunk (`parse_partial_json`) and emits only the growth of the `answer` field.
- Plain text is passed through.
- Other tools' arguments are never fed in.

Deltas are a best-effort preview; `final` is authoritative. `error` codes follow the same `user_visible` rule as HTTP errors, so internal failures appear as `internal_server_error`. Heartbeat comments are sent every `APP_STREAM_HEARTBEAT_SECONDS` (default `15`). Responses set `Cache-Control: no-cache` and `X-Accel-Buffering: no`. A streamed turn is persisted to the thread exactly like an `/invoke` turn.

### Thread history and lifecycle

ADR 0005, decision 7.

- **History.** `GET /v1/threads/{thread_id}/messages?limit=&offset=` returns `{thread_id, messages: [{role, content}], total, limit, offset}`, oldest first. `limit` is 1–100 (default 50). Only user and assistant turns with text are included.
- **Deletion.** `DELETE /v1/threads/{thread_id}` returns `204` after `adelete_thread` removes every checkpoint. It returns `409 thread_busy` while a run is in flight, because that run's final write would re-create the thread.
- **Ownership.** Both endpoints apply the same owner check as conversations. In v0.3.0, GET and DELETE use `X-User-Id` as the pre-auth identity because they have no body; v0.4.0 JWT mode derives ownership from the verified principal under ADR 0006. Missing, foreign and non-persisted threads all return `404 thread_not_found`.
- **Retention.** `persistence/retention.py::prune_threads` deletes threads whose newest root checkpoint is older than the cutoff. On Postgres this is one SQL aggregate; for other savers it scans `alist(None)`. Run it with `make prune-threads`.
- **Rate limiting** applies to every `/v1/agent/*` and `/v1/threads/*` route.

### Cancellation, timeouts and concurrency

ADR 0005, decisions 5 and 6.

- **Run lease.** `AgentService.prepare` claims a `RunLease` before any output. `invoke` and `stream` release it when the run ends, whatever the outcome. The SSE response class also releases it, and closes the stream, in a `finally` around the whole response, so it's freed even when sending fails before streaming begins; sse-starlette's own `background` hook would be skipped in that case. Release is idempotent.
  - **Busy thread:** with persistence enabled, a second run on a thread that already has a run in flight is rejected with `409 thread_busy`, and the first run is unaffected. Without persistence, `thread_id` is only a correlation ID and isn't guarded.
  - **Stream cap:** streams also take one of `APP_MAX_CONCURRENT_STREAMS` slots (default `100`); beyond that, `503 too_many_streams`.
  - **Per process:** both guards live in process memory. Like ADR 0004's rate limiter, they don't coordinate across replicas or workers.
- **Run timeout.** Every run, `invoke` or `stream`, is bounded by `APP_RUN_TIMEOUT_SECONDS` (default `120`), which covers all model calls, retries and tool calls. `APP_REQUEST_TIMEOUT_SECONDS` still bounds each individual provider call. For streams, the budget is enforced inside the producer task, so it holds even when the client stops reading. A client that doesn't accept data for 30 seconds is disconnected (`send_timeout`), which frees its lease. On timeout, `invoke` returns `504 run_timeout`; a stream emits `error {"code": "run_timeout", "retryable": true}`, then `done`.
- **Disconnect.** The graph runs in a producer task feeding a queue, and the SSE generator relays it. When the client disconnects, `sse-starlette` cancels the generator, whose `finally` cancels the producer exactly once and waits for it to unwind, logging `agent_stream_cancelled`. Cancelling LangGraph's `astream` cancels the running `agent` node, so model and tool calls stop.
  - The wait uses `asyncio.wait` inside a shielded, bounded anyio scope. A plain `await task` inside the already-cancelled anyio scope would forward a new `cancel()` to the producer on every retry, interrupting LangGraph's cleanup and orphaning the model call (covered by a regression test).
- **Shutdown.** On server shutdown, `sse-starlette` sets the stream's `shutdown_event`. The generator stops the run and sends `error {"code": "service_shutting_down", "retryable": true}` and `done` within a 2-second grace period.
- **Thread state.** A cancelled, timed-out or stopped run doesn't touch the thread's `messages`, because turns commit only on success. The thread can be continued immediately.

## Security Boundaries

The model is not trusted as a security boundary. Tool availability is enforced in application code. Current tools are read-only and bounded. External URLs are rejected if they target local hosts.

## Observability

Security events use the separate `neuron_agent.audit` logger and the fixed JSON schema
below (`timestamp` is UTC ISO-8601). Route this logger/`logger` field to a SIEM sink
independently of application logs. `actor` is only the first 12 hex characters of the
principal owner HMAC; `issuer_id` is the configured `APP_AUTH_ISSUER_ID` alias, never the
issuer URL. Fields with no applicable value are `null`. Reasons are stable codes, not
exception or claim text. Authentication success auditing is off by default and can be
enabled with `APP_AUTH_AUDIT_SUCCESS_ENABLED=true`.

```json
{"audit":true,"event":"authorization_denied","outcome":"denied","actor":"4a3f...","issuer_id":"primary","action":"threads:read","resource_type":"thread","resource_id":"00000000-0000-0000-0000-000000000001","request_id":"...","run_id":null,"reason":"insufficient_scope","count":null,"timestamp":"2026-10-10T12:00:00+00:00"}
```

Audit events never contain bearer tokens, raw claims/subjects, email addresses, client IPs,
prompts, answers or tool arguments. `observability/audit.py::audit` is the only emitter;
it accepts only explicit schema fields and emits through the dedicated logger.

Logs are JSON-formatted through `structlog` and include service, version, environment, request ID, and thread ID where available. LangSmith tracing can be enabled through environment variables.

`AgentService.invoke` generates a `run_id` per graph invocation alongside `request_id` (per HTTP call) and `thread_id` (per conversation), binds all three to `structlog`'s contextvars (`observability/logging.py::bind_correlation_context`), and passes `run_id` into the LangChain/LangGraph `RunnableConfig` so the same ID also tags the LangSmith trace when tracing is enabled. Because contextvars are merged into every log line for the duration of the request, correlation IDs appear on tool-call and provider-retry logs without those call sites needing to pass them explicitly.

Beyond correlation IDs, structured logs carry, where applicable: `model` (the configured `provider:model` identifier), `tool` (as `tool_name` on tool-call logs), `error_type` (the raw exception class name) alongside the stable `error_code` from the `AppError` taxonomy, `duration_ms` (per tool call, per agent execution, and per HTTP request), and `retry_count`/`retry_attempt` (provider-retry attempts tracked for the current agent execution via `models/factory.py::get_retry_attempts`). Key log events: `agent_request_completed`/`agent_request_failed`/`agent_request_unexpected_error` (API layer), `agent_execution_started`/`agent_execution_completed`/`agent_execution_failed` (graph layer), `tool_call_succeeded`/`tool_call_failed` and `provider_call_retry_candidate` (model/tool layer).

Streaming and conversation-state telemetry, listed in full in `OPERATIONS.md#streaming-and-conversation-state-events`:
- **Stream summary.** `services/agent_service.py::_StreamStats` emits one summary per stream: `stream_completed` with a `termination` reason or `stream_cancelled` on disconnect. It includes `ttft_ms`, `duration_ms`, and token and event counts. Correlation IDs are set explicitly on these events rather than relying on contextvars, because streams run across tasks.
- **Turn position.** `agent_execution_started` adds `turn` and `history_messages`.
- **Checkpoint I/O.** `persistence/checkpointer.py::instrument_checkpointer` wraps the saver's async read and write methods on the instance, so the saver keeps its class, and logs slow (at least 250 ms) or failed checkpoint operations. Logs carry the operation, backend and duration only, never keys, values or the DSN.
- **LangSmith.** Streamed runs pass the same `run_id` into the `RunnableConfig` as `invoke`, so they're tagged identically in LangSmith.

Logging never includes raw user prompts, tool arguments, exception text, or provider secrets — only stable, pre-classified fields (IDs, names, codes, counts, durations). API keys are read once in `models/factory.py::create_chat_model` and are never passed to a logger. See `SECURITY.md` for the broader logging/secrets policy.

## Scaling

The service is stateless except for provider clients and graph construction. Horizontal scaling is supported for the HTTP layer. Durable thread state requires Agent Server managed persistence or a configured production checkpointer.

## Failure Handling

Expected failures are classified through `AppError` subclasses (`src/neuron_agent/errors/base.py`), each carrying an `ErrorContext(code, http_status, retryable, user_visible, alert)`:

| Exception | Code | HTTP | Retryable | Client sees reason |
| --- | --- | --- | --- | --- |
| `ValidationAppError` | `validation_error` | 400 | no | yes |
| `AuthorizationError` | `authorization_error` | 403 | no | yes |
| `RateLimitError` | `rate_limit_error` | 429 | yes | yes |
| `ProviderQuotaError` | `provider_quota_exhausted` | 503 | no | no |
| `ProviderTimeoutError` | `provider_timeout_error` | 504 | yes | yes |
| `ConfigurationError` | `configuration_error` | 500 | no | no |
| `ProviderError` | `provider_error` | 502 | yes | no |
| `ToolExecutionError` | `tool_execution_error` | 502 | yes | no |
| `StructuredOutputError` | `structured_output_error` | 502 | yes | no |
| `AgentExecutionError` | `agent_execution_error` | 500 | yes | no |
| `PersistenceError` | `persistence_error` | 503 | yes | no |
| `ThreadNotFoundError` | `thread_not_found` | 404 | no | yes |
| `ThreadBusyError` | `thread_busy` | 409 | yes | yes |
| `CapacityError` | `too_many_streams` | 503 | yes | yes |
| `RunTimeoutError` | `run_timeout` | 504 | yes | yes |
| `ShuttingDownError` | `service_shutting_down` | 503 | yes | yes |

`api/main.py` centralizes the HTTP mapping: it raises `HTTPException(status_code=exc.context.http_status, detail=...)`, where `detail` is the stable `code` when `user_visible` is `True`, or the generic `internal_server_error` otherwise — so provider/tool/internal failure detail never reaches the client, only the server logs (via `logger.warning`/`logger.exception`). Any exception that isn't an `AppError` also maps to a generic `500 internal_server_error`.

`graphs/main_graph.py::call_agent` classifies failures from the agent loop by underlying exception type: `openai.RateLimitError` → `RateLimitError`, `openai.APITimeoutError` → `ProviderTimeoutError`, `openai.AuthenticationError` → `ConfigurationError`, any other `openai.OpenAIError` → `ProviderError`, `langchain`'s structured-output errors → `StructuredOutputError`, and anything else (including a LangGraph recursion-limit error) falls back to `AgentExecutionError`. `models/factory.py` raises `ConfigurationError` for an unsupported model provider or a malformed `provider:model` identifier. Health endpoints do not perform LLM calls.

Every tool call is bounded by `APP_TOOL_TIMEOUT_SECONDS` via a `wrap_tool_call` agent middleware (`models/factory.py::tool_timeout_middleware`); a tool that exceeds it raises `ToolExecutionError` directly, which `classify_agent_error` now passes through unchanged instead of reclassifying.

An outer `wrap_tool_call` middleware (`models/factory.py::tool_failure_isolation_middleware`) wraps every tool call — including timeouts from the middleware above — to log invocation metadata safely (`tool_name`, `duration_ms`, `error_code`; never raw arguments or exception text) and to isolate failures: an `AppError` (e.g. the calculator's `ValidationAppError` for invalid input) passes through unchanged, while any other exception is reclassified as `ToolExecutionError` so a tool bug can never surface an unclassified error or crash the agent loop. `calculator` additionally rejects expressions over 200 characters as `ValidationAppError` before parsing, bounding recursion depth during AST parsing/evaluation.

Model calls are retried up to `APP_PROVIDER_MAX_RETRIES` times (default `2`, i.e. up to 3 attempts total) via a `wrap_model_call` agent middleware (`models/factory.py::provider_retry_middleware`, built on `langchain`'s `ModelRetryMiddleware`) with exponential backoff (`backoff_factor=2.0`, `initial_delay=1.0s`, `max_delay=60.0s`) and jitter; only transient provider failures (`openai.APIConnectionError`, `APITimeoutError`, `RateLimitError`, `InternalServerError`) are retried — anything else (auth, malformed requests, unrecognized errors) propagates immediately. `on_failure="error"` means retry exhaustion re-raises the original exception rather than returning a degraded answer, so it still flows through `classify_agent_error`. The OpenAI SDK's own client-level retries are disabled (`max_retries=0` on `ChatOpenAI`) so this middleware is the single, centralized retry policy. Each attempt still respects `APP_REQUEST_TIMEOUT_SECONDS`; retries are not wrapped in an additional aggregate timeout.

## Rate Limiting

Every `/v1/agent/*` and `/v1/threads/*` route is protected by a token-bucket limiter, and health endpoints are exempt. This is (`security/rate_limiter.py::InMemoryTokenBucketRateLimiter`, ADR 0004) applied in `api/main.py` before the request reaches `AgentService`. Keyed by client IP, with capacity `APP_RATE_LIMIT_BURST` (default `20`) refilling at `APP_RATE_LIMIT_REQUESTS_PER_WINDOW` / `APP_RATE_LIMIT_WINDOW_SECONDS` (default `60` requests per `60`s). An exceeded limit returns `429 {"detail": "rate_limited"}` with an integer `Retry-After` header, independent of the unrelated `RateLimitError` in the `AppError` taxonomy above (which classifies the *model provider's* rate limiting, not this API-boundary control). The limiter is in-process and resets on restart; it does not coordinate across multiple worker processes or instances (see ADR 0004's Consequences). Disable with `APP_RATE_LIMIT_ENABLED=false`.
