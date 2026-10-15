# Operations

## Deployment

Two deployment paths are supported:

- LangGraph Agent Server/LangSmith using `langgraph.json`.
- Self-hosted container using `Dockerfile`.

Production deployments must inject secrets through the platform secret manager.

## Health Checks

- `/health/live`: process is serving requests.
- `/health/ready`: application configuration loaded; with `APP_CHECKPOINTER=postgres`, the database reachable; and in jwt mode, no JWKS fetch failure since the last signing key was obtained. Returns `503 {"status": "not_ready"}` otherwise, so take the instance out of rotation. The JWKS part is passive (see Signing keys and JWKS caching).

Health checks intentionally avoid LLM calls to prevent cost spikes and dependency coupling.

## Identity Provider

Staging and production require `APP_AUTH_MODE=jwt`: every `/v1/*` request carries an OAuth 2.0 access token that is a signed JWT (RFC 9068), issued by one OIDC-compliant identity provider (IdP). Neuron never issues tokens or stores users (ADR 0006).

### Connecting an IdP

1. **Register the API** as a resource (API, audience or resource server, depending on the IdP), with an identifier such as `neuron-api`. Access tokens must carry it in `aud`, be JWTs (not opaque tokens), be signed with RS256/384/512 or ES256/384/512 with a `kid` header, and contain all of `iss`, `aud`, `sub`, `exp`, `nbf` and `iat`; a token missing any of them is rejected (`auth_failed`, `reason="invalid_claims"`). Check that the IdP includes `nbf`, since some omit it by default. ID tokens carry the client ID in `aud`, so they are rejected.
2. **Define the scopes** `agent:invoke`, `threads:read`, `threads:delete` and `tools:calculator` (see README "Authentication"), and grant them to the client applications that need them. If the IdP models permissions as roles instead, map roles to scopes with `APP_AUTH_ROLES_CLAIM` and `APP_AUTH_ROLE_PERMISSIONS`; a role grants nothing unless it's mapped.
3. **Service accounts** use the client-credentials grant and the same scopes. There is no separate API-key path.
4. **Configure Neuron** from the IdP's discovery document (`<issuer>/.well-known/openid-configuration`): `issuer` becomes `APP_AUTH_ISSUER` (compared exactly, including any trailing slash) and `jwks_uri` becomes `APP_AUTH_JWKS_URL`.

```text
APP_AUTH_MODE=jwt
APP_AUTH_ISSUER=https://idp.example.com/
APP_AUTH_AUDIENCE=neuron-api
APP_AUTH_JWKS_URL=https://idp.example.com/.well-known/jwks.json
APP_AUTH_ISSUER_ID=primary
APP_IDENTITY_HASH_KEY=<at least 32 random characters, from the secret manager>
# Only if permissions arrive as roles:
APP_AUTH_ROLES_CLAIM=roles
APP_AUTH_ROLE_PERMISSIONS={"neuron-user":["agent:invoke","threads:read","threads:delete"]}
```

5. **Check it:** call `/v1/me/threads` with a token from the IdP; expect `200`. A `401` is audited as `auth_failed` with a `reason` (`wrong_issuer`, `wrong_audience`, `expired`, ...) that names the mismatch.

`.env.example` lists every other `APP_AUTH_*` setting with its bounds. One issuer per deployment is supported.

### Signing keys and JWKS caching

