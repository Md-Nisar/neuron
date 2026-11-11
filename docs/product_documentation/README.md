# Neuron Agent — Official Product Documentation Suite

> **Standard Alignment:** Structured in accordance with ISO/IEC/IEEE 26514:2022 (*Software User Documentation*) principles and Diátaxis documentation modes  
> **Product Version:** 1.1.0  
> **Status:** Production-Ready & Code-Verified  
> **Repository Baseline:** Commit `c726975` (Release v1.1.0)  
> **Documentation Custodian:** Md Nisar Ahmed (`nisar.a@entomo.co`)

---

## 1. Documentation Purpose and Scope

This document suite serves as the definitive, production-grade technical and operational manual for **Neuron Agent** (version 1.1.0). Every procedure, architecture diagram, configuration parameter, API contract, database schema, and operational runbook in this suite is directly traced to, and validated against, the underlying Python service codebase (`src/neuron_agent/`), the frontend single-page application (`web/`), the automated test suite (`tests/`), and formal architectural decision records (`docs/decisions/` ADR 0001 through ADR 0014).

### Objectives
1. **Adherence to International Information Design Standards:** Conforms to ISO/IEC/IEEE 26514:2022 recommendations for accuracy, completeness, clarity, conciseness, maintainability, and task-orientation.
2. **Diátaxis Information Architecture:** Strict separation between learning-oriented tutorials, problem-oriented how-to guides, information-oriented reference material, and understanding-oriented conceptual explanations.
3. **Docs-as-Code Traceability:** Strict synchronization with the codebase; absence of speculative or unimplemented features; explicit disclosure of environmental boundaries and verified limits.
4. **Multi-Audience Support:** Direct utility for application developers, system architects, security officers, site reliability engineers (SREs), compliance managers, and technical testers.

---

## 2. Diátaxis Structural Map

Technical documentation is partitioned into the four distinct Diátaxis modes:

```
                      PRACTICAL FOCUS
                             │
            Tutorials        │       How-To Guides
       (Learning-oriented)   │    (Task/Problem-oriented)
                             │
─────────────────────────────┼─────────────────────────────
                             │
          Explanation        │         Reference
    (Understanding-oriented) │   (Information-oriented)
                             │
                      THEORETICAL FOCUS
```

| Diátaxis Mode | Focus & Intent | Target Persona | Primary Directory |
| :--- | :--- | :--- | :--- |
| **Tutorials** | Hands-on, step-by-step introduction to build starting competence with guaranteed success. | New Developers, Evaluators | [`tutorials/`](tutorials/getting-started.md) |
| **How-To Guides** | Goal-oriented recipes and procedural guides to solve specific real-world tasks. | Developers, Operators, SREs | [`how-to/`](how-to/) |
| **Reference** | Technical descriptions, machinery, schemas, syntax, and error catalogues. | Developers, Integrators, SREs | [`reference/`](reference/) |
| **Explanation** | Architectural reasoning, background context, design choices, and security models. | Architects, Security, Leads | [`explanation/`](explanation/) |

In addition, standard product specifications and lifecycle guides are provided in:
- [`overview/`](overview/product-overview.md): Product vision, value proposition, feature catalogue, and capabilities.
- [`specifications/`](specifications/functional-specifications.md): Functional requirements, business logic, quotas, and release history.

---

## 3. Suite Navigation and Document Catalogue

```
docs/product_documentation/
├── README.md                                          # Master documentation portal (this file)
├── overview/
│   └── product-overview.md                           # Product vision, architectural summary, feature matrix
├── tutorials/
│   └── getting-started.md                            # Complete onboarding tutorial from clone to SSE streaming
├── how-to/
│   ├── authentication-and-authorization.md          # OIDC/JWT, JWKS caching, scopes, role mapping, dev tokens
│   ├── persistence-and-storage.md                   # PostgreSQL checkpointer, pool tuning, migrations, roles
│   ├── knowledge-engine-rag.md                      # Knowledge bases, document upload, docling-serve, hybrid search
│   ├── mcp-integration-and-approvals.md             # Streamable HTTP MCP, tool pinning, human approval gates
│   ├── memory-and-privacy.md                        # User note engine, remember/recall/forget, GDPR erase/export
│   ├── web-application.md                           # React/Vite web UI deployment, PKCE authentication, CSP
│   └── production-operations.md                     # Deployment, health probes, Prometheus/OTel, runbooks, backup
├── reference/
│   ├── rest-api.md                                  # Complete REST API reference (26 endpoints with schemas)
│   ├── sse-protocol.md                              # Server-Sent Events (SSE) Protocol v1 specification
│   ├── configuration.md                             # Complete APP_* settings dictionary & validation rules
│   ├── database-schema.md                           # PostgreSQL tables, indexes, RLS policies, 27 migrations
│   ├── error-catalogue.md                           # Error taxonomy, HTTP status codes, retryability, client visibility
│   └── cli-and-commands.md                          # neuron-api, neuron-worker, neuron-mcp-pin, CLI tools, Makefile
├── explanation/
│   ├── architecture-and-state-machine.md            # LangGraph state graph, run leases, turn atomicity, history bounds
│   ├── security-and-threat-model.md                 # Defense-in-depth, HMAC isolation, taint tracking, egress policy
│   ├── knowledge-engine-internals.md                # RAG pipeline, Docling unroutable parser, Procrastinate queue, RRF
│   └── observability-and-governance.md              # OpenTelemetry traces & metrics, SemConv, LangSmith governance, audit
└── specifications/
    ├── functional-specifications.md                 # Business rules, system limits, concurrency, rate limits
    └── releases-and-compatibility.md                # Version roadmap, expand/contract migrations, backwards compatibility
```

