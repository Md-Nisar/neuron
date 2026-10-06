# Operations

## Deployment

Two deployment paths are supported:

- LangGraph Agent Server/LangSmith using `langgraph.json`.
- Self-hosted container using `Dockerfile`.

Production deployments must inject secrets through the platform secret manager.

## Health Checks

- `/health/live`: process is serving requests.
- `/health/ready`: application configuration loaded and, with `APP_CHECKPOINTER=postgres`, the database reachable. Returns `503 {"status": "not_ready"}` otherwise, so take the instance out of rotation.

Health checks intentionally avoid LLM calls to prevent cost spikes and dependency coupling.

## Logs and Traces

Logs are JSON and include service metadata. Enable LangSmith tracing by setting:

```text
APP_ENABLE_LANGSMITH=true
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=neuron-agent-production
```

Do not log raw secrets, authorization headers, or sensitive user content.

### Streaming and conversation-state events

Every event carries `request_id`, `thread_id` and `run_id`. None of them contains prompt text, streamed tokens or tool arguments.

| Event | Level | Key fields | Meaning |
| --- | --- | --- | --- |
| `stream_started` | info | — | a `/v1/agent/stream` run began |
| `stream_completed` | info / warning | `termination` (`completed`, `error`, `timeout`, `shutdown`), `error_code`, `ttft_ms`, `duration_ms`, `tokens_streamed`, `events_streamed` | the stream reached `done`; warning unless `completed` |
| `stream_cancelled` | info | `termination=client_disconnect`, plus the same timing and count fields | the client went away before `done`; the run was cancelled |
| `stream_rejected` | warning | `termination` (the error code, e.g. `thread_busy`, `too_many_streams`, `thread_not_found`) | the stream was refused before the first byte |
| `agent_execution_started` | info | `turn`, `history_messages`, `model` | `turn` is the 1-based user-turn number in the thread |
| `history_trimmed` | info | `messages_total`, `messages_sent`, `max_history_tokens` | older turns were left out of the model input |
| `checkpoint_operation_slow` | warning | `operation`, `backend`, `duration_ms` | a checkpointer read or write took at least 250 ms |
| `checkpoint_operation_failed` | warning | `operation`, `backend`, `error_type`, `duration_ms` | a checkpointer read or write raised |
| `checkpointer_unreachable` | warning | `backend`, `error_type` | readiness probe failed |
| `threads_pruned` | info | `count`, `retention_days` | the retention job finished |

Suggested alerts:
- **Time to first token:** sustained rise in p95 `ttft_ms`.
- **Failed streams:** `stream_completed` with `termination != completed` above a few percent of streams.
- **Disconnects:** a spike in `stream_cancelled`. This usually means client or proxy timeouts, so check proxy buffering and timeouts first.
- **Capacity:** any `stream_rejected` with `too_many_streams`, which means you're at capacity; scale out or raise `APP_MAX_CONCURRENT_STREAMS`.
- **Database:** any `checkpoint_operation_failed`, or a sustained `checkpoint_operation_slow` rate.
- **Retention:** `threads_pruned` missing for longer than the job's schedule interval.

## Scaling

The API can scale horizontally. Durable conversations require Agent Server managed persistence or `APP_CHECKPOINTER=postgres`. With Postgres, any replica can continue any thread.

Two guards are per process (ADR 0005), like the rate limiter:
- the `thread_busy` check, which rejects a concurrent run on the same thread;
- `APP_MAX_CONCURRENT_STREAMS`.

Two simultaneous requests for the same thread that land on *different* replicas aren't rejected. Both run and both commit their turns. If that matters for your clients, route by `thread_id` (sticky sessions) or serialize sends client-side, which UIs normally do anyway.

## Thread Persistence (Postgres)

1. **Provision Postgres** 14 or newer; 16 is tested. Give the application a role that owns its schema.
2. **Configure** through the secret manager:

   ```text
   APP_CHECKPOINTER=postgres
   APP_POSTGRES_DSN=postgresql://neuron:<password>@<host>:5432/neuron?sslmode=require
   ```

   The DSN is a `SecretStr` and is never logged.
3. **Create or migrate the schema** once per deploy, before the new version serves traffic: `make db-setup` (`python -m neuron_agent.persistence.cli setup`). It's idempotent; it runs LangGraph's `AsyncPostgresSaver.setup()` migrations.
   - `APP_CHECKPOINTER_SETUP_ON_STARTUP=true` does the same at app startup. That's convenient for local use (and `docker compose`), but avoid it with many replicas starting at once.
