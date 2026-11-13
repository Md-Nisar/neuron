# Specifications: Functional Specifications and Business Rules

> **Document ID:** DOC-SPEC-001  
> **Diátaxis Mode:** Reference / Specification  
> **Standard Alignment:** Structured in alignment with ISO/IEC/IEEE 26514:2022 §7.1 (System & Functional Specifications) and Diátaxis (Specification)  
> **Product Version:** 1.2.0  
> **Status:** Production-Ready  
> **Code Traceability:** `src/neuron_agent/schemas/`, `src/neuron_agent/services/agent_service.py`, `src/neuron_agent/knowledge/`

---

## 1. System Limits and Quota Specifications

The following table summarizes all enforced functional boundaries, operational quotas, and resource constraints across the Neuron Agent platform:

| Functional Area | Parameter / Constraint | Configurable Setting | Default Value | Enforced Rule & Error Code |
| :--- | :--- | :--- | :--- | :--- |
| **HTTP Body** | Maximum incoming request body size | `APP_MAX_REQUEST_BODY_BYTES` | 65,536 bytes (64 KB) | Rejects oversized payloads with HTTP `413 payload_too_large`. Multipart uploads bypass this buffer. |
| **Prompt Length** | Maximum incoming user prompt length | `APP_MAX_PROMPT_CHARS` | 12,000 characters | Rejects prompts exceeding limit with HTTP `422 validation_error` (or `400 validation_error`). |
| **Agent Steps** | Maximum model iterations per turn | `APP_MAX_AGENT_ITERATIONS` | 8 iterations | Rejects runs exceeding step limit with HTTP `422 agent_step_limit_exceeded`. |
| **Turn Timeout** | Provider call timeout | `APP_REQUEST_TIMEOUT_SECONDS` | 60 seconds | Rejection with HTTP `504 provider_timeout_error` if an individual LLM call hangs. |
| **Run Timeout** | End-to-end agent run deadline | `APP_RUN_TIMEOUT_SECONDS` | 120 seconds | Halts run and returns HTTP `504 run_timeout` (or stream `error`). |
| **Tool Timeout** | Tool call execution bound | `APP_TOOL_TIMEOUT_SECONDS` | 20 seconds | Tool aborted with `502 tool_execution_error`. |
| **History Budget** | Active context window token budget | `APP_MAX_HISTORY_TOKENS` | 8,000 tokens | Oldest turns trimmed from LLM prompt using `trim_messages`. |
| **History Storage** | Persisted turns per thread | `APP_MAX_THREAD_MESSAGES` | 200 messages | Oldest whole turns evicted from PostgreSQL checkpoints via `RemoveMessage`. |
| **Thread Retention**| Inactive thread retention window | `APP_THREAD_RETENTION_DAYS` | 30 days | `prune-threads` CLI deletes checkpoints older than 30 days. |
| **Rate Limiter** | Request rate limit per window | `APP_RATE_LIMIT_REQUESTS_PER_WINDOW` | 60 requests / 60s | Exceeded limits return HTTP `429 rate_limited` with integer `Retry-After`. |
| **Rate Burst** | Token bucket burst capacity | `APP_RATE_LIMIT_BURST` | 20 tokens | Allows transient burst of up to 20 requests. |
| **Concurrent Runs**| Max parallel runs per user | `APP_MAX_CONCURRENT_RUNS_PER_USER` | 2 runs | Exceeded limits return HTTP `429 too_many_concurrent_runs`. |
| **Token Budget** | Rolling token allowance per user | `APP_USER_TOKEN_BUDGET` | 100,000 tokens | Exceeded budget returns HTTP `429 quota_exceeded` with `Retry-After`. |
| **Stream Cap** | Max concurrent SSE streams | `APP_MAX_CONCURRENT_STREAMS` | 100 per process | Rejection with HTTP `503 too_many_streams`. |
| **Memory Notes** | Max notes per user | `APP_MEMORY_MAX_ITEMS` | 50 notes | Rejection with HTTP `409 memory_full`. |
| **Memory Length**| Max characters per note | `APP_MEMORY_MAX_CHARS` | 500 characters | Rejection with HTTP `400 validation_error`. |
| **Export Cap** | Max export payload size | `APP_USER_DATA_EXPORT_MAX_BYTES` | 5,000,000 bytes (5 MB) | Exceeded pages return HTTP `413 export_too_large`. |
| **KB Quota** | Max knowledge bases per user | `APP_KNOWLEDGE_MAX_BASES_PER_USER` | 20 bases | Rejection with HTTP `409 knowledge_base_limit_reached`. |
| **KB Role Grants** | Max grants per knowledge base | `MAX_ROLE_GRANTS` | 50 grants | Rejection with HTTP `422 validation_error` if exceeded. |
| **Token Roles Limit**| Max roles extracted from claim | `APP_AUTH_ROLES_CLAIM` | 100 roles (max 256 chars/role)| Exceeding drops all roles and emits `auth_roles_dropped` audit event. |
| **File Parse Cap** | Max uploaded file size | `APP_KNOWLEDGE_PARSE_MAX_BYTES` | 50,000,000 bytes (50 MB) | Rejection with HTTP `413 file_too_large`. |
| **Page Parse Cap** | Max pages parsed per document | `APP_KNOWLEDGE_PARSE_MAX_PAGES` | 2,000 pages | Ingestion halted with `too_many_pages`. |
| **Char Parse Cap** | Max extracted characters per page | `APP_KNOWLEDGE_PARSE_MAX_PAGE_CHARS` | 50,000 characters | Ingestion halted with `page_too_long`. |
| **User Storage** | Max stored file bytes per user | `APP_KNOWLEDGE_MAX_BYTES_PER_USER` | 1,000,000,000 bytes (1 GB)| Upload rejected with HTTP `413 byte_quota_exceeded`. |
| **User Doc Cap** | Max documents per user | `APP_KNOWLEDGE_MAX_DOCUMENTS_PER_USER`| 1,000 documents | Upload rejected with HTTP `413 document_quota_exceeded`. |
| **User Page Cap** | Max parsed pages per user | `APP_KNOWLEDGE_MAX_PAGES_PER_USER` | 20,000 pages | Upload rejected with HTTP `413 page_quota_exceeded`. |
| **Active Ingestion**| Max in-flight ingesting documents | `APP_KNOWLEDGE_MAX_INGESTING_PER_USER`| 5 documents | Upload rejected with HTTP `429 ingestion_concurrency_exceeded`. |
| **Rerank Candidates**| Candidate pool sent to reranker | `src/neuron_agent/knowledge/retrieval.py` | 40 candidates | Fused top 40 candidates evaluated by cross-encoder. |
| **Rerank Timeout** | Per-request reranker deadline | `APP_KNOWLEDGE_RERANKER_TIMEOUT_SECONDS` | 3.0 seconds (0.5–30.0s) | On timeout, falls back to RRF order; `reranked: false`. |
| **Reindex Batch** | Retired embeddings purge batch size | `_RETIRED_BATCH` | 5,000 embeddings | Batched deletion per transaction to avoid lock contention. |

