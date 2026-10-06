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
    Client[Client] --> API[FastAPI API]
    API --> Service[AgentService]
    Service --> Graph[LangGraph StateGraph]
    Graph --> Agent[LangChain create_agent Harness]
    Agent --> Model[Configured Model Provider]
    Agent --> Tools[Read-only Tools]
    Graph --> State[Typed Graph State]
    API --> Logs[Structured Logs]
    Graph --> LangSmith[LangSmith Tracing when enabled]
```

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
- `schemas/`: public API and structured output contracts.
- `security/`: input, URL, and tool policy checks.
- `observability/`: structured logging setup.
- `prompts/`: versionable prompt assets.
- `errors/`: shared `AppError` taxonomy and HTTP/retry/visibility metadata.

## State Model

`MainGraphState` contains message history, request ID, thread ID, run ID, optional hashed user ID, answer, and error fields. User IDs are hashed before entering telemetry-oriented state.

## Persistence

Thread persistence and streaming are governed by ADR 0005 (`docs/decisions/0005-conversation-state-and-streaming.md`): checkpointer selection per environment (`memory`, `postgres`, `none`), thread ID and ownership rules, atomic turn commits, history trimming, the SSE event protocol, and the reject-on-busy concurrency policy. The graph exported to `langgraph.json` is compiled without a checkpointer, because Agent Server supplies its own persistence. Long-term memory (LangGraph `Store`) and domain persistence are not implemented because there is no product requirement yet.

## Security Boundaries

The model is not trusted as a security boundary. Tool availability is enforced in application code. Current tools are read-only and bounded. External URLs are rejected if they target local hosts.

## Observability

Logs are JSON-formatted through `structlog` and include service, version, environment, request ID, and thread ID where available. LangSmith tracing can be enabled through environment variables.

`AgentService.invoke` generates a `run_id` per graph invocation alongside `request_id` (per HTTP call) and `thread_id` (per conversation), binds all three to `structlog`'s contextvars (`observability/logging.py::bind_correlation_context`), and passes `run_id` into the LangChain/LangGraph `RunnableConfig` so the same ID also tags the LangSmith trace when tracing is enabled. Because contextvars are merged into every log line for the duration of the request, correlation IDs appear on tool-call and provider-retry logs without those call sites needing to pass them explicitly.

Beyond correlation IDs, structured logs carry, where applicable: `model` (the configured `provider:model` identifier), `tool` (as `tool_name` on tool-call logs), `error_type` (the raw exception class name) alongside the stable `error_code` from the `AppError` taxonomy, `duration_ms` (per tool call, per agent execution, and per HTTP request), and `retry_count`/`retry_attempt` (provider-retry attempts tracked for the current agent execution via `models/factory.py::get_retry_attempts`). Key log events: `agent_request_completed`/`agent_request_failed`/`agent_request_unexpected_error` (API layer), `agent_execution_started`/`agent_execution_completed`/`agent_execution_failed` (graph layer), `tool_call_succeeded`/`tool_call_failed` and `provider_call_retry_candidate` (model/tool layer).

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
| `ProviderTimeoutError` | `provider_timeout_error` | 504 | yes | yes |
| `ConfigurationError` | `configuration_error` | 500 | no | no |
| `ProviderError` | `provider_error` | 502 | yes | no |
| `ToolExecutionError` | `tool_execution_error` | 502 | yes | no |
| `StructuredOutputError` | `structured_output_error` | 502 | yes | no |
| `AgentExecutionError` | `agent_execution_error` | 500 | yes | no |

`api/main.py` centralizes the HTTP mapping: it raises `HTTPException(status_code=exc.context.http_status, detail=...)`, where `detail` is the stable `code` when `user_visible` is `True`, or the generic `internal_server_error` otherwise — so provider/tool/internal failure detail never reaches the client, only the server logs (via `logger.warning`/`logger.exception`). Any exception that isn't an `AppError` also maps to a generic `500 internal_server_error`.

`graphs/main_graph.py::call_agent` classifies failures from the agent loop by underlying exception type: `openai.RateLimitError` → `RateLimitError`, `openai.APITimeoutError` → `ProviderTimeoutError`, `openai.AuthenticationError` → `ConfigurationError`, any other `openai.OpenAIError` → `ProviderError`, `langchain`'s structured-output errors → `StructuredOutputError`, and anything else (including a LangGraph recursion-limit error) falls back to `AgentExecutionError`. `models/factory.py` raises `ConfigurationError` for an unsupported model provider or a malformed `provider:model` identifier. Health endpoints do not perform LLM calls.

Every tool call is bounded by `APP_TOOL_TIMEOUT_SECONDS` via a `wrap_tool_call` agent middleware (`models/factory.py::tool_timeout_middleware`); a tool that exceeds it raises `ToolExecutionError` directly, which `classify_agent_error` now passes through unchanged instead of reclassifying.

An outer `wrap_tool_call` middleware (`models/factory.py::tool_failure_isolation_middleware`) wraps every tool call — including timeouts from the middleware above — to log invocation metadata safely (`tool_name`, `duration_ms`, `error_code`; never raw arguments or exception text) and to isolate failures: an `AppError` (e.g. the calculator's `ValidationAppError` for invalid input) passes through unchanged, while any other exception is reclassified as `ToolExecutionError` so a tool bug can never surface an unclassified error or crash the agent loop. `calculator` additionally rejects expressions over 200 characters as `ValidationAppError` before parsing, bounding recursion depth during AST parsing/evaluation.

Model calls are retried up to `APP_PROVIDER_MAX_RETRIES` times (default `2`, i.e. up to 3 attempts total) via a `wrap_model_call` agent middleware (`models/factory.py::provider_retry_middleware`, built on `langchain`'s `ModelRetryMiddleware`) with exponential backoff (`backoff_factor=2.0`, `initial_delay=1.0s`, `max_delay=60.0s`) and jitter; only transient provider failures (`openai.APIConnectionError`, `APITimeoutError`, `RateLimitError`, `InternalServerError`) are retried — anything else (auth, malformed requests, unrecognized errors) propagates immediately. `on_failure="error"` means retry exhaustion re-raises the original exception rather than returning a degraded answer, so it still flows through `classify_agent_error`. The OpenAI SDK's own client-level retries are disabled (`max_retries=0` on `ChatOpenAI`) so this middleware is the single, centralized retry policy. Each attempt still respects `APP_REQUEST_TIMEOUT_SECONDS`; retries are not wrapped in an additional aggregate timeout.

## Rate Limiting

`/v1/agent/invoke` (only — health endpoints are exempt) is protected by a token-bucket limiter (`security/rate_limiter.py::InMemoryTokenBucketRateLimiter`, ADR 0004) applied in `api/main.py` before the request reaches `AgentService`. Keyed by client IP, with capacity `APP_RATE_LIMIT_BURST` (default `20`) refilling at `APP_RATE_LIMIT_REQUESTS_PER_WINDOW` / `APP_RATE_LIMIT_WINDOW_SECONDS` (default `60` requests per `60`s). An exceeded limit returns `429 {"detail": "rate_limited"}` with an integer `Retry-After` header, independent of the unrelated `RateLimitError` in the `AppError` taxonomy above (which classifies the *model provider's* rate limiting, not this API-boundary control). The limiter is in-process and resets on restart; it does not coordinate across multiple worker processes or instances (see ADR 0004's Consequences). Disable with `APP_RATE_LIMIT_ENABLED=false`.
