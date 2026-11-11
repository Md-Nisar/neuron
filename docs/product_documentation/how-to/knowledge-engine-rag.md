# How-To: Ingest Documents and Query Knowledge Bases (RAG)

> **Document ID:** DOC-HOW-003  
> **Diátaxis Mode:** How-To Guide (Task-Oriented)  
> **Standard Alignment:** Structured in alignment with ISO/IEC/IEEE 26514:2022 §7.4 (Procedural Task Information) and Diátaxis (How-To Guide)  
> **Audience:** Developers, Integrators, AI Engineers  
> **Code Traceability:** `src/neuron_agent/knowledge/`, ADR 0014, `docs/product/RAG_IMPLEMENTATION_TRACKER.md`

---

## 1. Overview and RAG Architecture

The Neuron Knowledge Engine (v1.1.0) provides an enterprise retrieval-augmented generation (RAG) subsystem. Users can upload private documents (PDF, DOCX, XLSX, PPTX, Markdown, Text) into isolated knowledge bases. Background workers parse, chunk, embed, and index documents into PostgreSQL using hybrid vector/full-text search. The agent accesses retrieved passages through bounded tools with cryptographic citation verification.

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

## 2. Prerequisites and Environment Setup

Enable the Knowledge Engine in `.env`:

```bash
# Mandatory prerequisite: Postgres checkpointer is strictly required
APP_CHECKPOINTER=postgres

# Enable the Knowledge Engine
APP_KNOWLEDGE_ENABLED=true

# Embedding Provider Configuration (NVIDIA or openai_compatible)
APP_KNOWLEDGE_EMBEDDING_PROVIDER=nvidia
APP_KNOWLEDGE_EMBEDDING_MODEL=nvidia/nemotron-3.5-embed-1b
APP_KNOWLEDGE_EMBEDDING_DIMENSIONS=1024
APP_KNOWLEDGE_SEARCH_MODE=hybrid

# docling-serve endpoint (for PDF and Office documents)
APP_KNOWLEDGE_PARSER_URL=http://docling:5001
APP_KNOWLEDGE_PARSER_TIMEOUT_SECONDS=900

# Blob Store Configuration (local directory or S3)
APP_KNOWLEDGE_BLOB_BACKEND=local
APP_KNOWLEDGE_BLOB_ROOT=var/knowledge-blobs
APP_KNOWLEDGE_BLOB_LOCAL_ALLOWED=true

# Worker Configuration
APP_POSTGRES_WORKER_DSN=postgresql://neuron_worker:worker-pass@localhost:5432/neuron_dev
APP_WORKER_CONCURRENCY=2
```

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
Create a knowledge base for project documentation. Specify processing locality (`hosted` or `self_hosted`):

```bash
curl -X POST http://127.0.0.1:8000/v1/knowledge/bases \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Engineering Architecture Guides",
    "processing": "hosted"
  }'
```

#### Response (`201 Created`)
```json
{
  "kb_id": "8f3b2e1a-4c5d-6e7f-8a9b-0c1d2e3f4a5b",
  "name": "Engineering Architecture Guides",
  "processing": "hosted",
  "created_at": "2026-11-12T02:00:00Z"
}
```

---

### Step 2: Upload a Document
Upload a document using `multipart/form-data`. Optionally provide an `Idempotency-Key` header to safely retry uploads without duplicate processing:

```bash
KB_ID="8f3b2e1a-4c5d-6e7f-8a9b-0c1d2e3f4a5b"

curl -X POST "http://127.0.0.1:8000/v1/knowledge/bases/$KB_ID/documents" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: upload-runbook-20261112" \
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

### Step 3: Monitor Ingestion Status
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

### Step 4: Perform Direct Hybrid Search
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
      "score": 0.0328
    }
  ]
}
```

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
When the agent uses retrieved passages, it outputs citations:
```json
{
  "status": "completed",
  "answer": "According to the architecture spec, token budgets are tracked over a 1-hour rolling window [cite:c1a2b3].",
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

Clients can inspect the exact passage cited by calling:
```bash
GET /v1/knowledge/documents/{doc_id}/chunks/{chunk_id}?neighbours=1
```

---

## 5. Deleting Documents and Purging Blobs

Deleting a document or base is asynchronous:
1. `DELETE /v1/knowledge/documents/{doc_id}`: Sets `deleted_at` (tombstone) and immediately returns `202 Accepted`.
2. Document disappears immediately from all queries and searches.
3. The worker's `purge_document` background task permanently deletes the blob file, chunk rows, and embeddings from PostgreSQL.