- Fetched keys are cached for `APP_AUTH_JWKS_CACHE_SECONDS` (default `300`) per process; each fetch times out after `APP_AUTH_JWKS_TIMEOUT_SECONDS`.
- A token with an unknown `kid` triggers a refetch, but not always at once. PyJWT forces a refetch at most once per 30 seconds after any successful fetch (including the first one and cache-expiry fetches), so a key published less than 30 seconds after a fetch is rejected (`401`, `auth_failed` with `reason="unknown_signing_key"`) until that window ends; the release gate measured 30.2 s with default settings. On top of that, when a refetch succeeds but still lacks the `kid`, further unknown-`kid` refetches wait one second per process, so forged `kid`s can't hammer a reachable IdP. While the IdP is unreachable there is no such cooldown: each request that needs a fetch tries one, serialized per process and bounded by `APP_AUTH_JWKS_TIMEOUT_SECONDS`.
- **Rotation:** publish the new key in the JWKS at least a minute before the IdP signs with it (covering the 30-second refetch window), and remove the old key only after every token it signed has expired (plus `APP_AUTH_LEEWAY_SECONDS`). Most IdPs pre-publish keys automatically. An IdP that starts signing with a key the moment it publishes it causes up to 30 seconds of `401`s per API process.
- **Compromised key:** remove it from the JWKS, then restart the API replicas; otherwise each process keeps trusting its cached copy for up to `APP_AUTH_JWKS_CACHE_SECONDS`.
- **IdP outage:** tokens whose key is still cached keep working until the cache expires. After that, requests fail closed with `503 authentication_unavailable`. `/health/ready` returns `503` from the first failed fetch until a later request obtains a signing key again, from a fetch or the cache. Readiness doesn't probe the JWKS itself, so an instance that receives no requests stays not ready: if the orchestrator removes not-ready instances from traffic, restart them after the IdP recovers, or base traffic decisions on `/health/live` plus your own IdP monitoring.

### Rotating `APP_IDENTITY_HASH_KEY`

Thread ownership is HMAC-SHA256(`APP_IDENTITY_HASH_KEY`, issuer + subject). Changing the key changes every owner key: every existing thread then returns `404` to its owner, `/v1/me/*` no longer finds it, and per-principal limits start fresh. There is no dual-key mode.

- Rotate only if the key is exposed. The key alone grants no access (a caller still needs a valid token), but with database access it lets someone link threads to known identities.
- To rotate, deploy the new key to every replica at once and let retention (`make prune-threads`) remove the orphaned threads, as in the v0.3 upgrade below. Tell users their earlier conversations are no longer available.
- Keep the key identical across replicas and restarts; a mismatch makes threads appear and disappear depending on the replica.

Related settings: trusted proxies and per-user limits are under Rate Limiting, audit log routing under Logs and Traces, and the HTTP surface (CORS, docs, headers, hosts) under HTTP Surface.

## Logs and Traces

Logs are JSON and include service metadata. Enable LangSmith tracing by setting:

```text
APP_ENABLE_LANGSMITH=true
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=neuron-agent-production
```

Do not log raw secrets, authorization headers, or sensitive user content.

### OpenTelemetry

The FastAPI server exports OpenTelemetry traces and metrics over OTLP/HTTP to a Collector
(ADR 0007). It is off by default, and nothing is exported until it is enabled:

```text
APP_OTEL_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=https://otel-collector.internal:4318
OTEL_EXPORTER_OTLP_HEADERS=authorization=Bearer%20<token>   # optional, URL-encoded
APP_OTEL_TRACES_SAMPLE_RATIO=1.0                             # head sampling for new traces
```

- **Resource:** `service.name` (`APP_OTEL_SERVICE_NAME`, default `APP_NAME`),
  `service.version` and `deployment.environment.name`.
- **Spans:** one HTTP server span per request, named by route template (for example
  `POST /v1/agent/invoke`). `/health/*` is not traced. An incoming W3C `traceparent` is
  honoured, including its sampled flag, so the sample ratio applies only to traces that
  start here. `X-Correlation-ID` stays the correlation ID and is recorded on the server
  span as `neuron.correlation_id`.
- **Logs:** every log line written inside a valid span context, sampled or not and audit
  records included, carries `trace_id` and `span_id`, so a log line leads to its trace.
- **Failures:** exports run in the background. An unreachable Collector never fails a
  request; the SDK logs `Failed to export ...` and drops the batch. Each export, retries
  included, gives up after `APP_OTEL_EXPORT_TIMEOUT_SECONDS`.
- **Transport:** in staging and production, an endpoint that carries
  `OTEL_EXPORTER_OTLP_HEADERS` must use HTTPS unless it is a loopback sidecar
  (`localhost`, `127.0.0.1`, `[::1]`), so credentials never cross the network in clear.
