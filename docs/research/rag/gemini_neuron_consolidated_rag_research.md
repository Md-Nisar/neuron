# Neuron $\times$ NVIDIA RAG & Open-Source Ecosystem: Consolidated Architecture & Research Report

**Date:** November 2, 2026  
**Target Platform:** `Md-Nisar/neuron` (Verified at `v0.9.0`, commit `0f6f24c`)  
**Primary Reference Evaluated:** `NVIDIA-AI-Blueprints/rag` (Verified at `v2.6.x`, commit `29905d8`)  
**Status:** Consolidated Architecture Specification & Implementation Plan

---

## Executive Verdict

Neuron (`Md-Nisar/neuron`) must build a **Neuron-Native, Composable Knowledge Engine** inside its existing FastAPI + LangGraph + PostgreSQL monolith, paired with an asynchronous worker process (`neuron-worker`) from the same container image and a stateless out-of-process document parsing container (`docling-serve`).

Neuron must **not** adopt the NVIDIA RAG Blueprint (`NVIDIA-AI-Blueprints/rag`) as an application server, embedded runtime, or microservice fleet. Instead, Neuron will adopt NVIDIA’s embedding and reranking models behind provider interfaces, extract its hybrid retrieval and evaluation recipes, and reserve `nv-ingest` / NIM containers strictly as optional adapters for GPU-heavy enterprise deployments.

---

## 1. Cross-Report Audit: Challenging Assumptions & Resolving Contradictions

Cross-analyzing the three research reports revealed critical differences in repository inspection depth:
* **Report 1 (`claude_neuron_rag_research_v1.md`)** executed a full source-level clone of both `Md-Nisar/neuron` (commit `0f6f24c`, `v0.9.0`) and `NVIDIA-AI-Blueprints/rag` (commit `29905d8`, `v2.6.x`) alongside live PyPI wheel inspections.
* **Report 2 (`chatgpt_neuron_rag_research_v1.md`)** inspected raw GitHub manifests (`pyproject.toml`, `CHANGELOG.md`) and selected critical source files.
* **Report 3 (`gemini_neuron_rag_research_v1.md`)** operated from architectural specifications without a live git checkout, leading to several implementation assumptions that were refuted by actual source code inspection.

### 1.1 Technical Contradictions & Evidence-Based Resolutions

| Architectural Topic | Report 1 (Source-Cloned) | Report 2 (Manifest/File Inspected) | Report 3 (Spec-Derived) | Consolidated Ground-Truth Resolution |
| :--- | :--- | :--- | :--- | :--- |
| **Database Access & Migrations** | Uses raw `psycopg` 3 with hand-written, versioned SQL in `persistence/migrations.py` and a migrator/app DB role split; **no SQLAlchemy**. | Recommends raw SQL tables, dedicated schema, and separate DB roles. | Assumes SQLAlchemy 2.0 `AsyncSession` and Alembic migrations. | **Reject SQLAlchemy/Alembic.** Follow Neuron's native `psycopg` 3 repository pattern and versioned SQL migrations in `persistence/migrations.py`. |
| **In-Process Import of `nvidia_rag`** | Impractical due to dependency weight, global env state, and lack of `AuthorizationContext` seams. | **Impossible in a single venv:** Neuron requires Python `>=3.13,<3.15` and `openai>=3.6.0`; NVIDIA RAG requires Python `>=3.11,<3.14` and `openai<2.0`. | Rejects copying `rag_server` due to FastAPI lifespan and config collisions. | **Hard Dependency Conflict Confirmed.** `nvidia_rag` cannot be installed in Neuron's Python environment. Only call NIM endpoints over HTTP or via `langchain-nvidia-ai-endpoints`. |
| **Thread History & Citation Persistence** | `call_agent` stores **only** the user turn and final `AIMessage` (ADR 0005); intermediate tool messages are discarded after the run. | Proposes assembling citations from retrieved chunks into the final response. | Proposes returning citations from the tool node to the SSE stream. | **Stamp `AIMessage.additional_kwargs`.** Because tool messages are not persisted to thread history, validated citations must be stamped onto the final `AIMessage.additional_kwargs` (next to `run_id`) so citations survive thread reloads. |
| **User & Tenant Identity Model** | `Principal` uses `principal_owner_key()` = `HMAC(issuer, subject)`. JWT roles are mapped to scopes and discarded; no org/tenant table exists yet. | Proposes `owner_kind ('user', 'org')` and `owner_key`. | Assumes `user_id` and `tenant_id` UUIDs exist in `UserSecurityContext`. | **Use HMAC `owner_key` + Retain JWT Roles.** Update `security/auth.py` (`Principal`) and `AuthorizationContext` to retain JWT `roles`/`groups` rather than inventing a separate user/tenant directory. |
| **Docling Deployment Boundary** | Run **`docling-serve` as an out-of-process container**; run only lightweight `docling-core` (`HybridChunker`) in `neuron-worker`. | Run `Docling` `DocumentConverter` inside the isolated Python worker process. | Embed `Docling` inside the `neuron-worker` container. | **Adopt `docling-serve` + `docling-core`.** Embedding full `Docling` pulls PyTorch and heavy OCR weights ($\sim 1.2\text{ GB}$ RAM) into Neuron's image. `docling-serve` isolates ML dependencies while `docling-core` chunks in-worker. |
| **Postgres Job Queue Selection** | **`Procrastinate` 3.10.0** (MIT, Postgres-only, supports `psycopg` app connections and stalled-job recovery). | Custom `ingestion_jobs` table using `FOR UPDATE SKIP LOCKED`, leases, and heartbeats. | **`PGQueuer`** (MIT, `LISTEN/NOTIFY` + `FOR UPDATE SKIP LOCKED`). | **Adopt `Procrastinate` + Document Status Columns.** `Procrastinate` integrates natively with Neuron's `psycopg` 3 pool and handles retries/stalled workers, while `neuron_kb_documents` tracks stage state (`queued`, `parsing`, `embedding`, `ready`, `failed`, `deleting`). |
| **Memory Extensions (`LangMem` / `Mem0`)** | **Reject both.** ADR 0009 mandates storing "only the user's words" (no model auto-extraction), and `langmem` (`0.0.30`, Oct 2025) is stale. | **Reject `Mem0` / `Graphiti`** for MVP to preserve user-controlled memory and deletion contracts. | Recommends adopting `langmem` on `AsyncPostgresStore`. | **Reject `langmem` and `Mem0`.** Auto-extraction violates ADR 0009. Instead, enable `AsyncPostgresStore(index=...)` (`pgvector`) in Phase 5 for semantic recall over explicit user notes. |
| **Prompt Injection Guardrails (`llm-guard`)** | **Reject `llm-guard`** (`0.3.16`, last released May 2025—stale). Rely on Neuron's `taints_run=True` capability gate + delimited JSON framing. | Treat scanners as telemetry signals only; rely on `taints_run` capability control, delimiters, and approval gates. | Recommends embedding `protectai/llm-guard` DeBERTa scanner on every RAG/MCP output. | **Reject `llm-guard`; Enforce Capability Control (`taints_run=True`).** `llm-guard` is unmaintained and adds heavy model overhead. Neuron's existing taint gate (`ToolSpec.taints_run=True`) deterministically forces human approval on outbound tools after reading untrusted data. |
| **CPU Reranker Selection** | **`fastembed` (0.9.1, Oct 2026)** or **TEI**; notes `FlashRank` (`0.2.10`, Jan 2025) is stale. | Recommends TEI, NIM, or hosted cross-encoder behind `Reranker` protocol. | Recommends `AnswerDotAI/rerankers` with `FlashRank` ONNX CPU default. | **Use TEI / NVIDIA NIM + `fastembed` CPU Fallback.** Avoid `FlashRank` due to staleness. |
| **PostgreSQL BM25 Extension** | Start with native `tsvector` + GIN; upgrade to **`pg_textsearch` v1.0** (PostgreSQL license) if needed; reject `ParadeDB pg_search` (AGPL-3.0). | Use native PostgreSQL `tsvector` + GIN with RRF. | Use native `tsvector` + GIN default; notes `ParadeDB pg_search` is AGPL-3.0. | **Native `tsvector` + GIN in Phase 1/2; `pg_textsearch` (PostgreSQL license) as optional upgrade.** Strictly avoid `ParadeDB pg_search` due to AGPL-3.0. |
| **NVIDIA RAG Vector Store Defaults** | Verified `v2.6.x` supports Milvus, **Elasticsearch (default since v2.6.0)**, and LanceDB. | Notes Elasticsearch/Milvus defaults. | Assumes Milvus + cuVS is the sole default vector store. | **NVIDIA RAG `v2.6.x` defaults to Elasticsearch (plus Milvus/LanceDB), with zero `pgvector` support.** Neuron will use `pgvector`. |