---

## 4. Target Audience Profiles (ISO/IEC/IEEE 26514:2022)

| Audience Persona | Responsibilities & Focus | Key Documents to Read |
| :--- | :--- | :--- |
| **Application Developer** | Integrates backend and frontend clients with Neuron via REST API and SSE stream; configures custom tools. | [`tutorials/getting-started.md`](tutorials/getting-started.md)<br>[`reference/rest-api.md`](reference/rest-api.md)<br>[`reference/sse-protocol.md`](reference/sse-protocol.md)<br>[`how-to/mcp-integration-and-approvals.md`](how-to/mcp-integration-and-approvals.md) |
| **Site Reliability Engineer (SRE) / DevOps** | Provisions PostgreSQL, Keycloak, worker processes, and Docker/Render hosting; configures telemetry and alerts. | [`how-to/persistence-and-storage.md`](how-to/persistence-and-storage.md)<br>[`how-to/production-operations.md`](how-to/production-operations.md)<br>[`reference/configuration.md`](reference/configuration.md)<br>[`reference/cli-and-commands.md`](reference/cli-and-commands.md) |
| **Enterprise Security Officer** | Audits trust boundaries, HMAC identity isolation, RLS rules, data retention, prompt injection controls, and tool safety. | [`explanation/security-and-threat-model.md`](explanation/security-and-threat-model.md)<br>[`how-to/authentication-and-authorization.md`](how-to/authentication-and-authorization.md)<br>[`explanation/observability-and-governance.md`](explanation/observability-and-governance.md) |
| **Data Protection & Compliance Officer** | Verifies GDPR/CCPA data subject export and erasure rights, token budgeting, and zero-prompt-leak logging. | [`how-to/memory-and-privacy.md`](how-to/memory-and-privacy.md)<br>[`specifications/functional-specifications.md`](specifications/functional-specifications.md)<br>[`reference/database-schema.md`](reference/database-schema.md) |
| **System Architect / Lead** | Assesses architectural resilience, state machine atomicity, multi-instance concurrency, and RAG ingestion throughput. | [`overview/product-overview.md`](overview/product-overview.md)<br>[`explanation/architecture-and-state-machine.md`](explanation/architecture-and-state-machine.md)<br>[`explanation/knowledge-engine-internals.md`](explanation/knowledge-engine-internals.md) |

---

## 5. Traceability Matrix

Every documented topic maps directly to code implementations, architectural decisions, and verification tests:

| Document | Primary Implementation Module | ADR Baseline | Key Automated Tests |
| :--- | :--- | :--- | :--- |
| **REST API Reference** | `src/neuron_agent/api/main.py` | ADR 0001, 0005, 0006, 0014 | `tests/unit/test_api.py`, `tests/security/test_authorization.py` |
| **SSE Protocol** | `src/neuron_agent/services/streaming.py` | ADR 0005 | `tests/unit/test_streaming.py`, `tests/unit/test_web_stream_contract.py` |
| **Auth & Scopes** | `src/neuron_agent/security/auth.py` | ADR 0006 | `tests/unit/test_auth.py`, `tests/security/test_multi_user_isolation.py` |
| **Checkpointer & Migrations** | `src/neuron_agent/persistence/` | ADR 0002, 0008, 0011 | `tests/unit/test_migrations_policy.py`, `tests/integration/test_postgres_retention.py` |
| **Knowledge Engine (RAG)** | `src/neuron_agent/knowledge/` | ADR 0014 | `tests/unit/test_knowledge_storage.py`, `tests/security/test_knowledge_api.py` |
| **Memory Notes** | `src/neuron_agent/memory/` | ADR 0009 | `tests/security/test_memory_api.py`, `tests/unit/test_memory_store.py` |
| **MCP Integration** | `src/neuron_agent/tools/mcp/` | ADR 0009 | `tests/unit/test_mcp_client.py`, `tests/unit/test_mcp_wiring.py` |
| **Approvals Workflow** | `src/neuron_agent/services/agent_service.py` | ADR 0009 | `tests/security/test_approval_api.py`, `tests/graph/test_approval_gate.py` |
| **Telemetry & SemConv** | `src/neuron_agent/observability/` | ADR 0007, 0008 | `tests/unit/test_metrics.py`, `tests/unit/test_validate_observability.py` |
| **Web UI** | `web/src/` | ADR 0010 | `web/src/App.test.tsx`, `web/src/a11y/a11y.test.tsx`, `web/e2e/` |

---

## 6. Document Quality and Maintenance Rules

1. **Strict Sync with Implementation:** Code changes must update the corresponding manual sections within the same pull request.
2. **Deterministic Assertions:** No performance claims or timeout figures are stated without cross-referencing `Settings` defaults in `src/neuron_agent/config/settings.py` or measured gate benchmarks.
3. **Disclosure of Environmental Bounds:** Features dependent on external subsystems (such as `docling-serve` for OCR, or live LLM provider keys) are documented alongside their fallback behaviors and container resource profiles.