---

## 2. Core Functional Business Rules

### 2.1 Thread Resolution and Ownership
- A request omitting `thread_id` triggers the server-side generation of a fresh UUIDv4.
- If a `thread_id` is supplied, it must parse as a valid UUID string (`422 validation_error` otherwise).
- In JWT mode (`APP_AUTH_MODE=jwt`), the thread must exist and its stored checkpoint `owner` metadata must match the caller's computed HMAC owner key.
- Attempting to access an unknown thread or another user's thread returns identical `404 thread_not_found` responses to prevent tenant enumeration attacks.
- If a second request arrives for a thread while a run is in progress, the API immediately returns `409 thread_busy`.

### 2.2 Built-in Arithmetic Calculator
- The `calculator` tool parses expressions using Python's `ast.parse(expression, mode="eval")`.
- Allowed AST nodes: `ast.Constant` (numeric), `ast.BinOp` (`Add`, `Sub`, `Mult`, `Div`, `Mod`, `Pow`), `ast.UnaryOp` (`UAdd`, `USub`).
- Rejected: Any variable names, function calls, attribute lookups, list comprehensions, or control flow.
- Bounded Bounds: Expressions $>200$ characters, exponentiation exponents $>100$, or results exceeding $|10^{12}|$ are rejected as `ValidationAppError`.