---

## 2. Verified Baseline & Readiness Constraints

### 2.1 `Md-Nisar/neuron` Baseline (`v0.9.0`, commit `0f6f24c`)
* **Codebase Scale & Quality:** $\sim 13,000$ lines of Python in `src/neuron_agent`, $1,352$ test functions across unit, security, integration, eval, e2e, and resilience suites, paired with a React 19.3.1 + Tailwind 4.3.3 + shadcn/ui SPA.
* **Security & Governance Primitives:** OAuth2/OIDC JWT verification (`TokenVerifier`) with PKCE on the web client, HMAC owner keys (`principal_owner_key()`), `ToolRegistry` with `ToolSpec(scope, risk, source, taints_run)`, batched HITL approvals (`HumanInTheLoopMiddleware(interrupt_mode="batched")`), and SHA-256 pinned Streamable HTTP MCP tools.
* **Release Freeze & Operational Caveats:**
  1. `main` is under a **release freeze until `v1.0.0`** (`CLAUDE.md`, `CONTRIBUTING.md`), permitting only bug fixes, documentation, tests, and backward-compatible changes.
  2. `CHANGELOG.md` documents that while the local reference stack passed validation, hosted production model/deployment checks remain unrun and model tool-call reliability caveats exist.
  3. **Two Deployment Targets:** `api/main.py` (FastAPI service) and `langgraph.json` (LangGraph Agent Server export, where memory and gated tools are disabled). Knowledge tools must follow the memory precedent and activate on the FastAPI path only.
* **Blocking Open Issues in Neuron (`Md-Nisar/neuron`):**
  * **#364 (SSRF risk in outbound URL validation)** and **#366 (HTTPS-only fetches):** Must close before any web ingestion or `research_web` tool is enabled.
  * **#370 (MCP transport exceptions crash runs):** Must close before adding MCP-based knowledge connectors.
  * **#365 (Shared rate limiter for multi-instance deployments):** Needed before scaling out ingestion workers.
  * **#372 (Thread retention must respect leases):** Establishes the lease pattern required for document retention and erasure.

### 2.2 `NVIDIA-AI-Blueprints/rag` Audit (`v2.6.x`, commit `29905d8`)
* **Architecture Reality:** A $41,500$-line showcase product (`rag_server`, `ingestor_server`, `nv-ingest`, Redis, Elasticsearch/Milvus, SeaweedFS/MinIO, and NIM fleet) requiring $3 \times \text{H100/B200}$ GPUs in Docker or $8 \times \text{H100}$ GPUs in Helm ($\sim 200\text{ GB}$ disk) for its default self-hosted profile.
* **Critical Security Flaws for Neuron Integration:**
  1. **Zero Authentication/Authorization:** The servers read `Authorization: Bearer` and blindly forward it as `vdb_auth_token`, while accepting `vdb_endpoint` as a per-request parameter.
  2. **Unsafe Access Control Pattern:** Uses an LLM filter-expression generator for metadata filtering, which is unsafe as a tenant security boundary.
  3. **Non-Durable Ingestion Jobs:** `ingestor_server/task_handler.py` uses in-process `asyncio.create_task` with Redis storing only status strings; if the process restarts, active ingestion jobs vanish.
  4. **Hard-Wired Inference Clients:** `utils/embedding.py` and `utils/reranker.py` only accept `model_engine == "nvidia-ai-endpoints"` (`NVIDIAEmbeddings` and `NVIDIARerank`).

---

## 3. Consolidated Open-Source Ecosystem Decisions

Filtering the $60+$ repositories evaluated across the three reports against license safety (no AGPL/GPL in core), PyPI maintenance health (no packages stalled in 2025), and architectural fit yields the final adoption matrix:

