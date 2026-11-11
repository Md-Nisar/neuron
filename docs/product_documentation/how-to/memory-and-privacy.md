# How-To: Manage User Memory and Data Subject Privacy Rights

> **Document ID:** DOC-HOW-005  
> **Diátaxis Mode:** How-To Guide (Task-Oriented)  
> **Standard Alignment:** Structured in alignment with ISO/IEC/IEEE 26514:2022 §7.4 (Procedural Task Information) and Diátaxis (How-To Guide)  
> **Audience:** Developers, Compliance Officers, Data Protection Officers  
> **Code Traceability:** `src/neuron_agent/memory/`, `src/neuron_agent/persistence/thread_index.py`, ADR 0005, ADR 0009

---

## 1. Overview and Compliance Model

Neuron Agent provides first-class support for privacy by design and data subject rights (GDPR Article 15/17, CCPA):
1. **User Memory:** A durable note store (`memory/store.py`) allowing users to persist personal facts across conversations. Memory is strictly scoped to the caller's HMAC owner key.
2. **Anti-Hallucination Guard:** The agent cannot fabricate memories or save tool output; the `remember` tool rejects anything not explicitly written by the user in the conversation.
3. **Right to Access & Portability (Export):** Users can export their entire conversation history, memory notes, and knowledge base metadata in a structured format via `GET /v1/me/export`.
4. **Right to Erasure (Forget):** Users can delete individual notes, single threads, or execute a comprehensive bulk erasure via `DELETE /v1/me/threads` and `DELETE /v1/me/knowledge`.

---

## 2. Configuring User Memory

Configure memory settings in `.env`:

```bash
# Enable the memory subsystem
APP_MEMORY_ENABLED=true

# Maximum notes per user (default 50)
APP_MEMORY_MAX_ITEMS=50

# Maximum characters per note (default 500)
APP_MEMORY_MAX_CHARS=500

# Note time-to-live in days (optional, null means indefinite)
APP_MEMORY_TTL_DAYS=90

# User data export size cap in bytes (default 5 MB)
APP_USER_DATA_EXPORT_MAX_BYTES=5000000
```

When using PostgreSQL (`APP_CHECKPOINTER=postgres`), run `make db-setup` to create the LangGraph `store` tables.

---

## 3. Working with Agent Memory Tools

When memory is enabled, the agent has access to three scoped tools:

### 1. `remember` (Scope: `tools:remember`, Risk: `mutating`)
Saves a note. The text must be quoted verbatim from what the user wrote in the current conversation:

```bash
# User says: "Remember that I am allergic to penicillin."
# Agent calls: remember(text="I am allergic to penicillin")
```

If the agent attempts to summarize or store unstated facts, the tool raises a `ToolException`:
> `"Error: only the user's own words can be remembered. Quote them exactly."`

### 2. `recall` (Scope: `tools:recall`, Risk: `read`)
Lists all notes stored for the user, presented to the model inside a framed `<notes>` block.

### 3. `forget` (Scope: `tools:forget`, Risk: `mutating`)
Deletes a specific note by ID when requested by the user.

---

## 4. Managing Memories Directly via REST API

Users can inspect and delete notes directly without using LLM tokens:

### List All Memories
```bash
curl -s http://127.0.0.1:8000/v1/me/memories \
  -H "Authorization: Bearer $TOKEN"
```
*(Requires `memories:read` scope)*

#### Response
```json
{
  "memories": [
    {
      "id": "e4f5a6b7c8d90e1f2a3b4c5d6e7f8a9b",
      "text": "I am allergic to penicillin",
      "created_at": "2026-11-12T01:30:00Z"
    }
  ]
}
```

### Delete a Specific Memory
```bash
curl -X DELETE "http://127.0.0.1:8000/v1/me/memories/e4f5a6b7c8d90e1f2a3b4c5d6e7f8a9b" \
  -H "Authorization: Bearer $TOKEN"
# Returns 204 No Content
```

### Delete All Memories
```bash
curl -X DELETE http://127.0.0.1:8000/v1/me/memories \
  -H "Authorization: Bearer $TOKEN"
```
#### Response
```json
{
  "erased_count": 1
}
```

---

## 5. Exercising Data Subject Rights

### 5.1 Listing User Threads
List conversation threads belonging to the authenticated caller (metadata only, no message text):

```bash
curl -s "http://127.0.0.1:8000/v1/me/threads?limit=20&offset=0" \
  -H "Authorization: Bearer $TOKEN"
```
*(Requires `threads:read` scope)*

#### Response
```json
{
  "threads": [
    {
      "thread_id": "019318b2-5f6e-7b3c-8a12-abcdef123456",
      "title": "Discussion about compilers",
      "created_at": "2026-11-12T01:00:00Z",
      "updated_at": "2026-11-12T01:15:00Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

---

### 5.2 Exporting Complete User Data (GDPR Portability)
Retrieve a structured, machine-readable export of all conversation history, ratings, memories, and knowledge base metadata:

```bash
curl -s "http://127.0.0.1:8000/v1/me/export?limit=10&offset=0&message_limit=50&message_offset=0" \
  -H "Authorization: Bearer $TOKEN"
```
*(Requires `threads:read` scope)*

#### Response
```json
{
  "threads": [
    {
      "thread_id": "019318b2-5f6e-7b3c-8a12-abcdef123456",
      "title": "Discussion about compilers",
      "created_at": "2026-11-12T01:00:00Z",
      "updated_at": "2026-11-12T01:15:00Z",
      "messages": [
        {"role": "user", "content": "Write a haiku about compilers."},
        {"role": "assistant", "content": "Code becomes machine..."}
      ],
      "total_messages": 2,
      "message_limit": 50,
      "message_offset": 0
    }
  ],
  "total_threads": 1,
  "limit": 10,
  "offset": 0,
  "memories": [
    {"id": "e4f5a6b7c8d90e1f2a3b4c5d6e7f8a9b", "text": "I am allergic to penicillin", "created_at": "2026-11-12T01:30:00Z"}
  ],
  "knowledge_bases": []
}
```

> [!NOTE]
> Exports are bounded by `APP_USER_DATA_EXPORT_MAX_BYTES` (default 5 MB). If a page exceeds this size, the server returns `413 export_too_large`; reduce `message_limit` or `limit` to paginate.

---

### 5.3 Bulk Erasure of User Data (GDPR Right to Be Forgotten)
Permanently and irreversibly erase all threads, checkpoints, titles, ratings, and memory notes belonging to the caller:

```bash
curl -X DELETE http://127.0.0.1:8000/v1/me/threads \
  -H "Authorization: Bearer $TOKEN"
```
*(Requires `data:erase` scope)*

#### Response
```json
{
  "erased_thread_count": 5,
  "busy_thread_count": 0,
  "erased_memory_count": 1,
  "erased_knowledge_base_count": 0,
  "erased_knowledge_document_count": 0,
  "knowledge_purge_pending": false
}
```

### 5.4 Erasing Knowledge Bases
To tombstone and purge all knowledge bases and uploaded documents:

```bash
curl -X DELETE http://127.0.0.1:8000/v1/me/knowledge \
  -H "Authorization: Bearer $TOKEN"
```
#### Response
```json
{
  "erased_base_count": 2,
  "erased_document_count": 12,
  "purge_pending": true,
  "complete": false
}
```
The documents and bases are immediately tombstoned and hidden from all queries; `neuron-worker` deletes the underlying files and vectors asynchronously.
