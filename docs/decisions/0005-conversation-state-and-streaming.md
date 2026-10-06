# ADR 0005: Conversation State and Streaming

## Status

Accepted. Partially supersedes ADR 0002 (the "local invocation has no checkpointer" decision).

## Problem

v0.3.0 ("Stateful + Streaming", `docs/ROADMAP.md`) requires multi-turn conversations and real-time responses. Today:

- `AgentRequest.thread_id` is accepted and forwarded as `configurable.thread_id`, but `build_graph()` compiles **without a checkpointer**, so every request starts with an empty history. `thread_id` is only a log correlation ID.
- ADR 0002 delegates short-term memory to LangGraph Agent Server. The self-hosted FastAPI path (`make api`, `Dockerfile`) has no persistence at all.
- The only response mode is a single blocking JSON payload from `POST /v1/agent/invoke`.

`AGENTS.md` forbids custom persistence without an ADR. This ADR records the decisions v0.3.0 issues #21–#29 implement.

## Requirements

- Conversations continue across requests, process restarts, and multiple API replicas when a durable backend is configured.
- `make test` stays deterministic and needs no external services.
- The `langgraph.json` / Agent Server deployment keeps working unchanged.
- Responses can be streamed incrementally, with the same validation, limits, error taxonomy, and redaction rules as `/invoke`.
- Conversation data at rest has a defined retention and deletion story.

## Decisions

### 1. Checkpointer selection

A new `persistence/` module owns checkpointer construction, selected by `APP_CHECKPOINTER`:

| Value | Saver | Allowed in |
| --- | --- | --- |
| `memory` (default) | `langgraph.checkpoint.memory.InMemorySaver` | `development`, `test` |
| `postgres` | `langgraph.checkpoint.postgres.aio.AsyncPostgresSaver` over a `psycopg_pool.AsyncConnectionPool` (`autocommit=True`, `row_factory=dict_row`, `prepare_threshold=0`) | any |
| `none` | no checkpointer: stateless, v0.2.0 behaviour | any |

- `memory` is rejected at startup in `staging` and `production`. Process memory isn't durable and isn't shared across replicas (the same reasoning ADR 0002 used).
- The Postgres DSN is a `SecretStr` read only through `Settings`, and it's never logged.
- The pool is opened and closed in the FastAPI `lifespan`. Schema creation (`AsyncPostgresSaver.setup()`) is an explicit, idempotent operator step (`make db-setup`), with an opt-in `APP_CHECKPOINTER_SETUP_ON_STARTUP` for local use. It never runs implicitly per request.
- The module-level `graph` exported to `langgraph.json` is always compiled **without** a checkpointer. Agent Server injects its own persistence. Only `AgentService` passes a checkpointer to `build_graph`.
- Checkpoint serialization registers `neuron_agent.schemas.agent.AgentAnswer` in `allowed_msgpack_modules`. Without it, LangGraph warns that deserializing an unregistered type stored in state will be blocked in a future version.

Rejected:
- SQLite: not shared across replicas.
- Redis: an additional service without a requirement.
- A custom repository layer: duplicates what checkpointers already do.

### 2. Thread semantics and isolation

- The server mints thread IDs as UUIDv4 when the request omits `thread_id`. Client-supplied IDs must be canonical UUIDs (`422 validation_error` otherwise).
- When persistence is enabled, a supplied `thread_id` must refer to an **existing** thread. New threads are only created by the server. This keeps "exists but not yours" and "doesn't exist" indistinguishable.
- A thread is bound to the `user_id_hash` that created it (`None` for anonymous threads). A request whose hashed `user_id` doesn't match gets the same `404 thread_not_found` as a missing thread.
- With `APP_CHECKPOINTER=none`, there is nothing to look up, so `thread_id` remains a correlation ID (backward compatible).
- `user_id` is **not authenticated** until v0.4.0. Before then, the guard prevents accidental cross-use, and the real protection is the unguessability of server-minted UUIDv4 thread IDs. This limitation is documented in `SECURITY.md`.

### 3. What is persisted, and the context window

- Thread history persists only the user turn (`HumanMessage`) and the final answer (`AIMessage`). The intermediate tool-call and tool-result messages produced inside `create_agent` aren't persisted. This avoids storing raw tool output and makes it impossible for history trimming to orphan a tool call from its result.
- A turn is committed atomically. `AgentService` passes the new user message in a per-run `user_message` state field, not in `messages`. The agent node appends both the `HumanMessage` and the final `AIMessage` to `messages` in a single update, only on success. A failed or cancelled run therefore never leaves a dangling user turn in history. Graph inputs that arrive with `messages` already populated (Agent Server, LangGraph Studio) are still supported.
- Per-run fields (`request_id`, `run_id`, `user_message`, `answer`, `error`) are overwritten on every turn and never read across turns.
- Context window: before each agent call, history is trimmed to a token budget (`langchain_core.messages.trim_messages`, keeping the newest turns, starting on a human message). Stored history is capped at `APP_MAX_THREAD_MESSAGES`, and older messages are removed from state with `RemoveMessage`.