4. **Size the pool.** `APP_POSTGRES_POOL_MAX_SIZE` (default `10`) is per process. Each run holds a connection only briefly per checkpoint read or write, so a pool of 10 serves far more than 10 concurrent runs. Keep `replicas × workers × pool size` under the database's `max_connections`, leaving headroom for the prune job and admin access. `APP_POSTGRES_POOL_TIMEOUT_SECONDS` (default `10`) bounds the wait for a connection; exceeding it surfaces as `503 persistence_error`.
5. **Back up** like any user-data store, with retention aligned to `APP_THREAD_RETENTION_DAYS` (see below). Restoring a backup restores conversations, including ones deleted after it was taken.
6. **Watch** `checkpoint_operation_slow`, `checkpoint_operation_failed` and `checkpointer_unreachable` (see Logs and Traces).

Local Postgres for development: `docker compose up` starts the API and Postgres 16 with persistence enabled and the schema created on startup. Integration tests use any reachable database: `APP_TEST_POSTGRES_DSN=postgresql://... make test-integration`.

**Agent Server deployments** don't use any of this: Agent Server provides its own persistence for the `langgraph.json` graph.

## Streaming Behind a Reverse Proxy

`/v1/agent/stream` is a long-lived `text/event-stream` response. Proxies must not buffer or time it out:

- **Disable response buffering.** The API sends `X-Accel-Buffering: no`, which nginx honours. Elsewhere, set `proxy_buffering off;` or the equivalent for that proxy.
- **Raise idle and read timeouts** above `APP_STREAM_HEARTBEAT_SECONDS` (default `15`); heartbeats keep idle streams alive. Also allow at least `APP_RUN_TIMEOUT_SECONDS` (default `120`) for the whole response.
- **Don't compress `text/event-stream`.** Compression buffers output.
- **Use HTTP/1.1 or newer** to the upstream, with keep-alive.

```nginx
location /v1/agent/stream {
    proxy_pass http://neuron_api;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_buffering off;
    proxy_read_timeout 180s;
    gzip off;
}
```

Clients that disconnect stop their run: model and tool calls are cancelled. A client that stops reading for 30 s is disconnected. On shutdown, open streams receive `error {"code": "service_shutting_down", "retryable": true}` within 2 s, then `done`.

## Conversation Retention and Deletion

- **Schedule retention.** Run `make prune-threads` (`python -m neuron_agent.persistence.cli prune`) daily, for example from cron or a Kubernetes CronJob, using the same `APP_CHECKPOINTER` and `APP_POSTGRES_DSN` as the API.
  - It deletes threads whose last checkpoint is older than `APP_THREAD_RETENTION_DAYS` (default `30`); `--older-than-days N` overrides that.
  - It's idempotent and logs `threads_pruned` with a count.
  - On Postgres it selects stale threads with one aggregate query over root-namespace checkpoints.
- **User deletion requests.** Handle them with `DELETE /v1/threads/{thread_id}` (`204`). It returns `409 thread_busy` while a run is in flight; retry after it finishes.
- **Backups.** Database backups keep deleted threads until the backups expire. Size backup retention against your data-retention policy.

## Rate Limiting

`/v1/agent/*` and `/v1/threads/*` enforce a token-bucket rate limit per client IP (`APP_RATE_LIMIT_ENABLED=true` by default). Defaults: burst capacity `APP_RATE_LIMIT_BURST=20`, refilling at `APP_RATE_LIMIT_REQUESTS_PER_WINDOW=60` per `APP_RATE_LIMIT_WINDOW_SECONDS=60`. Exceeding it returns `429 {"detail": "rate_limited"}` with a `Retry-After` header; health endpoints are exempt. The limiter is in-process: it resets on restart and does not coordinate across replicas, so each instance behind a load balancer enforces its own limit independently (see ADR 0004). Tune the window/burst/rate settings per deployment traffic profile, or set `APP_RATE_LIMIT_ENABLED=false` to disable it (not recommended in production).

## Timeouts and Retries

- `APP_REQUEST_TIMEOUT_SECONDS` (default 60s): per-attempt timeout on the model provider call (`ChatOpenAI(timeout=...)`).
- `APP_TOOL_TIMEOUT_SECONDS` (default 20s): per-call timeout on tool execution; exceeding it raises `ToolExecutionError` without leaking tool internals to the caller.
- `APP_PROVIDER_MAX_RETRIES` (default 2, i.e. 3 attempts total): retries for transient provider failures only (connection errors, provider timeouts, provider rate limits, 5xx), with exponential backoff and jitter. Non-transient failures (auth errors, malformed requests) are never retried.
- `APP_MAX_AGENT_ITERATIONS` (default 5): recursion budget for the agent's internal tool-call loop; exceeding it surfaces as `agent_execution_error`.

Raise provider timeouts/retries cautiously in production — higher values increase worst-case request latency and hold HTTP connections open longer under provider degradation.

