# Specifications: Release History, Versioning, and Compatibility

> **Document ID:** DOC-SPEC-002  
> **Diátaxis Mode:** Reference / Specification  
> **Standard Alignment:** Structured in alignment with ISO/IEC/IEEE 26514:2022 §7.1 (System Specifications & Lifecycle) and Diátaxis (Specification)  
> **Current Version:** 1.2.0  
> **Code Traceability:** `CHANGELOG.md`, `pyproject.toml`, `src/neuron_agent/persistence/migrations.py`

---

## 1. Versioning Strategy and Expand/Contract Rule

Neuron Agent follows [Semantic Versioning 2.0.0](https://semver.org/) (`MAJOR.MINOR.PATCH`). 

### Expand/Contract Migration Policy (Zero Down-Migrations)
To achieve zero-downtime rolling deployments, all database changes adhere to the **expand/contract** pattern:
1. **Expand Phase:** Migrations add new tables, nullable columns, and non-blocking concurrent indexes (`CREATE INDEX CONCURRENTLY`). The database remains 100% compatible with the previous application release.
2. **Contract Phase:** Deprecated columns or legacy tables are dropped only in subsequent releases, after all running replicas have been successfully upgraded.
3. **Rollback Strategy:** There are **no down-migrations**. In the event of a deployment failure, rollback consists simply of redeploying the previous container image.

---

## 2. Release History Summary

```
v0.1.0 ──► v0.3.0 ──► v0.4.0 ──► v0.5.0 ──► v0.7.0 ──► v0.8.0 ──► v1.0.0 ──► v1.1.0 ──► v1.2.0
Single      State &    JWT Auth   OpenTelemetry MCP Tools  React UI   Prod Gate  Knowledge  Retrieval &
Agent Node  Streaming  & Scopes   & SemConv    & Approvals App SPA    Release    Engine     Role Sharing
```

| Release | Date | Architectural Significance & Major Features |
| :--- | :--- | :--- |
| **v1.2.0** *(Current)* | Nov 2026 | **Retrieval Quality and Sharing (RAG-E09):** Cross-encoder candidate reranking (`nvidia/llama-nemotron-rerank-vl-1b-v2`) with automatic RRF fallback; role-based knowledge base sharing (`read`, `write`, `admin` access levels via token roles `APP_AUTH_ROLES_CLAIM`, `knowledge:admin` scope); operator zero-downtime re-indexing (`neuron-reindex start\|status\|cancel`) with multi-profile background dual-embedding and atomic swap; multilingual full-text search across 29 PostgreSQL dictionary configs; nightly retrieval regression gate (`knowledge-retrieval` in `nightly-eval.yml`); knowledge load scenarios & baseline report; operator feedback report (`feedback-report`) linking negative answer ratings to cited chunks; migrations 28 & 29. |
| **v1.1.0** | Nov 2026 | **Knowledge Engine (RAG):** Document ingestion (PDF, DOCX, XLSX, PPTX, TXT, MD), `docling-serve` unroutable parser container, pgvector hybrid search, Procrastinate task queue, RLS on chunks/embeddings, cryptographic citation verification. |
| **v1.0.0** | Nov 2026 | **Production Candidate General Availability:** Hardened multi-instance coordination, automated recovery drills, comprehensive end-to-end integration gates. |
| **v0.9.0** | Oct 2026 | **Reference Stack & Load Testing:** Reference multi-replica Docker Compose stack, Locust load-testing harness, benchmark gates. |
| **v0.8.0** | Oct 2026 | **Web Application:** React 19 single-page application (`web/`), TypeScript, Tailwind CSS, PKCE OIDC authentication, streaming client, approval dialogs. |
| **v0.7.0** | Oct 2026 | **Extensible Agent Platform:** Model Context Protocol (MCP) streamable HTTP support, cryptographic tool pinning (`neuron-mcp-pin`), human-in-the-loop approvals, user memory notes (`remember`, `recall`, `forget`). |
| **v0.6.0** | Oct 2026 | **Distributed Coordination:** PostgreSQL-backed distributed run leases (`neuron_run_leases`), rolling token budget ledger (`neuron_token_ledger`), distributed unlogged rate buckets. |
| **v0.5.0** | Oct 2026 | **Observability & Governance:** OpenTelemetry metrics and distributed tracing, SemConv v1.26.0 compliance, LangSmith privacy governance with automatic prompt redaction. |
| **v0.4.0** | Oct 2026 | **Enterprise Authentication:** Bearer JWT token verification via JWKS, 15 authorization scopes, HMAC-SHA256 caller pseudonymity, GDPR export & bulk erasure. |
| **v0.3.0** | Oct 2026 | **Stateful Persistence & Streaming:** PostgreSQL checkpointer (`AsyncPostgresSaver`), multi-turn conversations, SSE streaming (`/v1/agent/stream`). |
| **v0.1.0 – v0.2.0**| Oct 2026 | **Initial Baseline:** FastAPI baseline, single-node LangGraph agent, bounded tools (`utc_now`, `calculator`), deterministic fake model for CI. |

---

## 3. Platform Compatibility Matrix

| Dependency / Subsystem | Supported Versions | Tested & Verified Baseline | Notes & Constraints |
| :--- | :--- | :--- | :--- |
| **Python Runtime** | `3.13`, `3.14` | Python 3.13.2 | Managed via `uv` 0.11+. Fails fast on Python $\le 3.12$. |
| **PostgreSQL** | `16`, `17` | PostgreSQL 16.4 | Requires `pgvector` extension. |
| **pgvector** | $\ge 0.7.0$ | pgvector 0.7.4 | Required for `halfvec` vector types and HNSW indexing. |
| **Node.js (Web UI)** | $\ge 20.0.0$ | Node.js 22.11 LTS | Managed via `web/.nvmrc`. |
| **Docker Engine** | $\ge 24.0.0$ | Docker 27.2 with Compose v2 | Required for containerized deployments and reference stack. |
| **Identity Providers** | OIDC / RFC 7519 compliant | Keycloak 26+, Auth0, Okta | Must provide HTTPS JWKS endpoint and support RS256 or ES256. |

---

## 4. Disclosure of Known Limitations and Environmental Boundaries

In strict compliance with ISO/IEC/IEEE 26514:2022 §7.1.4 (Identification of Constraints and Limitations), the following architectural boundaries and non-verified features are formally documented:

1. **No Hosted Production Deployment Environment:**  
   As with releases 1.0.0 and 1.1.0, Neuron Agent is validated against automated test suites and a multi-container local reference stack (`docker-compose.reference.yml`). No hosted staging environment, public cloud deployment, or long-running production cluster currently exists. Releases are validated locally (`docs/releases/v1.2.0-release-verification.md`).
2. **Multilingual FTS Stemming Variations:**  
   PostgreSQL built-in full-text search configurations vary in recall depending on language morphology. Evaluation on the multilingual test corpus (`tests/fixtures/knowledge/multilingual/cases.json`) demonstrated text-channel recall@5 of 1.00 for English, Spanish, and French, but 0.33 for German compound nouns with the built-in `german` configuration. Advanced BM25 ranking via `pg_textsearch` is deferred until PostgreSQL 17+ becomes the mandatory minimum version.
3. **Anthropic Live Key Verification:**  
   Neuron includes full support for Anthropic models (`APP_DEFAULT_MODEL=anthropic:<model-id>`) via `langchain-anthropic`. The integration is covered by automated unit tests using mock fakes. However, because funded Anthropic API keys were not available during the release gates, **Anthropic models have not been verified against the live Anthropic API**.
4. **Windows Unprivileged Symlinks Limitation:**  
   In Windows operating systems, creating filesystem symlinks requires administrative privileges or Developer Mode enabled. Consequently, test cases in `tests/unit/test_web_headers.py` that invoke `os.symlink` will raise `[WinError 1314]` if executed in unprivileged Windows developer environments. This does not impact runtime execution of the API or Worker, which do not create symlinks.
5. **Agent Server Feature Exclusions:**  
   When deploying the exported graph through LangGraph Agent Server (`langgraph.json`):
   - Knowledge Engine tools and `/v1/knowledge` routes are not supported (they exist on the FastAPI service path only).
   - User memory notes stored in LangGraph `Store` are not accessible via Agent Server.
6. **`docling-serve` Resource Requirements:**  
   The `docling-serve` container image requires approximately 7.6 GB of disk space and a minimum of 4 GB RAM to perform OCR and layout parsing on complex documents. On resource-constrained environments, plain text (`.txt`) and Markdown (`.md`) ingestion should be used instead.
7. **E2E Browser Test Concurrency Edge Case:**  
   The browser test suite (`web/e2e/knowledge.spec.ts`) contains an erase-flow second-user sign-in test that can exhibit a race condition under constrained CI runner load.
8. **Windows Typechecking with POSIX System Calls:**  
   The load-testing harness (`loadtest/knowledge.py`) inspects POSIX system limits via `os.sysconf` wrapped in a defensive exception handler. On Windows developer workstations, running `mypy loadtest` reports an `attr-defined` error because `os.sysconf` is unavailable on Windows. Running type checks against the core application code (`uv run mypy src`) passes with zero issues on Windows, and `loadtest/knowledge.py` executes without error on Windows via its exception fallback.

