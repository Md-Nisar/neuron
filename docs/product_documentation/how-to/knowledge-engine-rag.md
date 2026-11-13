# How-To: Ingest Documents, Share, and Query Knowledge Bases (RAG)

> **Document ID:** DOC-HOW-003  
> **Diátaxis Mode:** How-To Guide (Task-Oriented)  
> **Standard Alignment:** Structured in alignment with ISO/IEC/IEEE 26514:2022 §7.4 (Procedural Task Information) and Diátaxis (How-To Guide)  
> **Audience:** Developers, Integrators, AI Engineers  
> **Code Traceability:** `src/neuron_agent/knowledge/`, ADR 0014, `docs/product/RAG_IMPLEMENTATION_TRACKER.md`

---

## 1. Overview and RAG Architecture

The Neuron Knowledge Engine (v1.2.0) provides an enterprise retrieval-augmented generation (RAG) subsystem. Users can upload private documents (PDF, DOCX, XLSX, PPTX, Markdown, Text) into isolated knowledge bases. Background workers parse, chunk, embed, and index documents into PostgreSQL using hybrid vector/full-text search with optional cross-encoder candidate reranking. Bases can be shared with verified token roles (`read`, `write`, `admin`), and operators can re-index embeddings to new models without downtime.

```mermaid
sequenceDiagram
    autonumber
    participant User as Client / Web App
    participant API as neuron-api
    participant Blob as Blob Storage (obstore)
    participant DB as PostgreSQL (knowledge schema)
    participant Worker as neuron-worker
    participant Docling as docling-serve (Isolated Container)
    participant Embed as Embedding Provider (NVIDIA/OpenAI)

    User->>API: POST /v1/knowledge/bases/{kb_id}/documents (multipart file)
    API->>API: Check file content type, size (<50MB) & user quotas
    API->>Blob: Stream file bytes to random key (SHA-256)
    API->>DB: INSERT knowledge.documents (status='queued')
    API->>DB: INSERT procrastinate_jobs (task='ingest_document')
    API-->>User: 202 Accepted {doc_id, status: "queued", status_url}

    Note over Worker,Docling: Asynchronous Background Ingestion
    Worker->>DB: Claim ingest job
    Worker->>Blob: Fetch original document bytes (verify SHA-256)
    alt Complex File (PDF/DOCX/XLSX/PPTX)
        Worker->>Docling: POST /v1/convert/file (internal network)
        Docling-->>Worker: Parsed blocks JSON
    else Plain Text / Markdown
        Worker->>Worker: Internal PlainTextParser
    end
    Worker->>Worker: Chunk document into heading paths (max 400 tokens)
    Worker->>Embed: Embed chunk texts in batches
    Embed-->>Worker: Dense vectors
    Worker->>DB: Transaction: Set status='ready', insert chunks & halfvec embeddings
    Worker->>DB: Complete job
```

---

## 2. Prerequisites & Environment Setup

Ensure the following settings are configured in `.env`:

```bash
# Enable Knowledge Engine
APP_KNOWLEDGE_ENABLED=true
APP_CHECKPOINTER=postgres
APP_POSTGRES_DSN="postgresql://neuron_app:app-secret@localhost:5432/neuron_dev"
APP_POSTGRES_WORKER_DSN="postgresql://neuron_worker:worker-secret@localhost:5432/neuron_dev"

# Embedding Model Configuration
APP_KNOWLEDGE_EMBEDDING_PROVIDER=nvidia
APP_KNOWLEDGE_EMBEDDING_MODEL="nvidia/nemotron-3.5-embed-1b"
APP_KNOWLEDGE_EMBEDDING_DIMENSIONS=1024
APP_KNOWLEDGE_EMBEDDING_BATCH_SIZE=1

# Optional Cross-Encoder Reranker
APP_KNOWLEDGE_RERANKER=nvidia
APP_KNOWLEDGE_RERANKER_MODEL="nvidia/llama-nemotron-rerank-vl-1b-v2"
APP_KNOWLEDGE_RERANKER_TIMEOUT_SECONDS=3.0

# Document Storage & Parser URL
APP_KNOWLEDGE_BLOB_BACKEND=local
APP_KNOWLEDGE_BLOB_ROOT="var/knowledge-blobs"
APP_KNOWLEDGE_PARSER_URL="http://localhost:5001"
```

> [!TIP]
> **NVIDIA Embeddings Batch Size:**  
> When using NVIDIA's API catalog, leave `APP_KNOWLEDGE_EMBEDDING_BATCH_SIZE` unset or set to `1`. Larger batch sizes on real-world document chunks may trigger HTTP 500 responses from upstream catalog endpoints (#480).

### Running docling-serve
For parsing PDF, Word, Excel, or PowerPoint documents, run the `docling-serve` container:

```bash
docker run -d --name docling \
  -p 5001:5001 \
  --read-only \
  --cap-drop=ALL \
  ghcr.io/docling-serve:latest
```
*(In Docker Compose, enable `COMPOSE_PROFILES=pdf`)*