- **Privacy:** prompts, answers and tool content are never recorded. HTTP spans do carry
  standard request attributes, such as the URL, user agent and peer address; redact them
  in the Collector where your policy requires it.
- **Agent Server** deployments don't use this exporter yet.

Security audit records use the separate `neuron_agent.audit` logger (also present as the
JSON `logger` field). Route that logger to the SIEM independently from application logs;
do not apply application-log sampling or filtering that drops denials. Records use the
fixed schema in `ARCHITECTURE.md#observability`; authentication success records are off
unless `APP_AUTH_AUDIT_SUCCESS_ENABLED=true`. Configure `APP_AUTH_ISSUER_ID` as a stable,
non-secret alias (for example `primary`), not an issuer URL. Choose SIEM retention under
your security/compliance policy; keep it separate from `APP_THREAD_RETENTION_DAYS`, since
audit records contain metadata and are not deleted with conversation data. Protect audit
sink access and retention against unauthorized modification/deletion.

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
| `thread_prune_job_completed` | info | `count`, `retention_days` | the retention job finished |
| `threads_pruned` | audit | `count` | the retention run's security audit record |

Suggested alerts:
- **Time to first token:** sustained rise in p95 `ttft_ms`.
- **Failed streams:** `stream_completed` with `termination != completed` above a few percent of streams.
- **Disconnects:** a spike in `stream_cancelled`. This usually means client or proxy timeouts, so check proxy buffering and timeouts first.
- **Capacity:** any `stream_rejected` with `too_many_streams`, which means you're at capacity; scale out or raise `APP_MAX_CONCURRENT_STREAMS`.
- **Database:** any `checkpoint_operation_failed`, or a sustained `checkpoint_operation_slow` rate.
- **Retention:** `thread_prune_job_completed` missing for longer than the job's schedule interval.

### Security incident runbook

| Response | Meaning | Runbook entry |
| --- | --- | --- |
| `401 authentication_error` | missing, malformed, expired or untrusted token | 401 spike |
| `403 authorization_error` | valid token without the route's scope | 403 spike |
| `503 authentication_unavailable` | the IdP's JWKS can't be fetched | IdP outage |
| `429 quota_exceeded` | the principal's rolling token budget is spent | Quota exhaustion |
| `429 too_many_concurrent_runs` | the principal already has `APP_MAX_CONCURRENT_RUNS_PER_USER` runs | Quota exhaustion |
| `429 rate_limited` | request rate, or failed authentications per IP | Quota exhaustion |

- **401/authentication failure spike:** query `logger="neuron_agent.audit" AND event="auth_failed"`
  and group by `reason`, `issuer_id` and time. `jwks_unavailable` indicates identity-provider
  connectivity trouble; invalid-token reasons indicate caller credentials or abuse. Verify
  issuer/JWKS health and key rotation before changing auth policy. Never copy bearer tokens
  into tickets or logs.
- **403/authorization denial spike:** query `event="authorization_denied"`, group by
  `action` and `reason`, and check for repeated scope mismatch or thread-access attempts.
  Verify role-to-scope configuration; never broaden permissions as a diagnostic shortcut.
- **IdP outage or JWKS fetch failures (`503 authentication_unavailable`):** query
  `event="auth_failed" AND reason="jwks_unavailable"`; `/health/ready` also returns `503`.
  Check the IdP's status and that `APP_AUTH_JWKS_URL` is reachable from the API (DNS,
  egress rules, TLS). Don't switch to `APP_AUTH_MODE=none` or widen the issuer. Requests
  recover by themselves once a fetch succeeds; readiness recovers only when a request gets
  a key, so restart instances that were taken out of rotation (Signing keys and JWKS caching).
- **Signing-key problems:** a spike of `auth_failed` with `reason="unknown_signing_key"` after an
  IdP key rotation means tokens are signed with a key the JWKS doesn't (yet) publish; check
  the IdP's JWKS before Neuron.