## Common Failures

| Symptom | Cause | Response |
| --- | --- | --- |
| Missing provider key in staging/production | `Settings.require_provider_key_outside_tests` fails fast at startup | process does not start; set `OPENAI_API_KEY` |
| Missing provider key in development | expected | fake local chat model serves requests; no live calls made |
| `429 rate_limited` | client exceeded the token bucket | caller retries after `Retry-After` seconds |
| `400 validation_error` | malformed JSON, unknown fields, oversized/empty/control-character message | reject before any model/tool call |
| `413 payload_too_large` | request body exceeds `APP_MAX_REQUEST_BODY_BYTES` | reject before parsing |
| `504 provider_timeout_error` | model provider did not respond within `APP_REQUEST_TIMEOUT_SECONDS` | retried internally first; surfaces only after retries are exhausted |
| `502 tool_execution_error` | tool exceeded `APP_TOOL_TIMEOUT_SECONDS` or raised an unclassified exception | tool failure is isolated; it cannot crash the agent loop |
| `502 provider_error` / `structured_output_error` | upstream 5xx, or the model returned output that failed the `AgentAnswer` schema | internal detail is logged, not returned to the caller |
| `500 agent_execution_error` | agent loop exceeded `APP_MAX_AGENT_ITERATIONS`, or an unclassified internal failure | check server logs' `error_type`/`error_code` fields |
| `500 configuration_error` | unsupported model provider, malformed `provider:model` identifier, or provider auth failure | fix configuration; never retried |
| `409 thread_busy` | another run on the same thread is still in flight (same process), or `DELETE` during a run | client retries after the current run finishes; normal for double-submits |
| `404 thread_not_found` | unknown thread, a different `user_id`, or persistence is `none` / was pruned | client starts a new conversation (omit `thread_id`) |
| `503 too_many_streams` | the process is at `APP_MAX_CONCURRENT_STREAMS` | scale out or raise the cap; watch `stream_rejected` |
| `504 run_timeout` / stream `error` `run_timeout` | the whole run exceeded `APP_RUN_TIMEOUT_SECONDS` | check provider latency and tool loops; raise the budget only alongside proxy timeouts |
| `503 persistence_error`, readiness `503` | Postgres unreachable, pool timeout, or a failed checkpoint operation | check the database and pool saturation; the pool reconnects automatically once Postgres is back; thread history is intact (turns commit only on success) |
| Spike in `stream_cancelled` | clients or a proxy dropping connections | check proxy buffering and timeouts (above) and client network; runs are cancelled, so no cost leak |
| Stream delivers everything at once | a proxy is buffering the response | disable buffering (above) |
| LangSmith unavailable | tracing endpoint unreachable | core request handling continues unless tracing is made mandatory by deployment policy |

Every row above maps to the `AppError` taxonomy in `ARCHITECTURE.md`'s Failure Handling section; use the logged `error_code`/`error_type`/`retry_count`/`duration_ms` fields (see `ARCHITECTURE.md`'s Observability section) to diagnose which layer failed.

## Production Configuration Expectations

Before deploying to `staging`/`production`:

- `OPENAI_API_KEY` (or `APP_OPENAI_API_KEY`) must be set via the platform secret manager — startup fails fast otherwise.
- `APP_ENV=production` (or `staging`).
- Leave `APP_RATE_LIMIT_ENABLED=true` and size `APP_RATE_LIMIT_*` for expected traffic; remember limits are per-instance, not cluster-wide.
- Set `APP_LOG_LEVEL=INFO` (or stricter) — logs never include raw secrets or prompts regardless of level (see `SECURITY.md`).
- Review `APP_REQUEST_TIMEOUT_SECONDS`, `APP_TOOL_TIMEOUT_SECONDS`, and `APP_PROVIDER_MAX_RETRIES` against the deployment's latency SLOs; defaults are development-oriented starting points, not production guarantees.
- Enable LangSmith tracing (above) only if the project/API key are production-scoped; do not point a production deployment at a development LangSmith project.
- **Set `APP_CHECKPOINTER` explicitly.**
  - `postgres` for durable conversations, with the steps above completed. `memory` is rejected in staging and production.
  - `none` for a deliberately stateless deployment; `auto` resolves to `none` there.
- **Schedule `make prune-threads`** and align `APP_THREAD_RETENTION_DAYS` with your data-retention policy.
- **Size the run guards.** Set `APP_RUN_TIMEOUT_SECONDS` and `APP_MAX_CONCURRENT_STREAMS` per instance, consistent with proxy timeouts and capacity.

## Rollback

Rollback by redeploying the previous container image or reverting the LangSmith deployment to the previous repository revision. Before removing graph nodes or state fields, verify no active threads depend on them.