| Capability | Adopted Package / Service | Version & License | Integration Classification | Rejected Alternatives & Why |
| :--- | :--- | :--- | :--- | :--- |
| **Vector & Lexical Store** | **`pgvector`** + **`pgvector-python`** + **Postgres FTS (`tsvector`)** | `0.8.0+` / `0.5.1` (PostgreSQL / MIT) | **A/C. Adopt in Existing Postgres** | **Milvus / Weaviate / Elasticsearch** (operational bloat for $<10\text{M}$ chunks); **ParadeDB `pg_search`** (AGPL-3.0 license). |
| **BM25 Upgrade (Phase 2)** | **`pg_textsearch`** (Timescale) | `v1.0` (PostgreSQL License) | **A. Optional PG Extension** | **ParadeDB `pg_search`** (AGPL-3.0). |
| **Document Parsing & Chunking** | **`docling-serve`** (HTTP sidecar) + **`docling-core`** (`HybridChunker`) | `1.38.2` / `2.145.0` (MIT) | **B. Sidecar Service** + **C. Worker Library** | **PyMuPDF** (AGPL-3.0); **MinerU** (Custom license/AGPL); **Marker** (GPL code / restricted weights); **Unstructured** (heavy deps). |
| **Durable Job Queue** | **`Procrastinate`** | `3.10.0` (MIT) | **A/C. Embed on Existing Postgres** | **Celery / Dramatiq / arq** (requires Redis/RabbitMQ; Dramatiq is LGPL); **Temporal / Prefect** (premature cluster overhead). |
| **Embeddings & Reranking** | **`langchain-nvidia-ai-endpoints`**, **`langchain-openai`**, **`TEI`**, **`fastembed`** | `fastembed 0.9.1` / `TEI` (Apache-2.0 / MIT) | **C. Provider Protocol** + **A. Optional Sidecar** | **`FlashRank`** (`0.2.10`, stale since Jan 2025). |
| **Tabular Data Analysis** | **`DuckDB`** + **`sqlglot`** | `2.0.0` / `30.27.0` (MIT) | **C. Embed Read-Only in Worker/API** | **Vanna** (unbounded text-to-SQL); **In-process Python `exec()`** (unsafe). |
| **Web Extraction** | **`Trafilatura`** (default) + **`Crawl4AI`** (JS fallback) | `2.3.1` / `0.9.5` (Apache-2.0) | **C. Embed in Worker** | **Firecrawl Self-Hosted** (AGPL-3.0 server license). |
| **Repository Intelligence** | **`tree-sitter-language-pack`** + **`GitHub MCP Server`** | `1.22.1` (MIT) | **C. Embed in Worker** + **B. MCP Connector** | Naive character splitters (destroy AST boundaries). |
| **Evaluation & Red-Teaming** | **Neuron `evaluation.py`** + **`Inspect AI` / `Promptfoo`** + optional **`Ragas` / `DeepEval`** | `Inspect AI 0.3.287` / `DeepEval 4.3.2` (MIT / Apache-2.0) | **C. Dev/CI Harness** | **Arize Phoenix Server** (Elastic-2.0 license; redundant with LangSmith + OTel). |

---

## 4. Uncovered Gaps & Collaborative Architectural Improvements

Synthesizing the deepest technical findings across all three reports resolved six subtle engineering gaps:

1. **Solving Filtered HNSW Starvation with `halfvec` + Iterative Scans + RLS Reset:**
   * *The Problem:* Pre-retrieval SQL filtering (`kb_id = ANY(...)`) and Postgres Row-Level Security (RLS) are mandatory, but HNSW indexes with selective filters can return fewer than $k$ rows, and RLS `SET LOCAL` session variables can leak across pooled connections if misconfigured.
   * *The Combined Solution:* Store embeddings as **`halfvec(N)`** (cutting HNSW RAM usage by $50\%$), set **`SET LOCAL hnsw.iterative_scan = relaxed_order`** alongside **`SET LOCAL neuron.kb_ids = ...`** inside an explicit `psycopg` transaction block (`async with conn.transaction():`) so settings automatically vanish on transaction commit/rollback, and fall back to exact distance scans when a KB has fewer than $1,000$ chunks.
2. **Bridging ADR 0005 Ephemeral Tool Messages with Bounding-Box Citations:**
   * *The Problem:* Users need rich page and bounding-box (`bbox`) citations with immutable `excerpt_hash` verification, but Neuron discards intermediate tool messages at the end of `call_agent` (ADR 0005).
   * *The Combined Solution:* `DoclingServeParser` extracts `page_start`, `page_end`, `headings`, and `locator_json` (bounding boxes) into `neuron_kb_chunks`. During a run, `search_knowledge` mints an opaque per-run `cite_id`. In `graphs/main_graph.py`, `_final_answer` validates `AgentAnswer.citations` against the run's in-memory tool messages, drops hallucinated IDs, and stamps the resolved citation objects (including `excerpt_hash` and `locator_json`) into `AIMessage.additional_kwargs["citations"]`.
3. **Zero-Tombstone Latency on Deletion & Permission Revocation:**
   * *The Problem:* Asynchronous blob/chunk deletion via `Procrastinate` leaves a window where deleted documents still exist in `neuron_kb_chunks`.
   * *The Combined Solution:* Combine `status = 'deleting'` and the `Procrastinate` purge job with an immediate tombstone predicate (`d.status = 'ready' AND d.deleted_at IS NULL AND kb.deleted_at IS NULL`) joined directly into the retrieval query and the `/chunks/{chunk_id}` citation preview endpoint.
4. **Out-of-Process Parsing with Byte-Pushing (Zero Parser Network Access):**
   * *The Problem:* Document parsers must run in a network-disabled container so malicious PDFs cannot trigger SSRF or phone home.
   * *The Combined Solution:* Deploy `docling-serve` on an internal-only Docker network (`internal: true`, zero egress) and have `neuron-worker` push raw file bytes to `docling-serve` (never passing external URLs for the parser to fetch).
5. **Safe Tabular Analytics Without Code Execution (Phase 4):**
   * *The Problem:* Tabular CSV/XLSX analysis is high-value, but Neuron deliberately avoids arbitrary code execution until Phase 5.
   * *The Combined Solution:* Pair `DuckDB` (`enable_external_access=false`, `memory_limit='256MB'`, $5\text{-second}$ timeout) with **`sqlglot`** AST validation to enforce single-statement `SELECT`-only queries over user-uploaded CSV/XLSX/Parquet files in Phase 4, deferring microVM sandboxes (`E2B`/`gVisor`) to Phase 5.
6. **Subgraph Escalation Only When Triggered:**
   * *The Problem:* Heavy multi-agent planners add latency and failure modes to simple knowledge lookups.
   * *The Combined Solution:* Keep `search_knowledge`, `get_document_excerpt`, and `list_knowledge_bases` as standard LangChain `@tool` functions inside `create_agent` for $90\%+$ of turns. Introduce bounded LangGraph subgraphs (`max_iterations=4`) only in Phase 4 for explicit deep-research runs, gated by evaluation benchmarks proving a quality gain over the standard agent loop.

---

## 5. Final Optimized RAG & Knowledge Architecture

### 5.1 Unified System Architecture Diagram

