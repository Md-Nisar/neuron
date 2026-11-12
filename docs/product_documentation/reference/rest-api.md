# Reference: REST API Specification

> **Document ID:** DOC-REF-001  
> **Diátaxis Mode:** Reference (Information-Oriented)  
> **Standard Alignment:** Structured in alignment with ISO/IEC/IEEE 26514:2022 §7.3 (Reference Information) and Diátaxis (Reference)  
> **API Version:** v1 (`/v1/*`)  
> **Endpoint Count:** 29 distinct operations  
> **Base URL:** `http://127.0.0.1:8000` (Local) / `https://<domain>` (Production)  
> **Content-Type:** `application/json` (unless multipart specified)  
> **Code Traceability:** `src/neuron_agent/api/main.py`, `src/neuron_agent/schemas/`

---

## 1. Global HTTP Conventions

### 1.1 Authentication & Authorization
All endpoints under `/v1/*` require a Bearer token in the `Authorization` header when `APP_AUTH_MODE=jwt`:
```http
Authorization: Bearer <JWT_ACCESS_TOKEN>
```
Missing or invalid tokens return `401 Unauthorized`. Insufficient scopes return `403 Forbidden`.

### 1.2 Correlation & Tracing Headers
Every response includes:
- `X-Correlation-ID`: Server-minted or client-supplied correlation UUID for distributed trace correlation.
- `Cache-Control: no-store`: Caching is disabled across all authenticated endpoints.

### 1.3 Error Response Format
All error responses adhere to a uniform, non-leaking JSON structure:
```json
{
  "detail": "<error_code>"
}
```
Client-visible error codes are listed in the [Error Catalogue](error-catalogue.md).

> [!NOTE]
> **Validation Error HTTP Status Codes:**
> - HTTP `422 Unprocessable Entity` with `{"detail": "validation_error"}` is returned for low-level Pydantic request schema validation failures (malformed JSON, wrong data types, missing required fields).
> - HTTP `400 Bad Request` with `{"detail": "validation_error"}` is returned for domain-level business validation violations (e.g. invalid UUID formats, illegal parameter combinations).

### 1.4 Rate Limiting & Retry Headers
Responses returning `429 Too Many Requests` or temporary capacity `503 Service Unavailable` include a standard `Retry-After: <seconds>` HTTP header:
- **Token Budget Exceeded (`429 quota_exceeded`):** Dynamic integer calculated from the remaining window seconds until sufficient token budget recovers.
- **Worker / Resource Concurrency Limits (`429 upload_busy`, `429 download_busy`, `429 concurrent_runs_exceeded`):** Fixed `Retry-After: 1`.
- **Knowledge Ingestion Concurrency (`429 ingestion_concurrency_exceeded`):** Fixed `Retry-After: 30`.
- **Server Shutdown in Progress (`503 shutting_down`):** Fixed `Retry-After: 1`.
- **Token Bucket Rate Limiter (`429 rate_limited`):** Dynamic integer specifying wait duration until the bucket allows next request.

---

## 2. Health & System Endpoints

### 2.1 Liveness Probe
`GET /health/live`  
- **Authentication:** None.  
- **Description:** Verifies that the FastAPI process is responsive.  
- **Response:** `200 OK`
  ```json
  {"status": "ok"}
  ```

### 2.2 Readiness Probe
`GET /health/ready`  
- **Authentication:** None.  
- **Description:** Verifies that the PostgreSQL connection pool is open and the JWKS cache is primed.  
- **Response:** `200 OK`
  ```json
  {"status": "ready"}
  ```
- **Error:** `503 Service Unavailable`
  ```json
  {"status": "not_ready"}
  ```

---

## 3. Agent Invocation & Streaming Endpoints

### 3.1 Invoke Agent (Single Turn)
`POST /v1/agent/invoke`  
- **Scope Required:** `agent:invoke`  
- **Description:** Submits a user message to the agent graph. Runs synchronously to completion.  
- **Request Body (`AgentRequest`):**
  ```json
  {
    "message": "What is 19 * 3?",
    "thread_id": "019318b2-5f6e-7b3c-8a12-abcdef123456",
    "knowledge_base_ids": ["8f3b2e1a-4c5d-6e7f-8a9b-0c1d2e3f4a5b"]
  }
  ```
  - `message` (string, required): 1 to 12,000 characters.
  - `thread_id` (string UUID, optional): Omit to start a new conversation.
  - `knowledge_base_ids` (array of UUIDs, optional): 1 to 10 IDs to restrict knowledge search.
