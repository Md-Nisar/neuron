# Changelog

## 0.3.0

"Stateful + Streaming": multi-turn conversations and real-time responses (ADR 0005).

- ADR 0005 records the design: checkpointer selection, thread rules, atomic turns, history bounds, the SSE protocol, the concurrency policy, and data retention. It partially supersedes ADR 0002 (#20).
- Configurable thread persistence through `APP_CHECKPOINTER`: `auto` (the default), `memory`, `postgres` or `none`. Postgres uses `AsyncPostgresSaver` over a validated connection pool opened in the FastAPI lifespan, with `make db-setup` migrations, readiness that reflects database health, and a `PersistenceError` (`503`) error type (#21).
- Multi-turn conversations: the server mints UUID thread IDs, each thread is bound to its hashed `user_id` (`404 thread_not_found` for missing and foreign threads alike), turns commit atomically, and the nested agent's internal state is never checkpointed (#22).
- Bounded history: a model-input token budget (`APP_MAX_HISTORY_TOKENS`) that never splits tool pairs, and a stored-message cap (`APP_MAX_THREAD_MESSAGES`) that evicts whole turns (#23).
- `POST /v1/agent/stream`: server-sent events (`run_started`, `token`, `tool_call`, `final`, `error`, `done`) with answer-field token extraction from structured output. Tool arguments are never streamed (#24).
- Cancellation and concurrency: client disconnects cancel the run, `APP_RUN_TIMEOUT_SECONDS` bounds whole runs, a busy thread gets `409 thread_busy`, `APP_MAX_CONCURRENT_STREAMS` caps open streams, and shutdown closes streams gracefully. Includes fixes for an anyio cancellation bug that kept model calls running after a disconnect, and a lease leak (#25).
- Thread history and lifecycle API: `GET /v1/threads/{id}/messages` and `DELETE /v1/threads/{id}`, plus `make prune-threads` retention through `APP_THREAD_RETENTION_DAYS` (#26).
- Streaming and state telemetry: stream lifecycle events with time to first token, termination reasons, turn and history size, and checkpoint latency and failure logging (#27).
- Eval dataset v2 (13 multi-turn cases), conversation security tests, and a live streaming smoke test. `neuron-eval` writes clean JSON to stdout again (#28).
- Operations documentation: Postgres, reverse-proxy settings for SSE, runbook entries, a `docker compose` stack with Postgres, and the full `.env.example` (#29).
- Release verification (#30) found and fixed a defect present since 0.2.0: every Agent Server or LangGraph Studio run failed, because inputs without a `run_id` crashed `agent_invocation_config`.

## 0.2.0

"Reliable Agent Runtime" — predictable failures, bounded execution, and operational visibility.

- Runtime error taxonomy: `AppError` subclasses with stable codes, HTTP mapping, retryability, and visibility metadata (#1).
- Enforced runtime limits: request/tool timeouts, agent iteration cap, prompt/body size limits (#2).
- Bounded provider retry with exponential backoff and jitter for transient model-provider failures (#3).
- Hardened tool execution boundaries: per-call timeout and failure isolation so a tool bug can never crash the agent loop (#4).
- Hardened request validation: body size limits, rejected-unknown-fields policy, control-character rejection (#5).
- Application-level token-bucket rate limiting at `/v1/agent/invoke`, keyed by client IP, with `429`/`Retry-After` (#6, ADR 0004).
- Expanded failure-and-resilience regression test suite covering every classified failure mode (#7).
- Agent evaluation dataset v1 with deterministic shape checks and live agent-quality scoring (#8).
- Structured logging and error telemetry: correlation IDs (`request_id`/`thread_id`/`run_id`) propagated via `structlog` contextvars and the LangSmith trace, plus `model`, `error_type`, `duration_ms`, and `retry_count` on key log events (#9).
- Documented reliability behavior and operations: timeout/retry/rate-limit configuration, the full failure-response taxonomy, production configuration expectations, and local troubleshooting across `README.md`, `OPERATIONS.md`, `DEVELOPMENT.md`, `SECURITY.md`, `ARCHITECTURE.md`, and ADR 0003 (#10).
- Fixed a defect found during release verification: the documented no-credentials fallback (a fake local chat model) crashed every `/v1/agent/invoke` call, because `create_agent` always binds tools and the fake model didn't support it (#11).

## 0.1.0

- Initial production-oriented LangChain/LangGraph agent service baseline.
