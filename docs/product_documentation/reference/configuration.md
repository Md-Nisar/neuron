# Reference: Application Configuration Dictionary

> **Document ID:** DOC-REF-003  
> **Diátaxis Mode:** Reference (Information-Oriented)  
> **Standard Alignment:** Structured in alignment with ISO/IEC/IEEE 26514:2022 §7.3 (Reference Information) and Diátaxis (Reference)  
> **Scope:** All environment variables read by `src/neuron_agent/config/settings.py`  
> **Code Traceability:** `src/neuron_agent/config/settings.py`, `.env.example`

All configuration parameters are read from environment variables (or `.env` in development) with the `APP_` prefix, using Pydantic Settings.

---

## 1. Core Service & Network Settings

| Environment Variable | Type | Default | Staging/Prod Requirement | Description |
| :--- | :--- | :--- | :--- | :--- |
| `APP_ENV` | `development` \| `staging` \| `production` \| `test` | `development` | **Required** | Operational environment tier. Staging and production enforce strict security checks. |
| `APP_HOST` | string (IP or hostname) | `127.0.0.1` | Optional | HTTP listen bind address. Public binds (`0.0.0.0`) are rejected in dev unless `APP_ALLOW_UNAUTHENTICATED_PUBLIC_BIND=true`. |
| `PORT` / `APP_PORT` | integer (1–65535) | `8000` | Optional | HTTP listen port. `PORT` (set by Render/Heroku) takes precedence over `APP_PORT`. |
| `APP_NAME` | string | `neuron-agent` | Optional | Service identifier used in logs and default OTel service name. |
| `APP_LOG_LEVEL` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` | `INFO` | Optional | Root logging level for structlog JSON output. |
| `APP_ALLOWED_HOSTS` | JSON list of strings | `[]` | Recommended in Prod | Allowed HTTP `Host` headers. Empty list disables header check. |
| `APP_CORS_ALLOWED_ORIGINS` | JSON list of strings | `[]` | Required for Web | Allowed origins for browser CORS (exact match, including scheme and port). |
| `APP_HSTS_MAX_AGE_SECONDS` | integer ($\ge 0$) | `0` | **Required > 0 in Prod** | Strict-Transport-Security `max-age` seconds. Must be positive in production. |
| `APP_EXPOSE_API_DOCS` | boolean | `false` | **Must be `false` in Prod** | When `true`, exposes `/docs` (Swagger) and `/redoc`. Rejected at startup if enabled in production. |

---

## 2. Model & Provider Settings

| Environment Variable | Type | Default | Staging/Prod Requirement | Description |
| :--- | :--- | :--- | :--- | :--- |
| `APP_DEFAULT_MODEL` | string | `openai:gpt-5.4-mini` | **Required** | Model identifier in `provider:model-name` format. Supported providers: `openai`, `nvidia`, `anthropic`. |
| `APP_FALLBACK_MODELS` | JSON list of strings | `[]` | Optional (max 3) | Ordered list of backup models tried when the primary model fails retries. |
| `OPENAI_API_KEY` / `APP_OPENAI_API_KEY` | Secret string | `None` | Required for `openai` | API key for OpenAI model calls. |
| `NVIDIA_API_KEY` / `APP_NVIDIA_API_KEY` | Secret string | `None` | Required for `nvidia` | API key for NVIDIA API Catalog model calls. |
| `ANTHROPIC_API_KEY` / `APP_ANTHROPIC_API_KEY` | Secret string | `None` | Required for `anthropic` | API key for Anthropic model calls. |
| `APP_OPENAI_COMPATIBLE_BASE_URL` | URL | `None` | Required for `openai_compatible` | `/v1` base URL of a self-hosted OpenAI-compatible server (vLLM, SGLang). http(s), no credentials, query or fragment; https in production, and in staging when a key is set. A private address is allowed. |
| `APP_OPENAI_COMPATIBLE_API_KEY` | Secret string | `None` | Optional | Key for that server. Without one, no key is sent (never `OPENAI_API_KEY`). |
| `APP_REQUEST_TIMEOUT_SECONDS` | integer (1–300) | `60` | Optional | Timeout per individual HTTP request to model provider. |
| `APP_PROVIDER_MAX_RETRIES` | integer (0–5) | `2` | Optional | Max retry attempts for transient provider errors (connection, timeout, rate limit). |
| `APP_MAX_OUTPUT_TOKENS` | integer (1–16384) | `2000` | Optional | Max token completion budget passed to model provider. |
| `APP_MAX_PROMPT_CHARS` | integer (100–200000) | `12000` | Optional | Maximum allowed character length for incoming user prompt. |
| `APP_MAX_AGENT_ITERATIONS` | integer (1–25) | `8` | Optional | Maximum model invocation steps allowed in a single turn before step-limit error. |
| `APP_RUN_TIMEOUT_SECONDS` | integer (1–900) | `120` | Optional | Total deadline for an entire agent run across all retries, model calls, and tools. |

---

## 3. Security & Authentication Settings

| Environment Variable | Type | Default | Staging/Prod Requirement | Description |
| :--- | :--- | :--- | :--- | :--- |
| `APP_AUTH_MODE` | `none` \| `jwt` | `none` | **Must be `jwt` in Prod** | Authentication mode. `none` is strictly forbidden outside development/test. |
| `APP_AUTH_ISSUER` | string (URL) | `None` | Required in JWT mode | Expected `iss` claim in caller's JWT token. |
| `APP_AUTH_ISSUER_ID` | string (alphanumeric) | `default` | Optional | Short identifier used in audit log records to mask the full IdP URL. |
| `APP_AUTH_AUDIENCE` | string | `None` | Required in JWT mode | Expected `aud` claim in caller's JWT token. |
| `APP_AUTH_JWKS_URL` | string (HTTPS URL) | `None` | Required in JWT mode | Public JWKS endpoint URL for fetching signing keys. |
| `APP_AUTH_ALGORITHMS` | JSON list of strings | `["RS256", "ES256"]` | Optional | Allowed JWT signature verification algorithms. |
| `APP_IDENTITY_HASH_KEY` | Secret string ($\ge 32$ chars) | `None` | **Required in Prod** | Secret key for computing HMAC-SHA256 owner pseudonym identifiers. |
| `APP_AUTH_REQUIRE_TYP` | boolean | `false` | **Required `true` in Prod** | When `true`, requires explicit `typ: JWT` header in token. Enforced in production. |
| `APP_AUTH_ROLE_PERMISSIONS` | JSON map of string to list | `{}` | Optional | Maps IdP realm/client roles to Neuron's internal scopes. |
| `APP_AUTH_AUDIT_SUCCESS_ENABLED` | boolean | `false` | Optional | When `true`, emits audit log events for successful authentications. |

---

## 4. Rate Limiting, Concurrency & Budgets

| Environment Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `APP_LIMITS_BACKEND` | `auto` \| `memory` \| `postgres` | `auto` | Backend for rate limits and run leases. Must be `postgres` in production multi-instance. |
| `APP_RATE_LIMIT_ENABLED` | boolean | `true` | Enables token-bucket rate limiting on `/v1/*` endpoints. |
| `APP_RATE_LIMIT_REQUESTS_PER_WINDOW` | integer ($\ge 1$) | `60` | Sustained request rate per window. |
| `APP_RATE_LIMIT_WINDOW_SECONDS` | integer ($\ge 1$) | `60` | Duration of rate limiting window in seconds. |
| `APP_RATE_LIMIT_BURST` | integer ($\ge 1$) | `20` | Maximum token bucket burst capacity. |
| `APP_MAX_CONCURRENT_STREAMS` | integer ($\ge 1$) | `100` | Per-process concurrent SSE stream cap before returning `503 too_many_streams`. |
| `APP_MAX_CONCURRENT_RUNS_PER_USER` | integer ($\ge 1$) | `2` | Maximum concurrent active runs per owner before returning `429 too_many_concurrent_runs`. |
| `APP_USER_TOKEN_BUDGET` | integer ($\ge 1$) | `100000` | Rolling provider token allowance per user within budget window. |
| `APP_USER_TOKEN_BUDGET_WINDOW_SECONDS`| integer ($\ge 1$) | `3600` | Duration of user token budget window (default 1 hour). |

---

## 5. Persistence & PostgreSQL Settings

| Environment Variable | Type | Default | Staging/Prod Requirement | Description |
| :--- | :--- | :--- | :--- | :--- |
| `APP_CHECKPOINTER` | `auto` \| `memory` \| `postgres` \| `none` | `auto` | **Must be `postgres` in Prod** | Checkpointer backend. `auto` resolves to `memory` in dev. |
| `APP_POSTGRES_DSN` | Secret string | `None` | Required if postgres | Connection string for `neuron_app` runtime role (pooled). |
| `APP_POSTGRES_MIGRATION_DSN` | Secret string | `None` | Required for setup | Connection string for `neuron_migrator` role (direct/non-pooled). |
| `APP_POSTGRES_WORKER_DSN` | Secret string | `None` | Required for worker | Connection string for `neuron_worker` role. |
| `APP_POSTGRES_APP_ROLE` | string | `neuron_app` | Optional | Name of runtime application role granted DML rights. |
| `APP_POSTGRES_WORKER_ROLE` | string | `neuron_worker` | Optional | Name of ingestion worker role granted knowledge rights. |
| `APP_POSTGRES_POOL_MAX_SIZE` | integer (1–100) | `10` | Optional | Max connections in the async psycopg pool per process. |
| `APP_POSTGRES_POOL_TIMEOUT_SECONDS` | integer (1–120) | `10` | Optional | Max seconds to wait for an available pool connection. |
| `APP_THREAD_RETENTION_DAYS` | integer (1–3650) | `30` | Optional | Inactive thread age before deletion by `prune-threads`. |
| `APP_MAX_HISTORY_TOKENS` | integer (256–200000) | `8000` | Optional | Message history window budget sent to the LLM. |
| `APP_MAX_THREAD_MESSAGES` | integer (2–10000) | `200` | Optional | Maximum message turns persisted per thread before older turns are evicted. |

> [!IMPORTANT]
> **Persistence Validation Rules:**
> - In `APP_ENV=production`, `APP_POSTGRES_DSN` and `APP_POSTGRES_MIGRATION_DSN` must use different database users. Reusing the same role fails startup validation.
> - When `APP_KNOWLEDGE_ENABLED=true`, `APP_CHECKPOINTER=postgres` is mandatory (in-memory or none is rejected).

---

## 6. Knowledge Engine (RAG) Settings

| Environment Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `APP_KNOWLEDGE_ENABLED` | boolean | `false` | Enables knowledge bases, document ingestion, and RAG tools. |
| `APP_KNOWLEDGE_EMBEDDING_PROVIDER` | `nvidia` \| `openai_compatible` \| `fake` | `nvidia` | Embedding model provider. |
| `APP_KNOWLEDGE_EMBEDDING_MODEL` | string | `nvidia/nemotron-3.5-embed-1b` | Model identifier for generating embeddings. |
| `APP_KNOWLEDGE_EMBEDDING_DIMENSIONS` | integer (1–4000) | `1024` | Vector dimension size indexed in pgvector `halfvec`. |
| `APP_KNOWLEDGE_REINDEX_EMBEDDING_PROVIDER` | `nvidia` \| `openai_compatible` \| `fake` | `None` | The model a re-index builds a new index profile with (RAG-09.04). Set on the API and the worker for the whole re-index, then moved into the `APP_KNOWLEDGE_EMBEDDING_*` settings. Needs `_MODEL` and `_DIMENSIONS`. |
| `APP_KNOWLEDGE_REINDEX_EMBEDDING_MODEL` | string | `None` | The re-index model's identifier. |
| `APP_KNOWLEDGE_REINDEX_EMBEDDING_DIMENSIONS` | integer (1–4000) | `None` | The re-index model's vector dimensions. |
| `APP_KNOWLEDGE_REINDEX_EMBEDDING_BASE_URL`, `_API_KEY`, `_LOCALITY` | as the `APP_KNOWLEDGE_EMBEDDING_*` ones | `None`, `None`, `hosted` | The re-index model's server, key and locality, checked as for the active model. |
| `APP_KNOWLEDGE_SEARCH_MODE` | `hybrid` \| `dense` \| `fts` | `hybrid` | Search candidate retrieval mode. |
| `APP_KNOWLEDGE_PARSER_URL` | string (URL) | `None` | Endpoint of `docling-serve` container on internal network. |
| `APP_KNOWLEDGE_PARSER_TIMEOUT_SECONDS` | integer (10–7200) | `900` | Total parsing deadline per file sent to `docling-serve`. |
| `APP_KNOWLEDGE_PARSE_MAX_BYTES` | integer | `50000000` | Maximum uploaded document file size (50 MB). |
| `APP_KNOWLEDGE_PARSE_MAX_PAGES` | integer | `2000` | Maximum page count parsed from a single document. |
| `APP_KNOWLEDGE_PARSE_MAX_PAGE_CHARS` | integer | `50000` | Maximum extracted characters allowed per page. |
| `APP_KNOWLEDGE_BLOB_BACKEND` | `local` \| `s3` | `local` | Storage backend for original uploaded files. |
| `APP_KNOWLEDGE_BLOB_ROOT` | string | `var/knowledge-blobs` | Directory path when blob backend is `local`. |
| `APP_KNOWLEDGE_BLOB_BUCKET` | string | `None` | S3 bucket name when blob backend is `s3`. |
| `APP_WORKER_CONCURRENCY` | integer (1–32) | `2` | Number of concurrent ingestion tasks executed by worker. |

---

## 7. OpenTelemetry & Observability Settings

| Environment Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `APP_OTEL_ENABLED` | boolean | `false` | Enables OpenTelemetry tracing and metric instrumentation. |
| `APP_OTEL_SERVICE_NAME` | string | `None` | Service name resource attribute (defaults to `APP_NAME`). |
| `APP_OTEL_EXPORTER_OTLP_ENDPOINT` | string (URL) | `http://localhost:4318` | Base URL of OTLP/HTTP collector. |
| `APP_OTEL_TRACES_SAMPLE_RATIO` | float (0.0–1.0) | `1.0` | Head sampling probability ratio for new traces. |
| `APP_ENABLE_LANGSMITH` | boolean | `false` | Enables LangSmith agent execution tracing. |
| `LANGSMITH_API_KEY` | Secret string | `None` | API key for LangSmith tracing platform. |
| `APP_LANGSMITH_CONTENT_APPROVED` | boolean | `false` | When `false`, redacts all prompt and answer text from LangSmith traces. |