- **Successful Response (`200 OK`, `AgentResponse`):**
  ```json
  {
    "status": "completed",
    "request_id": "req-123",
    "thread_id": "019318b2-5f6e-7b3c-8a12-abcdef123456",
    "run_id": "run-456",
    "answer": "19 * 3 is 57.",
    "used_tools": ["calculator"],
    "confidence": 1.0,
    "refused": false,
    "clarification_needed": false,
    "citations": null,
    "citation_schema_version": null,
    "grounded": null
  }
  ```
- **Paused for Approval Response (`200 OK`, `ApprovalRequiredResponse`):**
  ```json
  {
    "status": "approval_required",
    "request_id": "req-123",
    "thread_id": "019318b2-5f6e-7b3c-8a12-abcdef123456",
    "approval": {
      "approval_id": "appr-789",
      "actions": [{"name": "create_ticket", "args": {"title": "Outage"}}],
      "allowed_decisions": ["approve", "reject"]
    }
  }
  ```
- **Errors:** `400 validation_error`, `404 thread_not_found`, `409 thread_busy`, `409 approval_pending`, `413 payload_too_large`, `429 rate_limited`, `429 quota_exceeded`, `504 run_timeout`.

---

### 3.2 Stream Agent (Server-Sent Events)
`POST /v1/agent/stream`  
- **Scope Required:** `agent:invoke`  
- **Description:** Submits a message and streams real-time Server-Sent Events (`text/event-stream`).  
- **Request Body:** Identical to `AgentRequest`.  
- **Response Stream (`200 OK`):** Streams 7 event types (`run_started`, `token`, `tool_call`, `final`, `error`, `done`, `: ping`). See [SSE Protocol Specification](sse-protocol.md).

---

## 4. Conversation Thread Management

### 4.1 Read Thread Messages
`GET /v1/threads/{thread_id}/messages`  
- **Scope Required:** `threads:read`  
- **Query Parameters:**
  - `limit` (integer, default 50, max 100): Number of messages to return.
  - `offset` (integer, default 0): Number of messages to skip.
- **Response (`200 OK`, `ThreadHistoryResponse`):**
  ```json
  {
    "thread_id": "019318b2-5f6e-7b3c-8a12-abcdef123456",
    "messages": [
      {"role": "user", "content": "Hello!"},
      {"role": "assistant", "content": "Hello! How can I help you today?"}
    ],
    "total": 2,
    "limit": 50,
    "offset": 0
  }
  ```

### 4.2 Rename Thread
`PATCH /v1/threads/{thread_id}`  
- **Scope Required:** `threads:write`  
- **Request Body (`RenameThreadRequest`):**
  ```json
  {"title": "Compiler Architecture Discussion"}
  ```
- **Response (`200 OK`, `ThreadTitleResponse`):**
  ```json
  {
    "thread_id": "019318b2-5f6e-7b3c-8a12-abcdef123456",
    "title": "Compiler Architecture Discussion"
  }
  ```

### 4.3 Submit Answer Feedback
`POST /v1/threads/{thread_id}/runs/{run_id}/feedback`  
- **Scope Required:** `feedback:write`  
- **Request Body (`FeedbackRequest`):**
  ```json
  {"rating": "positive"}
  ```
  *(Rating: `"positive"` or `"negative"`)*
- **Response (`200 OK`, `FeedbackResponse`):**
  ```json
  {
    "thread_id": "019318b2-5f6e-7b3c-8a12-abcdef123456",
    "run_id": "run-456",
    "rating": "positive"
  }
  ```

### 4.4 Delete Thread
`DELETE /v1/threads/{thread_id}`  
- **Scope Required:** `threads:delete`  
- **Description:** Deletes all checkpoints, messages, titles, and ratings for this thread.  
- **Response:** `204 No Content`  
- **Error:** `409 thread_busy` if a run is currently in flight on the thread.

---

## 5. Approvals (Human-in-the-Loop)

### 5.1 Read Pending Approval
`GET /v1/threads/{thread_id}/approval`  
- **Scope Required:** `agent:approve`  
- **Response (`200 OK`, `ApprovalRequiredResponse`):** Returns the currently pending approval object.  
- **Error:** `404 approval_not_found` if no decision is pending.