Rejected for now: `SummarizationMiddleware`. It adds a second model call per long turn (cost, latency, a new failure mode), and it persists model-written summaries, which become an injection-persistence surface. It can be revisited when an eval shows that trimming loses needed context.

### 4. Streaming protocol

- Endpoint: `POST /v1/agent/stream`, taking the `AgentRequest` body and returning `text/event-stream` (SSE via `sse-starlette`). `/v1/agent/invoke` is unchanged.
- Engine: `graph.astream(stream_mode=["messages", "updates"])`. This is stable across LangGraph 1.x and captures tokens from the model call nested inside the `create_agent` loop. The v1.2 event-streaming API (`astream_events(version="v3")`) was rejected for now: it's newer, and its single-consumer projections add no value for one SSE consumer.
- Event schema (versioned, documented):

  | Event | Data |
  | --- | --- |
  | `run_started` | `request_id`, `thread_id`, `run_id` |
  | `token` | `text` (answer delta) |
  | `tool_call` | `name` only, never arguments |
  | `final` | the validated `AgentAnswer` payload (same fields as `AgentResponse`) |
  | `error` | `code`, `retryable`, following `AppError.user_visible` rules |
  | `done` | empty |

- Structured output: the model emits `AgentAnswer` as JSON. Token deltas are produced by incrementally parsing the partial JSON (`langchain_core.utils.json.parse_partial_json`) and emitting only the growth of the `answer` field. Plain-text model output is streamed as is. Tokens are a best-effort preview; the `final` event always carries the schema-validated answer and is authoritative.
- Errors before the first byte (validation, rate limit, body size, unknown thread) use normal HTTP status codes. Errors after the stream has started become a single `error` event followed by closing the stream.
- Responses set `Cache-Control: no-cache` and `X-Accel-Buffering: no`, and send periodic heartbeat comments.

Rejected: WebSockets (bidirectional is not needed, and they're harder to proxy and rate-limit); `GET` with query parameters (puts the prompt in URLs and access logs).

### 5. Concurrent runs on one thread

The double-texting strategy is **reject**. A second run on a thread with a run in flight gets `409 thread_busy`, and the first run is unaffected. The guard is process-local (an in-memory set of active thread IDs), so it doesn't coordinate across replicas. This is the same documented limitation as ADR 0004's rate limiter.

Rejected: enqueue, interrupt, and rollback (Agent Server's other multitask strategies). They need a run queue and cross-replica coordination, which ADR 0001 rules out without a requirement.

### 6. Cancellation and limits

- A client disconnect cancels the in-flight graph task, which stops provider and tool calls.
- Streamed runs are bounded by the same request timeout and recursion limit as `/invoke`.
- The number of concurrently open streams per process is capped (`503` beyond the cap).
- A cancelled or failed run leaves the thread's `messages` at the last completed turn (see the atomic turn commit in decision 3).

### 7. Conversation data at rest

- Checkpoints contain user prompts and model answers, so they're user data.
- `DELETE /v1/threads/{thread_id}` removes all checkpoints for a thread (`adelete_thread`).
- `APP_THREAD_RETENTION_DAYS` drives an idempotent prune job (`make prune-threads`) that operators schedule. `PostgresSaver` has no built-in TTL.
- Encryption at rest is delegated to the database or storage layer. LangGraph's `EncryptedSerializer` is a documented option, not enabled by default.

## Non-goals (v0.3.0)

- Long-term or cross-thread memory (LangGraph `Store`).
- Resumable or replayable streams.
- WebSockets.
- Multi-replica concurrency coordination.
- Authentication: v0.4.0.

## Consequences

- Local development gets working multi-turn conversations with no setup. `make test` stays dependency-free.
- Production gains durable conversations by configuring Postgres. Operators now own a database: setup, backups, retention, and capacity are documented in `OPERATIONS.md`.
- `langgraph-checkpoint-postgres` and `psycopg[binary,pool]` become runtime dependencies.
- The thread-busy guard and stream cap are per-process. Multi-replica deployments get correct persistence, but concurrent same-thread runs on different replicas aren't prevented.
- Streamed tokens may be cut short by an error. Clients must treat `final` as the authoritative answer.