```mermaid
flowchart TB
  subgraph Client["React 19 SPA (web/)"]
    ChatUI["Chat & SSE Stream (contract.json v1)"]
    KBUI["Knowledge Screen (Upload, Status, Grants)"]
    CiteSheet["Citation Chips & Bounding-Box Preview Sheet"]
  end

  subgraph FastAPI["Neuron API Process (src/neuron_agent/)"]
    Auth["TokenVerifier (OIDC/JWKS) -> Principal(owner_key, roles, scopes)"]
    AgentSvc["AgentService & ToolAuthorizationMiddleware"]
    KRoutes["/v1/knowledge/* Routes (Multipart Upload, Search, Preview, Grants)"]
    
    subgraph LangGraph["LangGraph Runtime (main_graph.py)"]
      AgentNode["create_agent + HumanInTheLoopMiddleware(batched)"]
      FinalNode["_final_answer (Validates cite_ids -> Stamps AIMessage.additional_kwargs)"]
      KTools["Knowledge Tools (search_knowledge, get_document_excerpt, list_kbs, query_table)\n[ToolSpec: taints_run=True]"]
    end

    subgraph KModule["Knowledge Engine Module (neuron_agent/knowledge/)"]
      KSvc["KnowledgeService (Quota, Tombstones, Grant Resolution)"]
      Retr["HybridRetriever (Dense halfvec + FTS tsvector + SQL RRF)"]
      Prov["Provider Interfaces (EmbeddingProvider, Reranker)"]
    end
  end

  subgraph Worker["Durable Worker Process (neuron-worker, Same Image)"]
    ProcWorker["Procrastinate Worker (ingest_document, delete_document, reindex_kb)"]
    Chunker["docling-core HybridChunker + tree-sitter AST Chunker"]
  end

  subgraph Storage["Neuron Persistence (Existing Postgres + BlobStore)"]
    PG[("PostgreSQL 16 (pgvector/pgvector:pg16)\n- Checkpoints, Store, Leases, Ledger\n- neuron_kb, grants, documents, chunks (halfvec + tsvector)\n- RLS Policy (neuron.kb_ids) + Procrastinate Queue")]
    Blob[("BlobStore (S3 / SeaweedFS / Local Volume)\nEncrypted Raw Files (Random Keys)")]
  end

  subgraph External["Stateless Isolated Services (Profile-Dependent)"]
    Docling["docling-serve Container (CPU Default, No Egress)\n[Optional GPU: NV-Ingest]"]
    Models["Model Endpoints\n- Lean: NVIDIA API Catalog / OpenAI\n- Self-Hosted: HF TEI / vLLM / NIM + fastembed CPU"]
  end

  ChatUI & KBUI & CiteSheet <-->|OIDC Bearer / SSE| Auth
  Auth --> AgentSvc & KRoutes
  AgentSvc --> AgentNode --> KTools --> KSvc
  AgentNode --> FinalNode --> ChatUI
  KRoutes --> KSvc
  KSvc --> Retr & Blob
  Retr <-->|Single SQL Tx: SET LOCAL kb_ids + iterative_scan| PG
  Retr <--> Prov <--> Models
  KSvc -->|Defer Job in Same DB Tx| PG
  PG <-->|Row Locks & Retries| ProcWorker
  ProcWorker <--> Blob
  ProcWorker -->|Push File Bytes (HTTP)| Docling
  Docling -->|DoclingDocument JSON (with bbox)| Chunker
  Chunker --> Prov
  Chunker -->|Idempotent Write by (doc_id, index_version)| PG
```

### 5.2 Proposed Module Layout & File Changes

#### New Neuron Modules (`src/neuron_agent/`)
| Module | Responsibility |
| :--- | :--- |
| `knowledge/models.py` | Pydantic models: `KnowledgeBase`, `Document`, `Chunk`, `Citation`, `SearchResult` |
| `knowledge/repository.py` | `psycopg` 3 queries for KBs, documents, chunks, grants, tombstones (no ORM) |
| `knowledge/service.py` | `KnowledgeService`: CRUD, quotas, `allowed_kbs(ctx)`, `search(ctx, ...)` |
| `knowledge/retrieval.py` | Dense `halfvec`, `tsvector` FTS, and SQL RRF queries; reranking orchestration |
| `knowledge/providers.py` | `EmbeddingProvider`, `Reranker` protocols + `nvidia`, `tei`, `openai`, `fastembed`, `fake` |
| `knowledge/parsing.py` | `DocumentParser` protocol + `DoclingServeParser`, `NvIngestParser`, `PlainTextParser` |
| `knowledge/blobs.py` | `BlobStore` protocol + `S3BlobStore`, `LocalBlobStore` |
| `knowledge/jobs.py` | `Procrastinate` app and `ingest_document`, `delete_document`, `reindex_kb` tasks |
| `knowledge/tools.py` | `knowledge_specs(service)` returning `ToolSpec`s (mirrors `memory/tools.py`) |
| `knowledge/citations.py` | Per-run `cite_id` minting and validation against run tool messages |
| `worker/main.py` | `neuron-worker` entrypoint |

#### Existing Neuron Files to Modify
| File | Change |
| :--- | :--- |
| `security/auth.py` | `Principal` retains `roles` (and optional `groups` claim) from verified JWT |
| `security/authorization.py` | `AuthorizationContext` gains `roles`; add scopes `knowledge:read`, `knowledge:write`, `knowledge:admin`, `tools:search_knowledge` |
| `services/agent_service.py` | `_compose_tools()` registers `knowledge_specs()` when `APP_KNOWLEDGE_ENABLED=true` |
| `schemas/agent.py` | Add optional `citations` to `AgentAnswer`, `AgentResponse`, and `ThreadMessage`; add optional `knowledge_base_ids` to `AgentRequest` |
| `graphs/main_graph.py` | `_final_answer` validates citations against run tool messages and stamps `AIMessage.additional_kwargs["citations"]` |
| `persistence/migrations.py` | Add knowledge migrations, app-role table grants, and RLS policies |
| `config/settings.py` | Add `APP_KNOWLEDGE_*`, `APP_EMBEDDING_MODEL`, and `APP_RERANK_MODEL` settings |
| `observability/semconv.py`, `metrics.py` | Add `knowledge.search` and `knowledge.ingest.*` spans and metrics (counts/IDs only) |
| `api/main.py` | Mount `/v1/knowledge/*` routes with dedicated multipart upload size limits |

### 5.3 Four Core Architectural Flows