### 2.3 Anti-Hallucination Memory Rule
- When the agent invokes `remember(text="...")`, the runtime verifies that the text appears verbatim within the user's explicit utterances in the active conversation thread (`HumanMessage`).
- If the model attempts to store a summary, deduction, or tool result, the tool execution is aborted with an error instructing the model to quote the user directly.

### 2.4 Cryptographic Citation Grounding
- Passages retrieved via `search_knowledge` receive an ephemeral, opaque `cite_id` minted by the server.
- The mapping between `cite_id` and document chunk UUIDs is held in tool message artifacts and is invisible to the prompt.
- The server validates the model's claimed citations in the final answer against the run's minting artifacts. Unverified citations are stripped, and `grounded` is computed strictly based on whether surviving valid citations exist.

### 2.5 Role-Based Knowledge Base Sharing (RAG-09.03)
- An owner can share a knowledge base with holders of specific verified JWT token roles (`APP_AUTH_ROLES_CLAIM`).
- Granted access levels:
  - `read`: List the base, search passages, receive citations, download original files.
  - `write`: In addition to `read`, upload documents and delete individual documents.
  - `admin`: In addition to `write`, rename the knowledge base and manage its role grants.
- Exclusivity of Ownership: Only the base's original creator (`subject_type = 'owner'`) may delete the knowledge base (`DELETE /v1/knowledge/bases/{kb_id}`), export its data, or execute bulk account erasure.
- Quota Attribution: Document uploads count against the uploader's user storage quotas, not the base owner's quota.
- Immediate Revocation: Authorization is evaluated dynamically via SQL in the same transaction as the operation; revoking a role takes effect instantaneously on the next request.

### 2.6 Hybrid Candidate Reranking and Fail-Safe Fallback (RAG-09.01)
- When `APP_KNOWLEDGE_RERANKER=nvidia` and `NVIDIA_API_KEY` is present, the top 40 fused candidates retrieved from dense vector and full-text search are reranked using a hosted cross-encoder model (`nvidia/llama-nemotron-rerank-vl-1b-v2`).
- Rerank results strictly enforce 1-to-1 matching: every candidate must be scored exactly once with finite values, or the output is treated as invalid.
- Fail-Safe Fallback: If the reranker times out (`APP_KNOWLEDGE_RERANKER_TIMEOUT_SECONDS`, default 3s), returns an HTTP error, or outputs malformed rankings, the system transparently preserves the original Reciprocal Rank Fusion (RRF) candidate order and returns `reranked: false`.

### 2.7 Multi-Profile Zero-Downtime Reindexing (RAG-09.04)
- Embedding model migrations are executed without service interruption using database-backed index profiles (`active`, `building`, `retired`).
- Migration constraints: At most one `active` and at most one `building` profile may exist simultaneously (enforced by unique partial indexes 28 and 29).
- Dual Embedding: While a re-index profile is `building`, all new uploads are automatically embedded using both the active and the building models, charging both embeddings to document token counts.
- Strict Locality Enforcement: A hosted re-index model is strictly refused if any live knowledge base has `processing = 'self_hosted'` or if `APP_KNOWLEDGE_PROCESSING_POLICY=self_hosted_only`.
- Atomic Swap: The building profile is promoted to `active` only when 100% of ready chunks across all live knowledge bases have been embedded with the target model. The swap executes within a single database transaction under a table-level share lock.

### 2.8 Negative Feedback Citation Extraction (RAG-09.07)
- The operator command `python -m neuron_agent.persistence.cli feedback-report` aggregates all thumbs-down answer ratings from `neuron_feedback`.
- For each negative rating, the command locates the corresponding conversation run, resolves its validated answer citations, and reports the affected chunk UUIDs and document UUIDs.
- Privacy Preservation: The report outputs identifiers, ratings, and timestamps only; it never extracts user queries, chunk texts, or conversational prompt contents.
