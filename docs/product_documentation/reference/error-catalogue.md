# Reference: Error Code Catalogue and Troubleshooting Reference

> **Document ID:** DOC-REF-005  
> **Diátaxis Mode:** Reference (Information-Oriented)  
> **Standard Alignment:** Structured in alignment with ISO/IEC/IEEE 26514:2022 §7.3 (Reference Information) and Diátaxis (Reference)  
> **Scope:** Machine-readable error codes and centralized HTTP mapping  
> **Code Traceability:** `src/neuron_agent/errors/base.py`, `src/neuron_agent/api/main.py`, `src/neuron_agent/knowledge/reranking.py`

---

## 1. Error Taxonomy Architecture

Neuron Agent implements a centralized, typed error taxonomy rooted in `AppError` (`src/neuron_agent/errors/base.py`). Every exception class defines a frozen `ErrorContext` specifying:
- `code`: Stable, machine-readable string code.
- `http_status`: Standard RFC 9110 HTTP status code.
- `retryable`: Boolean indicating whether the client or caller should retry.
- `user_visible`: Boolean. When `false`, the API layer sanitizes the response, returning a generic `internal_server_error` to prevent internal system and vendor detail leakage.
- `alert`: Boolean indicating whether the exception increments error counters and triggers immediate SRE alert notifications.

---

## 2. Complete Error Code Catalogue

| Error Code | HTTP Status | Retryable? | Client-Visible? | Alert? | Description & Cause | Operator / Client Action |
| :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `validation_error` | 400 / 422 | No | Yes | No | Input failed schema validation: HTTP 422 for FastAPI request body validation; HTTP 400 for domain-level business validation. | Check request JSON body and field constraints. |
| `authentication_error` | 401 | No | Yes | No | Missing, expired, malformed, or untrusted Bearer JWT token. | Refresh token via OIDC Identity Provider. |
| `authorization_error` | 403 | No | Yes | No | Caller token lacks the required scope for this endpoint. | Grant missing scope to user in Identity Provider. |
| `knowledge_access_denied` | 403 | No | Yes | No | Caller may see this knowledge base but is not permitted to modify it this way (lacks required role grant). | Verify assigned role grants via `GET /v1/knowledge/bases/{kb_id}/grants` or contact base owner. |
| `thread_not_found` | 404 | No | Yes | No | Thread ID does not exist or belongs to another user. | Verify thread ID; omit to start a new thread. |
| `approval_not_found` | 404 | No | Yes | No | No pending approval exists for this ID on this thread. | Thread was already decided or never paused. |
| `memory_disabled` | 404 | No | Yes | No | Memory subsystem is not enabled on this deployment. | Enable `APP_MEMORY_ENABLED=true` in settings. |
| `memory_not_found` | 404 | No | Yes | No | Note ID does not exist for the caller. | Verify note ID via `GET /v1/me/memories`. |
| `knowledge_disabled` | 404 | No | Yes | No | Knowledge Engine is not enabled on this deployment. | Enable `APP_KNOWLEDGE_ENABLED=true`. |
| `knowledge_base_not_found` | 404 | No | Yes | No | Knowledge base ID does not exist or was deleted. | Verify KB ID via `GET /v1/knowledge/bases`. |
| `knowledge_document_not_found` | 404 | No | Yes | No | Document ID does not exist or was deleted. | Verify doc ID via `GET /v1/knowledge/bases/{kb_id}/documents`. |
| `thread_busy` | 409 | Yes | Yes | No | Another run is currently in flight on this thread. | Retry request after waiting (backoff 500ms). |
| `approval_pending` | 409 | No | Yes | No | Thread is waiting for an approval decision; cannot accept messages. | Decide pending approval before sending new prompts. |
| `memory_full` | 409 | No | Yes | No | User has reached `APP_MEMORY_MAX_ITEMS` limit. | Delete unused notes before saving new ones. |
| `knowledge_base_limit_reached` | 409 | No | Yes | No | User has reached `APP_KNOWLEDGE_MAX_BASES_PER_USER` (20). | Delete old knowledge bases before creating new ones. |
| `idempotency_key_reused` | 409 | No | Yes | No | `Idempotency-Key` was previously used for a different base or file. | Mint a fresh unique UUID for the idempotency key. |
| `file_too_large` | 413 | No | Yes | No | Uploaded file exceeds `APP_KNOWLEDGE_PARSE_MAX_BYTES` (50 MB). | Compress or split the document. |
| `payload_too_large` | 413 | No | Yes | No | Request body exceeds `APP_MAX_REQUEST_BODY_BYTES` (64 KB). | Reduce prompt size. |
| `export_too_large` | 413 | No | Yes | No | Export response page exceeds `APP_USER_DATA_EXPORT_MAX_BYTES` (5 MB). | Paginate export using smaller `limit` / `message_limit`. |
| `byte_quota_exceeded` | 413 | No | Yes | No | User stored file bytes exceed `APP_KNOWLEDGE_MAX_BYTES_PER_USER` (1 GB). | Delete old documents. |
| `document_quota_exceeded` | 413 | No | Yes | No | User stored documents exceed quota (1,000). | Delete old documents. |
| `page_quota_exceeded` | 413 | No | Yes | No | User parsed pages exceed quota (20,000). | Delete old documents. |
| `unsupported_media_type` | 415 | No | Yes | No | Uploaded file format is not PDF, DOCX, XLSX, PPTX, TXT, or MD. | Convert file to supported document format. |
| `encrypted_pdf` | 415 | No | Yes | No | Uploaded PDF has password protection or DRM encryption. | Decrypt file before uploading. |
| `macro_refused` | 415 | No | Yes | No | Macro-enabled Office file (`.docm`, `.xlsm`) was refused. | Remove macros and save as standard `.docx`/`.xlsx`. |
| `archive_refused` | 415 | No | Yes | No | Non-Office ZIP archive file was uploaded. | Upload raw supported document files only. |
| `agent_step_limit_exceeded` | 422 | No | Yes | No | Agent reached `APP_MAX_AGENT_ITERATIONS` without completing. | Simplify prompt or raise iteration cap. |
| `rate_limited` | 429 | Yes | Yes | No | API request rate limit exceeded. | Back off; inspect `Retry-After` header. |
| `quota_exceeded` | 429 | Yes | Yes | No | Caller exceeded rolling provider token budget (`APP_USER_TOKEN_BUDGET`). | Back off; inspect `Retry-After` header. |
| `too_many_concurrent_runs` | 429 | Yes | Yes | No | Caller has exceeded `APP_MAX_CONCURRENT_RUNS_PER_USER` (2). | Wait for earlier active runs to complete. |
| `upload_busy` | 429 | Yes | Yes | No | Process upload concurrency cap reached (`APP_KNOWLEDGE_UPLOAD_CONCURRENCY`). | Retry after `Retry-After` header. |
| `download_busy` | 429 | Yes | Yes | No | Process download concurrency cap reached. | Retry after `Retry-After` header. |
| `ingestion_concurrency_exceeded` | 429 | Yes | Yes | No | User has $\ge 5$ documents currently ingesting. | Wait for active ingestion jobs to reach `ready`. |
| `configuration_error` | 500 | No | **No** | **Yes** | Server or provider misconfiguration (missing API key). | Inspect server startup logs and `.env` settings. |
| `agent_execution_error` | 500 | Yes | **No** | **Yes** | Unclassified exception during agent execution. | Inspect server error logs and stack traces. |
| `provider_error` | 502 | Yes | **No** | **Yes** | LLM provider returned an unexpected 5xx or bad response. | Verify provider status page (OpenAI / NVIDIA). |
| `tool_execution_error` | 502 | Yes | **No** | **Yes** | Local tool or remote MCP tool threw an unexpected error. | Inspect tool invocation logs. |
| `structured_output_error` | 502 | Yes | **No** | **Yes** | LLM failed to produce valid structured JSON matching schema. | Retried automatically; check model temperature/prompt. |
| `rerank_error` | 502 | Yes | **No** | **Yes** | Cross-encoder reranker failed, timed out, or produced invalid output. | Internal server error sanitized; search falls back to RRF candidate order with `reranked: false`. |
| `persistence_error` | 503 | Yes | **No** | **Yes** | PostgreSQL connection pool timeout or database connectivity loss. | Check PostgreSQL cluster health and connection counts. |
| `authentication_unavailable` | 503 | Yes | **No** | **Yes** | Identity Provider JWKS endpoint unreachable. | Check IdP connectivity and network firewall routes. |
| `too_many_streams` | 503 | Yes | Yes | No | Process reached `APP_MAX_CONCURRENT_STREAMS` (100). | Scale out API replicas. |
| `service_shutting_down` | 503 | Yes | Yes | No | Server is gracefully draining connections during shutdown. | Client should retry on another replica. |
| `provider_timeout_error` | 504 | Yes | Yes | No | Provider request exceeded `APP_REQUEST_TIMEOUT_SECONDS` (60s). | Retry with exponential backoff. |
| `run_timeout` | 504 | Yes | Yes | No | Total agent run exceeded `APP_RUN_TIMEOUT_SECONDS` (120s). | Break task into smaller sub-queries. |