### 5.2 Submit Approval Decision (Synchronous)
`POST /v1/threads/{thread_id}/approvals/{approval_id}`  
- **Scope Required:** `agent:approve`  
- **Request Body (`ApprovalDecisionRequest`):**
  ```json
  {
    "decision": "approve",
    "knowledge_base_ids": ["8f3b2e1a-4c5d-6e7f-8a9b-0c1d2e3f4a5b"]
  }
  ```
- **Response (`200 OK`):** Returns final `AgentResponse` or another `ApprovalRequiredResponse`.

### 5.3 Submit Approval Decision (Streaming)
`POST /v1/threads/{thread_id}/approvals/{approval_id}/stream`  
- **Scope Required:** `agent:approve`  
- **Response (`200 OK`):** Streams the continuation of the run over SSE.

---

## 6. User Data Rights & Privacy (GDPR / CCPA)

### 6.1 List User Threads
`GET /v1/me/threads`  
- **Scope Required:** `threads:read`  
- **Query Parameters:** `limit` (default 20, max 100), `offset` (default 0).  
- **Response (`200 OK`, `UserThreadsResponse`):** Summaries of caller threads (IDs, titles, timestamps).

### 6.2 Export Complete User Data
`GET /v1/me/export`  
- **Scope Required:** `threads:read`  
- **Query Parameters:** `limit` (default 5), `offset` (default 0), `message_limit` (default 20), `message_offset` (default 0).  
- **Response (`200 OK`, `UserDataExportResponse`):** Structured JSON containing threads, messages, memories, and knowledge base metadata.  
- **Error:** `413 export_too_large` if the page exceeds 5 MB.

### 6.3 Bulk Erase User Data
`DELETE /v1/me/threads`  
- **Scope Required:** `data:erase`  
- **Description:** Irreversibly deletes all conversation checkpoints, metadata, ratings, and memory notes.  
- **Response (`200 OK`, `UserDataErasureResponse`):**
  ```json
  {
    "erased_thread_count": 5,
    "busy_thread_count": 0,
    "erased_memory_count": 2,
    "erased_knowledge_base_count": 1,
    "erased_knowledge_document_count": 4,
    "knowledge_purge_pending": false
  }
  ```

---

## 7. User Memory Subsystem

### 7.1 List Memories
`GET /v1/me/memories`  
- **Scope Required:** `memories:read`  
- **Response (`200 OK`, `MemoriesResponse`):** List of stored user notes.

### 7.2 Delete Single Memory
`DELETE /v1/me/memories/{memory_id}`  
- **Scope Required:** `memories:write`  
- **Response:** `204 No Content`

### 7.3 Delete All Memories
`DELETE /v1/me/memories`  
- **Scope Required:** `memories:write`  
- **Response (`200 OK`, `MemoryErasureResponse`):** `{"erased_count": 3}`

---

## 8. Knowledge Engine (RAG) Endpoints

### 8.1 List Knowledge Bases
`GET /v1/knowledge/bases`  
- **Scope Required:** `knowledge:read`  
- **Response (`200 OK`, `KnowledgeBasesResponse`):** Array of caller's active knowledge bases.

### 8.2 Create Knowledge Base
`POST /v1/knowledge/bases`  
- **Scope Required:** `knowledge:write`  
- **Request Body (`KnowledgeBaseCreate`):**
  ```json
  {"name": "Engineering Docs", "processing": "hosted"}
  ```
- **Response (`201 Created`, `KnowledgeBase`):** Returns created knowledge base object.  
- **Error:** `409 knowledge_base_limit_reached` (max 20 bases per user).

### 8.3 Rename Knowledge Base
`PATCH /v1/knowledge/bases/{kb_id}`  
- **Scope Required:** `knowledge:write`  
- **Request Body (`KnowledgeBaseUpdate`):** `{"name": "New Name"}`  
- **Response (`200 OK`):** Updated `KnowledgeBase`.

### 8.4 Delete Knowledge Base
`DELETE /v1/knowledge/bases/{kb_id}`  
- **Scope Required:** `knowledge:write`  
- **Description:** Tombstones the knowledge base and queues background purge.  
- **Response:** `202 Accepted`