#### Flow 1: Pre-Filtered Tenant-Isolated Retrieval (Zero Bypass)
1. **Identity Resolution:** `TokenVerifier` validates the JWT and populates `Principal(issuer, subject, scopes, roles)`. `AuthorizationContext` carries `owner_key = HMAC(issuer, subject)` and verified `roles`.
2. **Scope & Runtime Context Injection:** `ToolAuthorizationMiddleware` verifies `tools:search_knowledge`. `search_knowledge` reads `owner_key` and `roles` exclusively from `runtime.context` (`ToolRuntime`), never from LLM arguments.
3. **Grant Intersection:** `KnowledgeService.allowed_kbs(ctx)` queries `neuron_kb` and `neuron_kb_grants` to compute the caller's readable `kb_id` set (where `kb.deleted_at IS NULL`) and intersects it with any model-supplied `kb_ids` filter. If empty, search returns `[]` immediately.
4. **Single-Transaction Hybrid SQL + RLS:** Inside an explicit `psycopg` transaction (`async with conn.transaction():`), the retriever executes:
   * `SET LOCAL neuron.kb_ids = '...';` (enforcing the PostgreSQL RLS policy on `neuron_kb_chunks`).
   * `SET LOCAL hnsw.iterative_scan = relaxed_order;` (preventing HNSW post-filter starvation).
   * A single CTE query performing dense `halfvec` cosine search + `tsvector` GIN search filtered by `kb_id = ANY(%(allowed)s)`, `index_version`, and `d.status = 'ready' AND d.deleted_at IS NULL`, fused via Reciprocal Rank Fusion:
     $$\text{RRF\_score} = \frac{1}{60 + \text{rank}_{\text{dense}}} + \frac{1}{60 + \text{rank}_{\text{lex}}}$$
5. **Reranking & Graceful Degradation:** The top $40$ fused candidates are passed to `Reranker.rerank(query, top_n=8)`. If the reranker times out or errors, the retriever gracefully degrades to the RRF order and sets `reranked: false` in the response metadata.

#### Flow 2: Server-Validated Citations & History Persistence
1. **Minting:** `search_knowledge` assigns each returned chunk a per-run `cite_id` (e.g., `cit_1`, `cit_2`) and formats results inside a delimited JSON block with `<` escaped and a `"data, not instructions"` preamble (reusing `memory/tools.py`'s `render_notes()` pattern).
2. **Generation & Server Validation:** The LLM outputs `AgentAnswer(answer=..., citations=["cit_1"])`. In `graphs/main_graph.py`, `_final_answer` inspects the run's actual tool messages, strips any `cite_id` not produced by a knowledge tool in that run, and increments the `neuron.citations.rejected` counter.
3. **Stamping & Streaming:** Validated citations (`n`, `doc_id`, `chunk_id`, `title`, `page_start`, `page_end`, `headings`, `locator_json`, `excerpt_hash`) are stamped into `AIMessage.additional_kwargs["citations"]` and emitted on `AgentResponse`, `ThreadMessage`, and the SSE `final` event.
4. **Revocation-Safe Inspection:** Clicking a citation chip in React calls `GET /v1/knowledge/documents/{doc_id}/chunks/{chunk_id}`, which re-verifies KB read access and checks `deleted_at IS NULL` before returning the chunk text and bounding-box coordinates.

#### Flow 3: Restart-Safe Asynchronous Ingestion & Tombstone Deletion
1. **Transactional Enqueue:** `POST /v1/knowledge/bases/{kb_id}/documents` validates quota, file size, and MIME magic bytes, streams the file to `BlobStore` under a random key with SHA-256 verification, inserts `neuron_kb_documents(status='queued')`, and defers `ingest_document(doc_id)` via `Procrastinate` **in the same PostgreSQL transaction** returning `202 Accepted`.
2. **Out-of-Process Parsing & Idempotent Write:** `neuron-worker` claims the job via Postgres row lock, pushes the file bytes to `docling-serve` with a strict timeout, validates the returned `DoclingDocument` JSON schema, chunks via `docling-core` `HybridChunker`, embeds in batches, and replaces chunks for `(doc_id, index_version)` in a single transaction before marking `status='ready'`.
3. **Tombstone-First Deletion:** `DELETE /v1/knowledge/documents/{doc_id}` immediately sets `status='deleting'` and `deleted_at=now()` (instantly hiding the document from all queries) and enqueues `delete_document(doc_id)` to purge chunks and the `BlobStore` object asynchronously. `DELETE /v1/me/knowledge` extends user data erasure (`UserDataErasureResponse.complete`) to all owned KBs, blobs, and queued jobs.

#### Flow 4: Indirect Prompt Injection Defense-in-Depth
1. **Deterministic Taint Gate:** All retrieval and web tools set `ToolSpec(taints_run=True)`. Once a run reads retrieved chunks, Neuron's existing security amendment R2 automatically gates any subsequent MCP or outbound tool call behind human-in-the-loop approval.
2. **Strict Context Framing & Zero Auto-Ingestion:** Retrieved chunks are escaped and framed as untrusted data; model output is never auto-ingested into knowledge bases or memory without explicit user approval (`save_to_knowledge` is `risk="mutating"`, `approval=always`).
3. **Telemetry Redaction:** OpenTelemetry spans (`knowledge.search`, `knowledge.ingest.*`) and structlog entries record only IDs, counts, latencies, and error codes—never raw chunk text, queries, or filenames.

---

## 6. Unified Database Schema, API & Tool Contracts

### 6.1 PostgreSQL Migration DDL (`persistence/migrations.py`)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE neuron_kb (
  kb_id            uuid PRIMARY KEY,
  owner_key        text NOT NULL,              -- HMAC(issuer, subject) of creator
  name             text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 80),
  visibility       text NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'shared')),
  embedding_model  text NOT NULL,              -- e.g. 'nvidia:nvidia/llama-nemotron-embed-1b-v2'
  embedding_dim    int  NOT NULL DEFAULT 2048,
  chunker_version  text NOT NULL DEFAULT 'docling-hybrid-v1',
  index_version    int  NOT NULL DEFAULT 1,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  deleted_at       timestamptz
);

CREATE TABLE neuron_kb_grants (
  kb_id            uuid NOT NULL REFERENCES neuron_kb(kb_id) ON DELETE CASCADE,
  subject_type     text NOT NULL CHECK (subject_type IN ('owner', 'role')),
  subject          text NOT NULL,              -- HMAC owner_key or JWT role name
  access           text NOT NULL CHECK (access IN ('read', 'write', 'admin')),
  granted_by       text NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (kb_id, subject_type, subject)
);