### Starting the Ingestion Worker
Run the worker in a dedicated process:

```bash
uv run neuron-worker run
```

---

## 3. Step-by-Step RAG Workflow

### Step 1: Create a Knowledge Base
Create a knowledge base with a designated processing locality (`hosted` or `self_hosted`) and language configuration:

```bash
curl -X POST http://127.0.0.1:8000/v1/knowledge/bases \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Engineering Architecture Guides",
    "processing": "hosted",
    "language": "english"
  }'
```

#### Multilingual Full-Text Search Configuration
The `language` parameter selects one of PostgreSQL's 29 built-in full-text search dictionaries (`simple`, `english`, `german`, `french`, `spanish`, `hindi`, etc.). Chunks extracted into this base will be stemmed using the selected dictionary, enabling accurate inflectional matching (e.g., "Häuser" matches "Haus" in German). `language` is fixed at creation.

#### Response (`201 Created`)
```json
{
  "kb_id": "8f3b2e1a-4c5d-6e7f-8a9b-0c1d2e3f4a5b",
  "name": "Engineering Architecture Guides",
  "processing": "hosted",
  "language": "english",
  "created_at": "2026-11-13T10:00:00Z",
  "access": "owner"
}
```

---

### Step 2: Share a Knowledge Base with Token Roles (RAG-09.03)
The creator (`owner`) or an assigned `admin` can share the knowledge base with specific token roles:

```bash
KB_ID="8f3b2e1a-4c5d-6e7f-8a9b-0c1d2e3f4a5b"

curl -X PUT "http://127.0.0.1:8000/v1/knowledge/bases/$KB_ID/grants" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "grants": [
      {"role": "engineering", "access": "write"},
      {"role": "product-ops", "access": "read"}
    ]
  }'
```

- **Scope Required:** `knowledge:admin`.
- **Access Levels:**
  - `read`: List base, search passages, receive citations, download files.
  - `write`: All `read` capabilities + upload documents and delete individual documents.
  - `admin`: All `write` capabilities + rename knowledge base and manage role grants.
- **Ownership Invariant:** Only the original creator retains `owner` status; role grants cannot delete the base, export its data, or execute account erasure.

---

### Step 3: Upload a Document
Upload a document using `multipart/form-data`. Optionally provide an `Idempotency-Key` header to safely retry uploads without duplicate processing:

```bash
curl -X POST "http://127.0.0.1:8000/v1/knowledge/bases/$KB_ID/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: upload-runbook-20261113" \
  -F "file=@spec.pdf;type=application/pdf" \
  -F "title=System Architecture Specification"
```

#### Response (`202 Accepted`)
```json
{
  "doc_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
  "kb_id": "8f3b2e1a-4c5d-6e7f-8a9b-0c1d2e3f4a5b",
  "status": "queued",
  "status_url": "/v1/knowledge/documents/a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d"
}
```

---

### Step 4: Monitor Ingestion Status
Poll the `status_url` until the document reaches `ready`:

```bash
DOC_ID="a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d"

curl -s "http://127.0.0.1:8000/v1/knowledge/documents/$DOC_ID" \
  -H "Authorization: Bearer $TOKEN"
```

#### Document Lifecycle Statuses
1. `queued`: File received and stored in blob storage; job queued in Procrastinate.
2. `parsing`: Content being converted to structured blocks by `docling-serve` or internal text parser.
3. `embedding`: Text chunks being passed to embedding model.
4. `ready`: Chunks and embeddings committed to PostgreSQL; document searchable.
5. `failed`: Ingestion halted. The `error_code` field contains a stable failure code (e.g., `file_too_large`, `encrypted_pdf`, `no_text`, `parser_timeout`).

---

### Step 5: Perform Direct Hybrid Search & Candidate Reranking
Query the knowledge base directly via REST API:

```bash
curl -X POST http://127.0.0.1:8000/v1/knowledge/search \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is the token budget policy?",
    "kb_ids": ["8f3b2e1a-4c5d-6e7f-8a9b-0c1d2e3f4a5b"],
    "limit": 3
  }'
```

#### Response
```json
{
  "status": "ok",
  "reranked": true,
  "results": [
    {
      "chunk_id": "e4f5a6b7-c8d9-0e1f-2a3b-4c5d6e7f8a9b",
      "doc_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
      "kb_id": "8f3b2e1a-4c5d-6e7f-8a9b-0c1d2e3f4a5b",
      "title": "System Architecture Specification",
      "ordinal": 4,
      "text": "The token budget is managed by a sliding 1-hour window...",
      "headings": ["Security", "Resource Management", "Token Budgets"],
      "page_start": 12,
      "page_end": 12,
      "score": 0.942
    }
  ]
}
```
Notice `"reranked": true`: The top 40 candidates from dense vector and full-text search were scored by the cross-encoder reranker. If the reranker times out or fails, search transparently falls back to RRF order and sets `"reranked": false`.