- **Quota exhaustion (`429`):** query `event="limit_exceeded"` grouped by `reason` and `actor`.
  `token_budget` is `quota_exceeded`, the per-principal rolling budget; `concurrent_runs` is
  `too_many_concurrent_runs`; `request_rate` and `authentication_attempts` are
  `rate_limited`; `concurrent_streams` is the process-wide stream cap (`503 too_many_streams`).
  One `actor` dominating points at a single client looping or retrying without honouring
  `Retry-After`. Check legitimate
  workload and provider capacity before tuning limits; do not disable guards during an incident.

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
3. **Create or migrate the schema** once per deploy, before the new version serves traffic: `make db-setup` (`python -m neuron_agent.persistence.cli setup`). It's idempotent; it runs LangGraph's `AsyncPostgresSaver.setup()` migrations, then creates `neuron_checkpoints_owner_idx`, the index behind `/v1/me/*`. The index is built `CONCURRENTLY`, so running it against a live database doesn't block writes. Without the index, `/v1/me/*` still works but scans the `checkpoints` table.
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

## HTTP Surface

| Setting | Default | Meaning |
| --- | --- | --- |
| `APP_CORS_ALLOWED_ORIGINS` | `[]` (CORS off) | JSON list of exact browser origins, such as `["https://app.example.com"]`. Each must be a lowercase `scheme://host[:port]` with no path or trailing slash, because browsers send exactly that. `*` is rejected. |
| `APP_EXPOSE_API_DOCS` | `true` in development/test, `false` in staging/production | Serve `/docs`, `/redoc` and `/openapi.json`; otherwise they return `404`. The schema declares the bearer (`JWT`) scheme on every `/v1/*` route. |
| `APP_ALLOWED_HOSTS` | `[]` (any host) | JSON list of accepted lowercase hostnames, without scheme or port (the port is ignored when matching); `*.example.com` matches subdomains. Other hosts get `400 Invalid host header`. `/health/*` is exempt, since probes usually address the instance by IP. Set it in production for self-hosted deployments. |
| `APP_HSTS_MAX_AGE_SECONDS` | `0` (off) | Sends `Strict-Transport-Security: max-age=N`. Enable only when every client reaches the API over HTTPS. |

CORS allows `GET`, `POST` and `DELETE` with the `Authorization`, `Content-Type` and `X-Correlation-ID` request headers, and exposes `Retry-After` and `X-Correlation-ID` to scripts. Preflights are cached for 10 minutes. Credentialed (cookie) CORS is never enabled: browsers send the bearer token in `Authorization`.

Every response carries `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` and `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'`. `/v1/*` responses, including errors and streams, carry `Cache-Control: no-store`. Unhandled errors are answered as `500 {"detail": "internal_server_error"}` with the same headers. If the proxy adds security headers of its own, don't repeat these: nginx `add_header` appends rather than replaces, so clients would receive both copies. The stream's `X-Accel-Buffering: no` is consumed by nginx and is unaffected by these headers.

## Conversation Retention and Deletion

- **Schedule retention.** Run `make prune-threads` (`python -m neuron_agent.persistence.cli prune`) daily, for example from cron or a Kubernetes CronJob, using the same `APP_CHECKPOINTER` and `APP_POSTGRES_DSN` as the API.
  - It deletes threads whose last checkpoint is older than `APP_THREAD_RETENTION_DAYS` (default `30`); `--older-than-days N` overrides that.
  - It's idempotent and logs `thread_prune_job_completed` with a count and emits the `threads_pruned` audit record.
  - On Postgres it selects stale threads with one aggregate query over root-namespace checkpoints.
- **User deletion requests.** Handle them with `DELETE /v1/threads/{thread_id}` (`204`). It returns `409 thread_busy` while a run is in flight; retry after it finishes.
- **Backups.** Database backups keep deleted threads until the backups expire. Size backup retention against your data-retention policy.

### Upgrade from v0.3 identity to JWT ownership

v0.3 threads store an unkeyed SHA-256 owner derived from request-provided identity;
JWT mode uses a keyed HMAC of the verified `(iss, sub)`. These formats are
intentionally incompatible, and JWT mode will treat every legacy thread as
not-found. Do not add a dual-hash fallback.

The supported rollout preserves security and lets old threads expire:

1. Before enabling JWT mode, provision the issuer, audience, JWKS URL, and a
   stable `APP_IDENTITY_HASH_KEY` (at least 32 characters) as deployment
   secrets. Keep the key stable across all replicas and restarts.
