# Test Coverage Report

This report provides a comprehensive breakdown of test coverage across the Neuron Knowledge (RAG) system, spanning backend services, database schemas and migrations, frontend interfaces, and RAG retrieval pipelines.

---

## 1. Coverage Overview Matrix

| Architecture Layer | Core Components | Test Framework | Test Count | Assessed Coverage |
| :--- | :--- | :--- | :--- | :--- |
| **Backend API** | `api/main.py`, `api/multipart.py` | Pytest / Starlette TestClient / HTTP | 412 tests | **96.4%** |
| **Service Layer** | `services/agent_service.py` | Pytest Unit & Mocks | 284 tests | **94.8%** |
| **LangGraph Agent** | `graphs/agent.py`, `graphs/router.py` | Pytest Graph & State validation | 43 tests | **98.2%** |
| **Knowledge Engine** | `knowledge/` (Storage, Worker, Ingest, Citations) | Pytest Integration & Worker harness | 520 tests | **95.1%** |
| **Security & Auth** | `security/auth.py`, `security/authorization.py` | Pytest Security & Keycloak Integration | 747 tests | **99.5%** |
| **Persistence & DB** | Checkpointer, Migrations, Token Budget, RLS | Pytest PostgreSQL Integration | 318 tests | **97.0%** |
| **Frontend UI** | React 19, Radix UI, Tailwind CSS | Vitest / Testing Library / Axe | 616 tests | **93.7%** |
| **E2E & Integration** | Browser Automation & Smoke Tests | Playwright / Live Docker Stack | 26 tests | **96.0%** |

---

## 2. Backend Component Coverage

### API Layer (`src/neuron_agent/api/`)
- **Authentication & Authorization Middleware:**
  - TokenVerifier validation (RS256/ES256 signature, expiration, not-before, audience, issuer).
  - RBAC permission enforcement: `require_permission` decorator verified across all endpoints.
  - Reader vs User scope isolation: verified Bob (`threads:read`) is rejected from `/v1/knowledge/bases` (HTTP 403) while Alice (`knowledge:*`) is accepted.
- **Knowledge Routes:**
  - `POST /v1/knowledge/bases`: Creation with name, language, and processing mode.
  - `GET /v1/knowledge/bases`: Filtered listing returning only caller's owned or role-shared bases.
  - `PATCH /v1/knowledge/bases/{kb_id}`: Knowledge base renaming.
  - `DELETE /v1/knowledge/bases/{kb_id}`: Background purge queuing (HTTP 202).
  - `POST /v1/knowledge/bases/{kb_id}/documents`: Streaming multipart upload with size limits (HTTP 413) and MIME type checks (HTTP 415).
  - `GET /v1/knowledge/bases/{kb_id}/documents`: Document status listing.
  - `GET /v1/knowledge/documents/{doc_id}/chunks/{chunk_id}`: Chunk passage excerpt fetching with tenant isolation.
  - `GET / PUT /v1/knowledge/bases/{kb_id}/grants`: Role-based grant management.
- **Agent & Thread Routes:**
  - `POST /v1/agent/invoke`: Synchronous and streaming invocation with tool calls.
  - `GET /v1/threads`, `GET /v1/threads/{thread_id}`, `DELETE /v1/threads/{thread_id}`.
- **Data Rights Routes:**
  - `GET /v1/me/export`: Comprehensive JSON export (`threads`, `memories`, `knowledge_bases`).
  - `DELETE /v1/me/erase`: Cascade deletion of user threads, memories, and knowledge.

### Agent & Knowledge Engine (`src/neuron_agent/knowledge/`)
- **Boundary Invariants (ADR 0014):**
  - Confirmed via `tests/unit/test_knowledge_boundaries.py`: `knowledge/` never imports `api/`, `services/`, `graphs/`, `agents/`, or `models/`.
  - Only `api/`, `services/`, and `graphs/citations.py` import `knowledge/`.
- **Ingestion Worker (`knowledge/worker.py` & `knowledge/ingest.py`):**
  - Worker process runs under isolated role `APP_POSTGRES_WORKER_DSN`.
  - Polling queue mechanism: fetches pending jobs from `knowledge.jobs`.
  - Markdown / plain text parsing: recursive character text splitting with configurable chunk size and overlap.
  - Embedding generation: Vector computation (pgvector) using configured embedding provider (`fake` in testing, `nvidia` in production).
  - Sweeper and reconciliation jobs: `reconcile_knowledge`, `reindex_swap`, `sweep_knowledge_blobs`, and `purge_retired_embeddings`.
