# Architecture Summary: Neuron Enterprise AI Platform

## 1. Product, Principals, and Protected Resources
Neuron is an enterprise-grade agentic AI assistant and retrieval-augmented generation (RAG) platform.
- **Principals**:
  - *Anonymous/External Client*: Untrusted internet actors communicating via HTTPS to edge reverse proxies.
  - *Authenticated User*: Validated via Auth0 RS256 Bearer JWT tokens. Assigned hierarchical roles: `viewer` (read-only query), `analyst` (query, execute tools, upload files), and `admin` (full access).
  - *Background Workers & Microservices*: Internal components (Docling document parser, LLM provider connectors, MCP servers).
- **Protected Resources**: Auth0 identity & credentials, private user chat sessions, R2/S3 raw document blobs, vector embeddings, and LLM orchestration graph state.

## 2. Tech Stack and Baseline
- **Backend**: Python 3.13 / 3.14, FastAPI, Pydantic v2, LangChain, LangGraph, Uvicorn, obstore, httpcore2, python-multipart.
- **Frontend**: React 19, TypeScript, Vite, Tailwind CSS, DOMPurify sanitization.
- **Infrastructure**: Cloudflare Pages (Frontend SPA), Cloudflare R2 (S3-compatible object storage), Docker containers, GitHub Actions CI/CD workflows.
- **Comparable Baseline**: Enterprise RAG assistants (OpenWebUI, LangGraph Cloud, AWS Bedrock Agent harnesses). Neuron adopts strict defensive boundaries: no arbitrary dynamic code execution, strict AST math evaluation, bounded streaming multipart ingestion without disk spooling, and explicit SSRF prevention via DNS-pinned socket connections.

## 3. Entry Surfaces and Data Sinks
- **Surface 1: HTTP API** (`POST /api/v1/chat`, `POST /api/v1/upload`, `GET /health/*`, `GET /metrics`): Handled by FastAPI with CORS, trusted proxy resolution, and sliding-window rate limiting.
- **Surface 2: Web SPA** (`web/`): Cloudflare Pages edge hosting, SPA client routing, memory-only session tokens.
- **Surface 3: Agent & Model Context** (`graphs/`, `models/`, `prompts/`): LLM input/output policies, system prompt sandboxing, token caps.
- **Surface 4: Tool Execution** (`tools/calculator.py`, `tools/mcp/client.py`): Strict AST expression evaluation and hash-pinned MCP tool calls.
- **Surface 5: Storage & Parsing** (`knowledge/blobs.py`, `knowledge/parsing.py`, `knowledge/docling_serve.py`): Random 128-bit hex blob keys, SHA-256 integrity verification, sandboxed Docling JSON schema parser.
- **Surface 6: Outbound Network Egress** (`security/egress.py`): Socket-level resolution checking public IPs only, blocking loopback, link-local, private, and multicast addresses.

## 4. Trust Boundaries and Strongest Controls
- **Boundary 1 (External -> Edge)**: Cloudflare WAF, DDoS mitigation, `_headers` security headers, and trusted proxy IP extraction.
- **Boundary 2 (Unauth -> Auth)**: Auth0 JWKS RS256 signature, audience, and expiration verification in `security/auth.py`.
- **Boundary 3 (Auth -> RBAC)**: Role checks via `security/authorization.py`.
- **Boundary 4 (Input -> LLM)**: Input guardrails in `security/input_policy.py`.
- **Boundary 5 (LLM -> Output/Tools)**: Output guardrails (`security/output_policy.py`), AST math restriction (`calculator.py`), and hash-pinned MCP client schemas (`mcp/client.py`).
- **Boundary 6 (Worker -> Outbound Egress)**: Egress SSRF prevention via `PublicOnlyBackend` in `security/egress.py`.

## 5. Companion Selection
- `AI-AND-LLM.md`: Selected for prompt assembly, MCP client integrations, and output sanitization.
- `WEB-PROTOCOL-AND-AUTH.md`: Selected for FastAPI endpoints, Auth0 JWT verification, CORS, and rate limiting.
- `CLOUD-AND-DEPLOYMENT.md`: Selected for Cloudflare Pages, R2 storage, Docker packaging, and CI/CD pipelines.
- `CLIENT-SIDE.md`: Selected for React SPA, markdown rendering, and postMessage frame communications.
- `DATA-ISOLATION-AND-LIFECYCLE.md`: Selected for multi-tenant blob isolation and document ingestion lifecycles.
