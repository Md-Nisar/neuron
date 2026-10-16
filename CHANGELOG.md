# Changelog

## Unreleased

Fixes found by the first live eval runs:
- `used_tools` lists the tools that actually ran successfully in the request, not the model's own claim, which could omit tools or list the internal `AgentAnswer` output tool.
- An empty final answer from the model is a `502 structured_output_error`, not an unclassified internal error.
- A provider `404` (unknown model, or one the account can't use) is a non-retryable `configuration_error`, not a retryable `provider_error`.
- The eval runners score a case whose run fails as a failed case (`run failed: <error code>`) and continue, instead of aborting the whole suite.
- Request validation failures log only each error's `type` and `loc`; the rejected input (request text) is no longer logged.
- `retry_count` on `agent_execution_completed`/`agent_execution_failed` logs counts provider retries again; it was always `0` with the real agent, because the count was updated in a child context (found while adding #90's span attribute).
- The deterministic eval harness tests run in `make test` and CI again; since the NVIDIA provider change only the live quality evals (now also marked `integration`) are excluded by default.

v0.5.0 "Evaluation + Observability" (ADR 0007):
- OpenTelemetry foundation (#89). With `APP_OTEL_ENABLED=true`, the API exports traces and metrics over OTLP/HTTP (`OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS`) with head sampling (`APP_OTEL_TRACES_SAMPLE_RATIO`). HTTP spans are named by route template, `/health/*` is not traced, an incoming `traceparent` is honoured for its trace ID but not its sampled flag, so callers can't force or suppress tracing, and log lines carry `trace_id` and `span_id`. It is off by default, and no content is recorded.
- Agent tracing (#90): `invoke_agent neuron` per run (on Agent Server too), `chat {model}` per model call with token usage by kind and retry count, `execute_tool {tool}` per tool call with its outcome, and `neuron.stream` per SSE stream with time to first token, event count and termination. Failures carry the `AppError` code as `error.type`; no prompt, answer, tool argument or result, token or raw subject is recorded.
- Token accounting by kind and model (#91): each run's `model_token_usage` log splits `provider_tokens` into input, output, cache-read and reasoning tokens, in total and per model id. Budgets still charge the total. Estimated cost (the optional part of ADR 0007 section 4) is deferred to v0.6.0, since there is no verifiable, dated price data for the configured models.

## 0.4.0

"Secure Multi-User": verified identity, per-user isolation and limits (ADR 0006).

Breaking changes (README "Migrating from 0.3.x"):
- **Bearer tokens are required in staging and production.** `APP_AUTH_MODE=none` is rejected there; `jwt` mode needs `APP_AUTH_ISSUER`, `APP_AUTH_AUDIENCE`, an HTTPS `APP_AUTH_JWKS_URL` and `APP_IDENTITY_HASH_KEY`.
- **`user_id` and `X-User-Id` are ignored in jwt mode**; the verified `(iss, sub)` is the identity. They remain only for `APP_AUTH_MODE=none` local development.
- **0.3.x threads are not accessible in jwt mode**: ownership is an HMAC of the verified identity, and there is no fallback to the old hash (`OPERATIONS.md`).
- New `401 authentication_error`, `403 authorization_error`, `503 authentication_unavailable`, `429 quota_exceeded` and `429 too_many_concurrent_runs` responses.
- `/v1/*` responses are `Cache-Control: no-store` (streams were `no-cache`); API docs are hidden in staging and production by default.

Changes:
- ADR 0006 defines OAuth 2.0/OIDC JWT authentication, principal identity, authorization and the migration from 0.3 (#52).
- JWT bearer authentication on every `/v1/*` route: JWKS-backed signature checks, issuer/audience/time-claim validation, an asymmetric-algorithm allow-list, token size limits, throttled key refresh, fail-closed JWKS errors and RFC 6750 responses. Health endpoints stay public (#53).
- Threads are owned by a keyed HMAC of the verified issuer and subject (#54).
- Scope-based authorization (`agent:invoke`, `threads:read`, `threads:delete`, `tools:calculator`), with optional role-to-scope mapping; tool availability follows the caller's permissions (#55).
- Per-user limits: per-principal rate limits, concurrent-run caps and rolling token budgets (#56).
- Privacy-safe security audit events on a separate `neuron_agent.audit` logger (#57).
- LangGraph Agent Server deployments use the same verifier, owner keys and permissions (#58).
- User data rights: `GET /v1/me/threads`, `GET /v1/me/export` and `DELETE /v1/me/threads` (#59).
- Authentication documentation and local development tokens (#62):
  - `make dev-auth`, `make dev-jwks` and `make dev-token` (`scripts/dev_token.py`) mint tokens from a local key and serve its JWKS on loopback, with no identity provider. They refuse to run unless `APP_ENV=development`;
  - README authentication quickstart, bearer `curl`/JavaScript examples and "Migrating from 0.3.x"; `OPERATIONS.md` identity-provider setup, key rotation and JWKS caching, `APP_IDENTITY_HASH_KEY` rotation, and runbook entries for each new error code; `SECURITY.md` IdP trust assumptions and remaining limitations;
  - a test that keeps `.env.example` in step with `Settings`.
- `/v1/me/threads`, `/v1/me/export` and `DELETE /v1/me/threads` do work in proportion to the page they return, not the caller's whole checkpoint history (#76):
  - on Postgres, one paginated aggregate query lists the caller's threads, served by a new `neuron_checkpoints_owner_idx` index. Re-run `make db-setup` when upgrading;
  - messages are loaded only from the latest checkpoint of each returned thread;
  - export stops reading once `APP_USER_DATA_EXPORT_MAX_BYTES` is exceeded;
  - bulk erase loads no messages.
- HTTP surface hardening for browser and multi-user exposure (#60):
  - CORS through an explicit `APP_CORS_ALLOWED_ORIGINS` allow-list (empty by default; `*` and malformed origins are rejected at startup), with preflight support for `/v1/agent/stream`;
  - `/docs`, `/redoc` and `/openapi.json` are hidden in staging and production unless `APP_EXPOSE_API_DOCS=true`, and the schema declares the bearer scheme;
  - `nosniff`, `no-referrer` and a deny-all `Content-Security-Policy` on every response, `Cache-Control: no-store` on `/v1/*` (streams change from `no-cache`), and opt-in HSTS (`APP_HSTS_MAX_AGE_SECONDS`);
  - an `APP_ALLOWED_HOSTS` Host check that exempts `/health/*`;
  - unhandled errors become a JSON `500 internal_server_error` that keeps the CORS, correlation and security headers;
  - rate limits match routes without any `root_path` prefix, so `uvicorn --root-path` no longer bypasses them, and failed authentication on `/v1/me/*` now counts against the per-IP limit like the other `/v1` routes;
  - `413` and `429` responses now carry `X-Correlation-ID`, and their log events carry the `request_id`;
  - an empty `X-Correlation-ID` is now replaced with a UUID instead of being logged as an empty ID.
- Security tests and eval dataset v3 for multi-user isolation (#61):
  - shared JWT fixtures (local RSA and EC keys, an in-process JWKS, `make_token`);
  - an HTTP BOLA matrix over every `/v1/*` route, including token expiry mid-session, revoked permissions and parallel streams;
  - a token-attack suite;
  - 12 multi-user security eval cases;
  - a `pip-audit` dependency audit in `make security` and CI.
- PyJWT is upgraded to 2.15.1 (14 advisories against 2.13.0, including algorithm confusion and JWKS redirects) and urllib3 to 2.8.0. A token whose `alg` doesn't match its `kid`'s key now gets `401` instead of `500`: the verifier passes the `PyJWK` to `jwt.decode`, which binds verification to the key's algorithm. Tokens with an empty or non-string `iss`/`sub` are now audited as `auth_failed` (#61).
- A model provider account with no API credit (OpenAI `429 insufficient_quota`) is no longer retried or reported as a rate limit. It fails at once as `ProviderQuotaError` (`provider_quota_exhausted`, `503`, alerting) (#50).
- Release gate (#63). It found and fixed one defect present since #58: on Agent Server, the graph built each run's authorization from the run's client-supplied `context`. Runs without one crashed, so every Agent Server and Studio run failed, and a run whose `context` listed `permissions` got those permissions (a function-level authorization bypass for tools). Runs now take permissions and the owner only from the authenticated user Agent Server records; client `context` grants nothing.

Known issues (see `docs/releases/v0.4.0-release-verification.md`):
- The live OpenAI smoke tests and live evals have still not run (no usable API credentials, as in 0.3.0); model-facing behaviour is verified only with fake models.
- Agent Server (`langgraph.json`) deployments enforce authentication, scopes, tool permissions and owner isolation, but not the API's per-principal rate limits, run caps, token budgets or message input policy.
- A newly published IdP signing key can be rejected for up to 30 seconds (PyJWT's forced-refetch cooldown); pre-publish keys.
- `/health/ready` doesn't probe the JWKS, so an instance marked not ready after an IdP outage recovers only when it serves a request.

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

Known issue: the live OpenAI smoke tests and live evals could not complete, because the available API account had no credit (`429 insufficient_quota`). Deterministic suites, Postgres integration and real-server checks all pass; see `docs/releases/v0.3.0-release-verification.md`.

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