### 8.4a Share a Knowledge Base by Role
`GET /v1/knowledge/bases/{kb_id}/grants` and `PUT /v1/knowledge/bases/{kb_id}/grants`  
- **Scope Required:** `knowledge:admin`, and the base's owner or a role with `admin` access to it (RAG-09.03).  
- **Request Body (`KnowledgeGrants`, `PUT`):** `{"grants": [{"role": "finance", "access": "read"}]}`. Replaces every role grant of the base: a role left out loses its access from the next request. At most 50, each role once, 1 to 200 characters without control characters or outer spaces; `access` is `read` (list, search, cite, download), `write` (also upload and delete documents) or `admin` (also rename and manage grants).  
- **Response (`200 OK`, `KnowledgeGrants`):** The base's role grants, sorted by role. The owner's own access is not listed.  
- **Errors:** `403 knowledge_access_denied` for a member without `admin` access; `404 knowledge_base_not_found` for a base the caller cannot see. Each change is audited as `knowledge_grant_changed` with the role and access level (`none` for a revoke).

A role grant shares a base with every holder of that role in a verified token (`APP_AUTH_ROLES_CLAIM`). Members see it in `GET /v1/knowledge/bases` and in search; an action their access does not allow is `403 knowledge_access_denied`. Only the owner deletes a base.

### 8.5 Upload Document
`POST /v1/knowledge/bases/{kb_id}/documents`  
- **Scope Required:** `knowledge:write`  
- **Content-Type:** `multipart/form-data`  
- **Headers:** `Idempotency-Key` (optional, 1–200 ASCII chars).  
- **Form Fields:** `file` (binary, required), `title` (string, optional).  
- **Response (`202 Accepted`, `DocumentAccepted`):**
  ```json
  {
    "doc_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
    "kb_id": "8f3b2e1a-4c5d-6e7f-8a9b-0c1d2e3f4a5b",
    "status": "queued",
    "status_url": "/v1/knowledge/documents/a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d"
  }
  ```
- **Errors:** `413 file_too_large` (>50MB), `415 unsupported_media_type`, `429 upload_busy`.

### 8.6 List Base Documents
`GET /v1/knowledge/bases/{kb_id}/documents`  
- **Scope Required:** `knowledge:read`  
- **Query Parameters:** `limit` (default 50), `offset` (default 0).  
- **Response (`200 OK`, `KnowledgeDocumentsResponse`):** Paginated documents list.

### 8.7 Get Document Details
`GET /v1/knowledge/documents/{doc_id}`  
- **Scope Required:** `knowledge:read`  
- **Response (`200 OK`, `KnowledgeDocument`):** Status, error codes, page count, sizes.

### 8.8 Get Document Chunk
`GET /v1/knowledge/documents/{doc_id}/chunks/{chunk_id}`  
- **Scope Required:** `knowledge:read`  
- **Query Parameters:** `neighbours` (integer, 0 to 3, default 0).  
- **Response (`200 OK`, `KnowledgeChunk`):** Extracted text, headings, pages, and surrounding neighbor chunks.

### 8.9 Download Original File
`GET /v1/knowledge/documents/{doc_id}/file`  
- **Scope Required:** `knowledge:read`  
- **Response (`200 OK`):** Raw file stream with `Content-Disposition: attachment`.

### 8.10 Search Knowledge Bases
`POST /v1/knowledge/search`  
- **Scope Required:** `knowledge:read`  
- **Request Body (`KnowledgeSearchRequest`):**
  ```json
  {
    "query": "sliding window token budget",
    "kb_ids": ["8f3b2e1a-4c5d-6e7f-8a9b-0c1d2e3f4a5b"],
    "limit": 5
  }
  ```
- **Response (`200 OK`, `KnowledgeSearchResponse`):**
  ```json
  {
    "status": "ok",
    "results": [
      {
        "chunk_id": "...",
        "doc_id": "...",
        "kb_id": "...",
        "title": "Architecture Spec",
        "ordinal": 4,
        "text": "...",
        "headings": ["Security"],
        "page_start": 10,
        "page_end": 10,
        "score": 0.032
      }
    ]
  }
  ```

### 8.11 Delete Document
`DELETE /v1/knowledge/documents/{doc_id}`  
- **Scope Required:** `knowledge:write`  
- **Response:** `202 Accepted`

### 8.12 Erase All Knowledge
`DELETE /v1/me/knowledge`  
- **Scope Required:** `data:erase`  
- **Response (`200 OK`, `KnowledgeErasureResponse`):** Erased base count, document count, and purge pending status.