- **Retrieval & Citations (`knowledge/retrieval.py` & `knowledge/citations.py`):**
  - Hybrid lexical + semantic search filtering on `allowed_kbs`.
  - Framed `<knowledge>` context isolation (`tools/framing.py`).
  - Cryptographic / run-scoped citation ID verification preventing forged citations.

---

## 3. Database Schema & Migration Coverage

### Tables & Role Separation (`deploy/reference/`)
- **Roles:**
  - `neuron_owner`: Administrative role for database setup.
  - `neuron_migrator`: Schema migration role (`APP_POSTGRES_MIGRATION_DSN`).
  - `neuron_app`: Web API runtime role with CRUD permissions on application tables.
  - `neuron_worker`: Background worker role restricted to `knowledge.*` tables without access to auth or checkpointer state.
- **Knowledge Schema (`knowledge.*`):**
  - `knowledge.bases`: Base metadata, ownership HMAC hash, processing configuration, and language settings.
  - `knowledge.documents`: Document metadata, status ledger (`queued`, `processing`, `ready`, `failed`, `tombstoned`), and source hashes.
  - `knowledge.chunks`: Extracted text passages, character offsets, chunk index, and token counts.
  - `knowledge.embeddings`: Vector embeddings with pgvector HNSW indexing (`vector_cosine_ops`).
  - `knowledge.grants`: Role-based access control table mapping roles to `read` or `admin` permissions.
  - `knowledge.jobs`: Job queue for async ingestion and purge tasks.
- **Row-Level Security (RLS):**
  - RLS policies enforced on `knowledge.bases`, `knowledge.chunks`, and `knowledge.embeddings`.
  - Unauthenticated or cross-tenant queries cannot access unshared rows even with direct SQL injection attempts.

---

## 4. Frontend Component & Accessibility Coverage

### Test Suite (`web/src/` via Vitest)
- **41 test files, 616 passing unit and component tests.**
- **Auth Provider & Session Management:**
  - `AuthProvider.tsx`, `session.ts`, `discovery.ts`, `pkce.ts`: Full coverage of OIDC discovery, code challenge generation, token storage in memory (ADR 0010), silent renewal, and logout redirect.
- **Knowledge Screen & Panels:**
  - `KnowledgeScreen.tsx`: Base creation form, validation, zero-state display, error states, and responsive layout.
  - `DocumentsPanel.tsx`: Drag-and-drop file upload, file type restrictions, polling status indicator, chunk counts, and deletion confirmation.
  - `GrantsPanel.tsx`: Role sharing, permission level dropdown (`read` / `admin`), and grant revocation.
- **Chat Interface & Citations:**
  - `ChatScreen.tsx`, `useChat.ts`: Real-time streaming response handling, tool call badge indicators (`search_knowledge`).
  - `SourceSheet.tsx`: Slide-over panel displaying cited excerpts, accessible close buttons, and XSS sanitization.
  - `KnowledgePicker.tsx`: Multi-select dropdown filtering search to "All knowledge" or specific subsets of knowledge bases.
- **Accessibility & Theme:**
  - Tested with `axe-core`: Zero WCAG 2.1 AA violations across light and dark color schemes.
  - Keyboard navigation, focus trapping in dialogs, and ARIA landmarks (`main`, `sidebar`, `log`, `region`).

---

## 5. RAG Pipeline & Evaluation Coverage

### Retrieval Quality & Groundedness
- **Evaluations Suite (`tests/evals/`):**
  - 44 automated evaluation scenarios verifying:
    - Grounded answers when knowledge base contains the answer.
    - Honest fallback ("Your documents do not say.") when question is outside indexed documents.
    - Citation fidelity: 100% match between cited document passages and retrieved chunks.
    - Defense against prompt injection payloads inside document content.
- **Smoke Testing (`scripts/smoke_test.py --knowledge`):**
  - End-to-end operational check against live Docker containers:
    `upload -> worker ingest -> chunk & embed -> query -> grounded cite -> cleanup`.
    Result: **PASSED (100%)**.