---

## 3. Operational & Startup Diagnostics

| Diagnostic Code | Context | Description & Cause | Remediation Action |
| :--- | :--- | :--- | :--- |
| `knowledge_profile_mismatch` | Startup / Search | Configured embedding settings differ from the database's active index profile. | Set `APP_KNOWLEDGE_REINDEX_EMBEDDING_*` and run `reindex start` to migrate profiles. |
| `processing_locality_forbidden` | Ingestion / Re-index | Ingestion or re-index attempted hosted processing while policy or base requires `self_hosted`. | Verify `APP_KNOWLEDGE_PROCESSING_POLICY` or configure a self-hosted provider. |
| `reindex_failed` | Background Task | Background re-indexing worker task failed and exhausted retry budget. | Check worker logs; execute `reindex status` or `reindex cancel`. |
| `auth_roles_dropped` | Audit Event | Caller token carried $>100$ roles or a role name $>256$ characters. | Configure Identity Provider token role mapper to trim excess claims. |

---

## 4. Retry-After Header Behaviour

For retryable errors (HTTP 429 and temporary HTTP 503), Neuron supplies an RFC 9110 compliant `Retry-After: <seconds>` HTTP header:

| Error Code | HTTP Status | Retry-After Value | Behaviour & Rationale |
| :--- | :---: | :---: | :--- |
| `quota_exceeded` | 429 | Dynamic (integer) | Calculated from the remaining window seconds until the user's rolling token ledger recovers sufficient budget. |
| `too_many_concurrent_runs` | 429 | `1` | Fixed short retry; the client should poll after active turn finishes. |
| `upload_busy` | 429 | `1` | Fixed short retry; process upload slot released when concurrent upload completes. |
| `download_busy` | 429 | `1` | Fixed short retry; process download slot released when concurrent streaming download completes. |
| `ingestion_concurrency_exceeded`| 429 | `30` | Ingestion pipelines take several seconds to process; retry after 30s. |
| `service_shutting_down` | 503 | `1` | Fixed short retry; directs traffic away from gracefully draining pod. |
| `rate_limited` | 429 | Dynamic (integer) | Seconds required for token bucket to refill at configured fill rate. |