---

## 4. Querying Knowledge Bases Through the Agent

When `knowledge_base_ids` is provided in `/v1/agent/invoke` or `/v1/agent/stream`, the agent is equipped with three scoped knowledge tools:
1. `list_knowledge_bases`: Lists available bases matching caller permissions.
2. `search_knowledge`: Executes hybrid search (max 5 searches per turn).
3. `get_document_excerpt`: Fetches surrounding chunks using a `cite_id` returned during search.

### Example Agent Invocation
```bash
curl -X POST http://127.0.0.1:8000/v1/agent/invoke \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Summarize our token budget policy from the architecture spec.",
    "knowledge_base_ids": ["8f3b2e1a-4c5d-6e7f-8a9b-0c1d2e3f4a5b"]
  }'
```

### Verified Citation Grounding
When the agent uses retrieved passages, it outputs verified citations:

```json
{
  "status": "completed",
  "answer": "The token budget operates on a rolling 1-hour window...",
  "used_tools": ["search_knowledge"],
  "citations": [
    {
      "cite_id": "c1a2b3",
      "doc_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
      "chunk_id": "e4f5a6b7-c8d9-0e1f-2a3b-4c5d6e7f8a9b",
      "title": "System Architecture Specification",
      "headings": ["Security", "Token Budgets"],
      "page_start": 12,
      "page_end": 12
    }
  ],
  "citation_schema_version": 1,
  "grounded": true
}
```

---

## 5. Deleting Documents and Bases

Deleting a document or base is asynchronous:
1. `DELETE /v1/knowledge/documents/{doc_id}`: Sets `deleted_at` (tombstone) and immediately returns `202 Accepted`.
2. Document disappears immediately from all queries and searches.
3. The worker's `purge_document` background task permanently deletes the blob file, chunk rows, and embeddings from PostgreSQL.
4. `DELETE /v1/knowledge/bases/{kb_id}`: May only be executed by the base creator (`owner`). Tombstones the base and purges all documents.

---

## 6. Re-indexing to a New Embedding Model (Zero Downtime)

When migrating to a different embedding provider, model, or dimension, Neuron supports zero-downtime re-indexing into a new database index profile (ADR 0014, amendment "re-index to a new profile"). Active search continues uninterrupted using the current model until the new profile is 100% complete:

1. **Configure Target Settings:**
   Set the re-index model settings on the API, worker, and operator shells:
   ```bash
   APP_KNOWLEDGE_REINDEX_EMBEDDING_PROVIDER=nvidia
   APP_KNOWLEDGE_REINDEX_EMBEDDING_MODEL="nvidia/llama-3.2-nv-embedqa-1b-v2"
   APP_KNOWLEDGE_REINDEX_EMBEDDING_DIMENSIONS=2048
   APP_KNOWLEDGE_REINDEX_EMBEDDING_LOCALITY=hosted
   ```
   Keep the active `APP_KNOWLEDGE_EMBEDDING_*` settings on the current model. Restart the API and worker.

2. **Start Re-indexing:**
   As the migration role:
   ```bash
   uv run python -m neuron_agent.persistence.cli reindex start
   ```
   This verifies processing locality across all bases, concurrently builds the target HNSW index, marks the profile as `building`, and queues `reindex_kb` worker jobs for every live base.

3. **Monitor Re-indexing Progress:**
   ```bash
   uv run python -m neuron_agent.persistence.cli reindex status
   ```
   While `building`, all new uploads are automatically embedded with both active and re-index models.

4. **Automatic Profile Swap:**
   The worker's periodic `reindex_swap` task automatically checks whether every ready chunk has a vector under the building profile. When 100% covered, it promotes the building profile to `active` and retires the old profile within an atomic transaction.

5. **Post-Swap Cleanup:**
   After the swap, move the re-index settings into `APP_KNOWLEDGE_EMBEDDING_*`, remove the `_REINDEX_` settings, and restart. The worker automatically cleans up retired profile embeddings hourly in 5,000-row batches, and the next `setup` drops the retired HNSW index.

---

## 7. Auditing Low-Rated Answers and Cited Chunks (RAG-09.07)

Operators can inspect which chunks and documents are cited by answers that users rated negatively (thumbs-down):

```bash
uv run python -m neuron_agent.persistence.cli feedback-report
```

#### Sample JSON Output
```json
[
  {
    "thread_id": "019318b2-5f6e-7b3c-8a12-abcdef123456",
    "run_id": "run-456",
    "rating": "negative",
    "created_at": "2026-11-13T14:22:10Z",
    "citations": [
      {
        "doc_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
        "chunk_id": "e4f5a6b7-c8d9-0e1f-2a3b-4c5d6e7f8a9b"
      }
    ]
  }
]
```
This report operates directly on database IDs without logging or extracting chunk text or user prompts, preserving complete data confidentiality while enabling precise retrieval error analysis.
