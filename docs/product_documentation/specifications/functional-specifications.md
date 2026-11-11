# Specifications: Functional Specifications and Business Rules

> **Document ID:** DOC-SPEC-001  
> **Diátaxis Mode:** Reference / Specification  
> **Standard Alignment:** Structured in alignment with ISO/IEC/IEEE 26514:2022 §7.1 (System & Functional Specifications) and Diátaxis (Specification)  
> **Product Version:** 1.1.0  
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
| **File Parse Cap** | Max uploaded file size | `APP_KNOWLEDGE_PARSE_MAX_BYTES` | 50,000,000 bytes (50 MB) | Rejection with HTTP `413 file_too_large`. |
| **Page Parse Cap** | Max pages parsed per document | `APP_KNOWLEDGE_PARSE_MAX_PAGES` | 2,000 pages | Ingestion halted with `too_many_pages`. |
| **Char Parse Cap** | Max extracted characters per page | `APP_KNOWLEDGE_PARSE_MAX_PAGE_CHARS` | 50,000 characters | Ingestion halted with `page_too_long`. |
| **User Storage** | Max stored file bytes per user | `APP_KNOWLEDGE_MAX_BYTES_PER_USER` | 1,000,000,000 bytes (1 GB)| Upload rejected with HTTP `413 byte_quota_exceeded`. |
| **User Doc Cap** | Max documents per user | `APP_KNOWLEDGE_MAX_DOCUMENTS_PER_USER`| 1,000 documents | Upload rejected with HTTP `413 document_quota_exceeded`. |
| **User Page Cap** | Max parsed pages per user | `APP_KNOWLEDGE_MAX_PAGES_PER_USER` | 20,000 pages | Upload rejected with HTTP `413 page_quota_exceeded`. |
| **Active Ingestion**| Max in-flight ingesting documents | `APP_KNOWLEDGE_MAX_INGESTING_PER_USER`| 5 documents | Upload rejected with HTTP `429 ingestion_concurrency_exceeded`. |

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