2. Confirm `make prune-threads` runs at least daily against the same Postgres
   database and `APP_THREAD_RETENTION_DAYS` configuration as the API. Configure
   backup expiration to match the approved conversation retention policy.
3. Record the time of the last v0.3 write, then deploy with `APP_AUTH_MODE=jwt`.
   Legacy conversations are unavailable after the switch; clients start new
   threads. Do not promise old-thread access during the transition.
4. Continue scheduled pruning for one full `APP_THREAD_RETENTION_DAYS` window
   after the last legacy write. After that window, all legacy threads should
   have been pruned; verify the `thread_prune_job_completed` job logs and database state
   before considering the migration complete.

If customers require uninterrupted access, stop the rollout and design a
separately reviewed migration that can authenticate each legacy owner and map
it to a verified principal. Do not infer that mapping from user-controlled
values or rewrite checkpoint ownership in place without an auditable plan.

## Rate Limiting

`/v1/agent/*`, `/v1/threads/*` and `/v1/me/*` enforce token-bucket limits (`APP_RATE_LIMIT_ENABLED=true` by default). Authenticated requests are keyed by the verified principal's opaque owner HMAC; in local `AUTH_MODE=none`, and after failed JWT authentication, the key is the client IP. Defaults: burst capacity `APP_RATE_LIMIT_BURST=20`, refilling at `APP_RATE_LIMIT_REQUESTS_PER_WINDOW=60` per `APP_RATE_LIMIT_WINDOW_SECONDS=60`. Exceeding it returns `429 {"detail": "rate_limited"}` with `Retry-After`; health endpoints are exempt.

By default, `X-Forwarded-For` is ignored. Set `APP_TRUSTED_PROXIES` to a JSON list of trusted proxy IP addresses/CIDRs only when the app is reachable exclusively through those proxies. Configure Uvicorn's `--forwarded-allow-ips` to the same trusted hops; never use `*` on an internet-reachable deployment. The app uses forwarded addresses only when its immediate peer is in `APP_TRUSTED_PROXIES`, preventing clients from choosing their own IP bucket.

`APP_MAX_CONCURRENT_RUNS_PER_USER=2` caps active invoke and stream runs together per principal; the existing `APP_MAX_CONCURRENT_STREAMS=100` remains a per-process global stream cap. Exceeding the principal cap returns `429 too_many_concurrent_runs` and `Retry-After`.

Provider token usage from model `usage_metadata` is charged to a rolling per-principal window: `APP_USER_TOKEN_BUDGET=100000` tokens per `APP_USER_TOKEN_BUDGET_WINDOW_SECONDS=3600`. Admission is rejected before a run with `429 quota_exceeded` and `Retry-After` when the budget is exhausted. Usage is charged after successful, failed, or cancelled runs whenever the provider returns usage metadata. Each worker keeps independent in-memory counters; they reset on restart and are not coordinated across replicas. Multi-replica deployments must account for per-worker enforcement; a shared Redis/Postgres backend is intentionally out of scope. Tune all limits to provider quotas and workload sizes. Set `APP_RATE_LIMIT_ENABLED=false` only for controlled local diagnostics, not production.

## Timeouts and Retries

- `APP_REQUEST_TIMEOUT_SECONDS` (default 60s): per-attempt timeout on the model provider call (`ChatOpenAI(timeout=...)`).
- `APP_TOOL_TIMEOUT_SECONDS` (default 20s): per-call timeout on tool execution; exceeding it raises `ToolExecutionError` without leaking tool internals to the caller.
- `APP_PROVIDER_MAX_RETRIES` (default 2, i.e. 3 attempts total): retries for transient provider failures only (connection errors, provider timeouts, provider rate limits, 5xx), with exponential backoff and jitter. Non-transient failures (auth errors, malformed requests) are never retried.
- `APP_MAX_AGENT_ITERATIONS` (default 5): recursion budget for the agent's internal tool-call loop; exceeding it surfaces as `agent_execution_error`.