CREATE TABLE neuron_kb_documents (
  doc_id           uuid PRIMARY KEY,
  kb_id            uuid NOT NULL REFERENCES neuron_kb(kb_id) ON DELETE CASCADE,
  uploaded_by      text NOT NULL,              -- HMAC owner_key
  title            text NOT NULL,
  mime_type        text NOT NULL,
  size_bytes       bigint NOT NULL CHECK (size_bytes >= 0),
  sha256           char(64) NOT NULL,
  blob_key         text NOT NULL,
  source_type      text NOT NULL DEFAULT 'upload' CHECK (source_type IN ('upload', 'github', 'web')),
  source_ref       text,                       -- Validated URL or repo@commit_sha
  parser_version   text,
  status           text NOT NULL CHECK (status IN ('queued', 'parsing', 'embedding', 'ready', 'failed', 'deleting')),
  error_code       text,
  page_count       int,
  chunk_count      int,
  index_version    int  NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  deleted_at       timestamptz,
  UNIQUE (kb_id, sha256)
);

CREATE TABLE neuron_kb_chunks (
  chunk_id         uuid PRIMARY KEY,
  doc_id           uuid NOT NULL REFERENCES neuron_kb_documents(doc_id) ON DELETE CASCADE,
  kb_id            uuid NOT NULL,              -- Denormalized for pre-retrieval filter & RLS
  index_version    int  NOT NULL,
  ordinal          int  NOT NULL,
  text             text NOT NULL,
  content_hash     char(64) NOT NULL,
  headings         text[] NOT NULL DEFAULT '{}',
  page_start       int,
  page_end         int,
  locator_json     jsonb NOT NULL DEFAULT '{}'::jsonb, -- Bounding boxes (bbox) / AST line spans
  token_count      int  NOT NULL,
  embedding        halfvec(2048) NOT NULL,     -- FP16 halfvec cuts HNSW memory by 50%
  tsv              tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED,
  UNIQUE (doc_id, ordinal, index_version)
);

CREATE INDEX CONCURRENTLY neuron_kb_chunks_hnsw_idx
  ON neuron_kb_chunks USING hnsw (embedding halfvec_cosine_ops);
CREATE INDEX CONCURRENTLY neuron_kb_chunks_tsv_idx
  ON neuron_kb_chunks USING gin (tsv);
CREATE INDEX CONCURRENTLY neuron_kb_chunks_kb_ver_idx
  ON neuron_kb_chunks (kb_id, index_version);
CREATE INDEX CONCURRENTLY neuron_kb_docs_active_idx
  ON neuron_kb_documents (kb_id, status) WHERE deleted_at IS NULL;

ALTER TABLE neuron_kb_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE neuron_kb_chunks FORCE ROW LEVEL SECURITY;
CREATE POLICY kb_isolation_policy ON neuron_kb_chunks
  USING (kb_id = ANY (string_to_array(current_setting('neuron.kb_ids', true), ',')::uuid[]));