Raise provider timeouts/retries cautiously in production — higher values increase worst-case request latency and hold HTTP connections open longer under provider degradation.

## Common Failures

| Symptom | Cause | Response |
| --- | --- | --- |
| Missing provider key in staging/production | `Settings.require_provider_key_outside_tests` fails fast at startup | process does not start; set `OPENAI_API_KEY` (or `NVIDIA_API_KEY` for `nvidia:` models) |
| Missing provider key in development | expected | fake local chat model serves requests; no live calls made |
| `429 rate_limited` | client exceeded the token bucket | caller retries after `Retry-After` seconds |
| `400 validation_error` | too-long, empty, whitespace-only or control-character message | reject before any model/tool call |
| `422 validation_error` | malformed JSON, unknown fields, wrong field types | reject before any model/tool call |
| `413 payload_too_large` | request body exceeds `APP_MAX_REQUEST_BODY_BYTES` | reject before parsing |
| `504 provider_timeout_error` | model provider did not respond within `APP_REQUEST_TIMEOUT_SECONDS` | retried internally first; surfaces only after retries are exhausted |
| `502 tool_execution_error` | tool exceeded `APP_TOOL_TIMEOUT_SECONDS` or raised an unclassified exception | tool failure is isolated; it cannot crash the agent loop |
| `502 provider_error` / `structured_output_error` | upstream 5xx, or the model returned output that failed the `AgentAnswer` schema or was empty | internal detail is logged, not returned to the caller |
| `500 agent_execution_error` | agent loop exceeded `APP_MAX_AGENT_ITERATIONS`, or an unclassified internal failure | check server logs' `error_type`/`error_code` fields |
| `503` with log `error_code=provider_quota_exhausted` | the model provider account has no credit (OpenAI `429 insufficient_quota`) | add credit or raise the quota; never retried, alerts on every request until fixed |
| `500 configuration_error` | unsupported model provider, malformed `provider:model` identifier, provider auth failure, or a model the provider does not offer this account (`404`) | fix configuration; never retried |
| `409 thread_busy` | another run on the same thread is still in flight (same process), or `DELETE` during a run | client retries after the current run finishes; normal for double-submits |
| `404 thread_not_found` | unknown thread, a different `user_id`, or persistence is `none` / was pruned | client starts a new conversation (omit `thread_id`) |
| `503 too_many_streams` | the process is at `APP_MAX_CONCURRENT_STREAMS` | scale out or raise the cap; watch `stream_rejected` |
| `504 run_timeout` / stream `error` `run_timeout` | the whole run exceeded `APP_RUN_TIMEOUT_SECONDS` | check provider latency and tool loops; raise the budget only alongside proxy timeouts |
| `503 persistence_error`, readiness `503` | Postgres unreachable, pool timeout, or a failed checkpoint operation | check the database and pool saturation; the pool reconnects automatically once Postgres is back; thread history is intact (turns commit only on success) |
| Spike in `stream_cancelled` | clients or a proxy dropping connections | check proxy buffering and timeouts (above) and client network; runs are cancelled, so no cost leak |
| Stream delivers everything at once | a proxy is buffering the response | disable buffering (above) |
| LangSmith unavailable | tracing endpoint unreachable | core request handling continues unless tracing is made mandatory by deployment policy |
| `Failed to export span batch` / `metrics` in logs | OTLP Collector unreachable or rejecting the export | requests are unaffected; check `OTEL_EXPORTER_OTLP_ENDPOINT`, headers and Collector health |

Every row above maps to the `AppError` taxonomy in `ARCHITECTURE.md`'s Failure Handling section; use the logged `error_code`/`error_type`/`retry_count`/`duration_ms` fields (see `ARCHITECTURE.md`'s Observability section) to diagnose which layer failed.

## Production Configuration Expectations

Before deploying to `staging`/`production`:

- `OPENAI_API_KEY` (or `APP_OPENAI_API_KEY`) must be set via the platform secret manager — startup fails fast otherwise.
- Use an `openai:` model. `nvidia:` models (NVIDIA API catalog) are meant for development on the free tier; they work in any environment, but the free tier isn't intended for production traffic or user data.
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