```

### 6.2 REST API & SSE Contract (`api/main.py`)
All routes enforce `extra="forbid"` on request bodies and return identical `404 Not Found` responses for missing, deleted, or unauthorized resources to prevent ID enumeration:

* `GET /v1/knowledge/bases` (`knowledge:read`) & `POST /v1/knowledge/bases` (`knowledge:write`).
* `PATCH /v1/knowledge/bases/{kb_id}` & `DELETE /v1/knowledge/bases/{kb_id}` (`knowledge:admin` + KB admin, tombstones immediately and schedules async purge).
* `PUT /v1/knowledge/bases/{kb_id}/grants` (`knowledge:admin` + KB admin, replaces role grants and logs an audit event).
* `POST /v1/knowledge/bases/{kb_id}/documents` (`knowledge:write` + KB write, multipart upload with `Idempotency-Key` $\rightarrow$ `202 Accepted` with document record).
* `GET /v1/knowledge/bases/{kb_id}/documents` & `GET /v1/knowledge/documents/{doc_id}` (KB read, returns ingestion stage and status).
* `DELETE /v1/knowledge/documents/{doc_id}` (KB write $\rightarrow$ `202 Accepted`, sets `status='deleting'` and `deleted_at=now()`).
* `GET /v1/knowledge/documents/{doc_id}/chunks/{chunk_id}` (KB read, live permission + tombstone check for citation preview sheet, returns text + `locator_json` bbox).
* `GET /v1/knowledge/documents/{doc_id}/file` (KB read, serves raw file with `Content-Disposition: attachment`).
* `POST /v1/knowledge/search` (`knowledge:read`, direct retrieval endpoint for UI and evaluation runner).
* `DELETE /v1/me/knowledge` (`threads:delete`, full GDPR/user erasure of owned KBs, blobs, chunks, and jobs).
* **SSE `final` Event & `AgentResponse` Extension (Additive, Protocol v1 Compatible):**
  ```json
  {
    "status": "completed",
    "answer": "The termination notice period is 60 days [1].",
    "used_tools": ["search_knowledge"],
    "citations": [
      {
        "n": 1,
        "doc_id": "a41b8c90-...",
        "chunk_id": "f09c12d4-...",
        "title": "Employment_Contract_2025.pdf",
        "headings": ["7. Termination"],
        "page_start": 4,
        "page_end": 4,
        "locator_json": {"bbox": [72.0, 140.5, 520.0, 210.0]},
        "excerpt_hash": "sha256:9f86d081..."
      }
    ]
  }
  ```

### 6.3 Governed Agent Tool Specifications (`knowledge/tools.py`)

| Tool Name | Model Arguments | Scope | Risk Class | HITL Approval | `taints_run` | Hard Limits |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `list_knowledge_bases` | None | `tools:search_knowledge` | `read` | No | `False` | Max $50$ KBs returned. |
| `search_knowledge` | `query: str (<=500)`, `kb_ids?: list[UUID] (<=10)`, `limit?: int (<=10)` | `tools:search_knowledge` | `read` | No | **`True`** | Max $10$ chunks, $6,000$ chars total, max $5$ calls/run. |
| `get_document_excerpt` | `cite_id: str`, `window?: int (<=2)` | `tools:search_knowledge` | `read` | No | **`True`** | Only accepts `cite_id`s minted in the current run. |
| `get_document_metadata` | `doc_id: UUID` | `tools:search_knowledge` | `read` | No | `False` | Returns title, pages, status, source only. |
| `query_table` *(Phase 4)* | `doc_id: UUID`, `sql: str` | `tools:query_table` | `read` | No | **`True`** | `sqlglot` verified single `SELECT`; DuckDB $5\text{ s}$ / $256\text{ MB}$ / $200$ rows cap. |
| `search_repository` *(Phase 4)* | `repo_kb_id: UUID`, `query: str`, `path_glob?: str` | `tools:search_repository` | `read` | No | **`True`** | Same bounds as `search_knowledge`; returns commit SHA & line spans. |
| `research_web` *(Phase 4)* | `question: str`, `max_pages: int (<=5)` | `tools:research_web` | `read` (outbound) | **Yes (if run already tainted)** | **`True`** | HTTPS-only, `validate_safe_url` (#364/#366), $1\text{ MB}$/page cap. |
| `save_to_knowledge` *(Phase 4)* | `kb_id: UUID`, `title: str`, `content_or_url: str` | `tools:save_to_knowledge` | **`mutating`** | **Always** | `False` | Enforces per-owner storage and page quotas. |

---

## 7. Phased Roadmap, Backlog, Build-vs-Buy Savings & Final ADRs

### 7.1 Consolidated Implementation Roadmap

| Phase | Timeline & Effort | Core Deliverables | Security & Quality Acceptance Gates |
| :--- | :--- | :--- | :--- |
| **Phase 0: Readiness & Freeze Work** | **2–3 Engineer-Weeks** *(During `v1.0.0` Freeze)* | Write **ADR 0014**; close Neuron issues **#364 (SSRF)**, **#366 (HTTPS)**, and **#370 (MCP crashes)**; run off-main benchmark spike (`docling-serve` + `pgvector` `halfvec` on $50$ representative PDFs/DOCX files). | ADR 0014 signed off; SSRF & MCP test suites green; baseline recall@5, MRR, and ingestion latency/page recorded. |
| **Phase 1: Knowledge Foundation (MVP)** | **5–7 Engineer-Weeks** *(Post-`v1.0.0`)* | Private KBs, multipart upload (`BlobStore`), `Procrastinate` worker (`neuron-worker`), `docling-serve` adapter, `halfvec` dense search, `search_knowledge` tool, `_final_answer` citation validation & stamping, React `KnowledgeScreen` & citation drawer, GDPR erasure/export. | **$0\%$ cross-user leakage** in CI security tests; killed worker recovers job automatically; $\ge 95\%$ valid citations on $30$-question golden set; poisoned-PDF dataset v6 triggers zero unapproved outbound tools. |
| **Phase 2: Hybrid Search, Reranking & Sharing** | **4–5 Engineer-Weeks** | `tsvector` GIN + SQL RRF hybrid search (and optional `pg_textsearch` BM25 evaluation), `Reranker` (`nvidia`, `TEI`, `fastembed`), `Principal` role retention, `neuron_kb_grants` shared KBs, blue-green `index_version` re-index job, Locust load test. | Hybrid + rerank measurably beats Phase 1 dense recall@5/MRR on golden dataset; role revocation blocks retrieval and citation preview on very next query. |
| **Phase 3: External Knowledge Connectors** | **4–6 Engineer-Weeks** | GitHub repo sync job with `tree-sitter` AST chunking, SSRF-safe web page ingestion (`Trafilatura` / `Crawl4AI`), pinned MCP doc connectors, `openai_compatible` base URL provider for vLLM/SGLang. | Private IP/redirect URLs rejected; indexed code chunks cite exact file path, commit SHA, and line range. |
| **Phase 4: Specialized Agent Capabilities** | **6–8 Engineer-Weeks** | `query_table` (`DuckDB` + `sqlglot` read-only analytics), `research_web` + `save_to_knowledge` (HITL gated), `search_repository`, optional bounded LangGraph retrieval/research subgraphs. | Non-`SELECT` SQL statements rejected by `sqlglot`; `save_to_knowledge` always triggers HITL interrupt; subgraphs kept only if evals beat single-agent loop. |
| **Phase 5: Enterprise Scale & Advanced Platform** | **8–12 Engineer-Weeks** | Semantic recall over user memory (`AsyncPostgresStore` `pgvector` index), microVM sandboxed Python plotting (`E2B`/`gVisor`), `Qdrant` adapter if chunks exceed $10\text{M}\text{--}50\text{M}$, `LightRAG` / `Graphiti` evaluation. | Sandbox escape red-team suite passes; external vector DB or GraphRAG adopted only upon benchmark threshold proof. |

### 7.2 Prioritized Engineering Backlog (Phases 0–2)

| ID | Title & Description | Pri | Depends | Reused Packages | Neuron Modules | Est. | Acceptance Criteria |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **KN-001** | ADR 0014: Knowledge Engine scope, product requirements, storage & security boundaries | P0 | — | — | `docs/decisions/` | 0.5 w | Accepted by maintainer; defines datasets and recall/latency targets. |
| **KN-002** | Close SSRF and HTTPS-only outbound fetch issues | P0 | #364, #366 | — | `security/` | 1.0 w | Security suite passes private IP, DNS rebinding, and redirect cases. |
| **KN-003** | Handle MCP transport exceptions gracefully | P0 | #370 | `mcp` | `tools/mcp/client.py` | 0.5 w | Dropped MCP transport yields a structured tool error, not a run crash. |
| **KN-004** | Benchmark spike: `docling-serve` + `pgvector` `halfvec` on $50$ real documents | P0 | KN-001 | `docling-serve`, `pgvector` | Spike branch only | 1.0 w | Recall@5, ingest latency/page, and memory footprint recorded. |
| **KN-010** | `pgvector` Docker image, extension migration, and startup readiness check | P0 | KN-001 | `pgvector` | `persistence/migrations.py`, `startup_checks.py` | 0.5 w | `neuron-agent setup` enables `vector`; readiness fails cleanly if missing. |
| **KN-011** | Knowledge tables, app-role grants, tombstone indexes, and RLS policy | P0 | KN-010 | — | `persistence/migrations.py`, `roles.py` | 1.0 w | Role grant tests pass; RLS blocks rows outside `neuron.kb_ids`. |
| **KN-012** | `BlobStore` protocol (`LocalBlobStore` + `S3BlobStore`) with SHA-256 verification | P0 | KN-001 | S3 client | `knowledge/blobs.py` | 0.5 w | Random object keys; idempotent deletes; zero path traversal. |
| **KN-013** | `Procrastinate` app wiring, `neuron-worker` entrypoint, and graceful drain | P0 | KN-011 | `procrastinate` | `knowledge/jobs.py`, `worker/main.py` | 1.0 w | Killed worker's locked job is recovered and completed upon restart. |
| **KN-014** | `DocumentParser` protocol + `DoclingServeParser` (byte-push, no egress) | P0 | KN-013 | `docling-serve`, `docling-core` | `knowledge/parsing.py` | 1.0 w | Enforces timeouts, page/byte caps, and schema validation; recorded fake for CI. |
| **KN-015** | `EmbeddingProvider` (`nvidia`, `openai_compatible`, `fake`) | P0 | KN-001 | `langchain-nvidia-ai-endpoints`, `langchain-openai` | `knowledge/providers.py`, `settings.py` | 0.5 w | Batched embedding with provider retry classification and dimension checks. |
| **KN-016** | Durable ingestion task: parse $\rightarrow$ `HybridChunker` $\rightarrow$ embed $\rightarrow$ transactional write | P0 | KN-013–015 | `docling-core` | `knowledge/jobs.py` | 1.0 w | Idempotent replacement by `(doc_id, index_version)`; stage transitions verified. |
| **KN-017** | `/v1/knowledge/*` API routes, multipart upload limits, and tombstone deletes | P0 | KN-011, 012, 016 | — | `api/main.py`, `knowledge/service.py` | 1.0 w | Foreign/deleted IDs return `404`; tombstones take effect immediately. |
| **KN-018** | Dense `halfvec` retrieval with pre-filter SQL, RLS, and `iterative_scan` | P0 | KN-011, 015 | `pgvector` | `knowledge/retrieval.py` | 0.5 w | Adversarial multi-user test confirms $0\%$ cross-user leakage. |
| **KN-019** | Knowledge tools (`search_knowledge`, `get_document_excerpt`, `list_kbs`) + `taints_run=True` | P0 | KN-018 | LangChain tools | `knowledge/tools.py`, `agent_service.py` | 1.0 w | Tools require scope; outbound MCP tools require HITL approval after search. |
| **KN-020** | Server-side `cite_id` validation, `AIMessage.additional_kwargs` stamping, SSE `citations` | P0 | KN-019 | — | `knowledge/citations.py`, `main_graph.py`, `schemas/agent.py` | 1.0 w | Hallucinated `cite_id`s dropped and counted; reloaded threads preserve citations. |
| **KN-021** | React `KnowledgeScreen`, upload dropzone, status polling, and citation preview sheet | P0 | KN-017, 020 | `shadcn/ui` | `web/src/features/knowledge`, `features/chat` | 1.5 w | Playwright E2E flow (upload $\rightarrow$ ask $\rightarrow$ open citation bbox preview) passes. |
| **KN-022** | Extend `/v1/me` export and erasure to knowledge bases, blobs, chunks, and jobs | P0 | KN-017 | — | `agent_service.py`, `features/data` | 0.5 w | `DELETE /v1/me/knowledge` removes all user blobs, chunks, and queued tasks. |
| **KN-023** | Retrieval & citation eval harness + poisoned-document security dataset v6 | P0 | KN-020 | — | `evaluation.py`, `tests/fixtures/` | 1.0 w | CI gates on recall@5, citation precision, and zero injection bypasses. |
| **KN-030** | `tsvector` GIN + SQL Reciprocal Rank Fusion (RRF) hybrid search | P1 | KN-018 | Postgres FTS | `knowledge/retrieval.py` | 0.5 w | Hybrid retrieval measurably improves recall@5/MRR over dense baseline. |
| **KN-031** | `Reranker` protocol (`nvidia`, `TEI`, `fastembed`, `none`) with fallback | P1 | KN-030 | `langchain-nvidia-ai-endpoints`, `TEI`, `fastembed` | `knowledge/providers.py` | 0.5 w | Reranker timeout degrades cleanly to RRF order with `reranked: false`. |
| **KN-032** | Retain verified JWT `roles` in `Principal` and `AuthorizationContext` | P1 | — | — | `security/auth.py`, `authorization.py` | 0.5 w | Spoofed/unconfigured issuer claims rejected in unit and security tests. |
| **KN-033** | Shared KBs (`neuron_kb_grants`) API and React grants editor | P1 | KN-032 | — | `knowledge/service.py`, `web/src/features/knowledge` | 1.0 w | Role revocation denies search and citation preview on the very next request. |
| **KN-034** | Blue-green `reindex_kb` background job for embedding model upgrades | P1 | KN-016 | `procrastinate` | `knowledge/jobs.py` | 0.5 w | Searches continue on old `index_version` until new version completes and swaps. |
| **KN-035** | Locust load test for concurrent ingestion and filtered hybrid search | P1 | KN-030, 031 | `locust` | `loadtest/` | 0.5 w | p50/p95 retrieval latency and ingestion throughput recorded on reference stack. |

### 7.3 Reconciled Build-vs-Buy Effort Savings
Composing `pgvector`, `docling-serve` + `docling-core`, `Procrastinate`, `TEI`/`fastembed`/`NVIDIA NIM`, `DuckDB` + `sqlglot`, `Trafilatura`/`Crawl4AI`, and `tree-sitter` requires writing **$\sim 3,000\text{--}4,000$ lines of Neuron domain, security, and UI code** (taking **$11\text{--}15$ engineer-weeks** through Phase 2, and **$22\text{--}38$ engineer-weeks** through Phase 4), compared to **$40\text{--}70$ engineer-weeks** to build layout parsing, durable queues, ANN indexing, and AST splitters in-house—yielding a net engineering savings of **$25\text{--}40$ engineer-weeks** while keeping the default deployment at **$0$ GPUs** and adding only two CPU containers (`neuron-worker` and `docling-serve`).

### 7.4 Final Architecture Decision Records (ADRs)
* **ADR-0014 (Knowledge Engine Boundary):** Implement `neuron_agent.knowledge` in-process on Neuron's existing PostgreSQL (`pgvector` `halfvec` + `tsvector` FTS) using `psycopg` 3 and transactional RLS (`SET LOCAL neuron.kb_ids`), rejecting `NVIDIA-AI-Blueprints/rag` as a service due to Python dependency conflicts (`openai<2.0` vs `>=3.6.0`), non-durable `asyncio` ingestion tasks, and lack of tenant authentication.
* **ADR-0015 (Out-of-Process Parsing):** Standardize on `docling-serve` (MIT) in a network-isolated container receiving raw file bytes, paired with `docling-core` `HybridChunker` in `neuron-worker`, keeping PyTorch and AGPL/GPL parsers (`PyMuPDF`, `MinerU`, `Marker`) out of Neuron's runtime.
* **ADR-0016 (Durable Queue & Tombstone Lifecycle):** Use `Procrastinate` on Neuron's PostgreSQL for restart-safe background jobs and enforce immediate tombstone filtering (`deleted_at IS NULL AND status = 'ready'`) prior to async chunk/blob cleanup.
* **ADR-0017 (Server-Validated Stamped Citations):** Mint per-run `cite_id` tokens in retrieval tools, validate them in `_final_answer` against run tool messages, and stamp resolved provenance (including `excerpt_hash` and `locator_json` bounding boxes) into `AIMessage.additional_kwargs` to comply with ADR 0005.
* **ADR-0018 (Taint-Gated Retrieval & Single Orchestrator):** Mark all retrieval/web tools `taints_run=True` to enforce HITL approval on subsequent external tool calls, reject auto-extracted memory libraries (`langmem`, `Mem0`) per ADR 0009, and preserve LangGraph `create_agent` as the sole agent orchestrator.