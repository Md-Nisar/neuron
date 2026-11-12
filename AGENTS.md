# Coding Agent Instructions

## Architecture Rules

- Keep HTTP concerns in `api/`.
- Keep request orchestration in `services/`.
- Keep graph construction and node routing in `graphs/`.
- Keep provider and LangChain harness construction in `models/`.
- Keep prompts under `prompts/`.
- Do not scatter environment reads outside `config/`. There are two exceptions. `observability/langsmith_governance.py` overwrites LangSmith's own `LANGSMITH_*`/`LANGCHAIN_*` variables because the library reads them itself (ADR 0007, section 5). `observability/telemetry.py` sets `OTEL_SEMCONV_STABILITY_OPT_IN` for the same reason (ADR 0008, decision 3). `tests/unit/test_entrypoint.py` fails on any other `os.environ`/`os.getenv` use under `src/`.
- Keep the Knowledge Engine in `knowledge/` (ADR 0014), within the boundaries below.
- Do not add retrieval, queues, custom persistence, or subgraphs without a concrete requirement and ADR update. ADR 0014 covers the knowledge module's retrieval, ingestion queue and storage, and nothing beyond them.

## Knowledge Engine Boundaries

`knowledge/` holds storage, the ingestion worker, retrieval, the knowledge tools and citation validation (ADR 0014; `ARCHITECTURE.md`, "Knowledge storage"). `tests/unit/test_knowledge_boundaries.py` enforces the import rules.

- Only three layers import it: `api/` (the `/v1/knowledge` routes and their wiring), `services/` (`AgentService` adds the knowledge tools and erases a user's knowledge) and `graphs/`, which uses `knowledge/citations.py` only.
- It never imports `api/`, `services/`, `graphs/`, `agents/` or `models/`. It may use `config/`, `errors/`, `observability/`, `persistence/`, `schemas/`, `security/` and `tools/` (the registry and framing).
- Every query filters on the bases the caller may use (`allowed_kbs`: their HMAC owner key's bases and those shared with their verified roles, ADR 0014 amendment "sharing by role"), and `knowledge.chunks` and `knowledge.embeddings` also have row-level security. Never accept a base or document id without that check.
- Retrieved text is untrusted. It reaches the model only inside the framed `<knowledge>` block (`tools/framing.py`), and a knowledge tool call taints the run, so gated tools then need approval. Citations are checked on the server: an answer keeps only the `cite_id`s its own run's tools issued.
- `neuron-worker` (`knowledge/worker.py`) is a separate process with its own database role (`APP_POSTGRES_WORKER_DSN`). Never give it the app or migration DSN, the identity key or the auth settings.
- docling-serve parses files on an internal network with no route out. The embedding provider is the only hosted step, and each base's processing setting governs it (`hosted` or `self_hosted`; `SECURITY.md`, "Knowledge Embedding Egress").
- Operating it: `OPERATIONS.md`, "Knowledge Engine" (runbooks) and "Runbook: knowledge queue".

## Commands

Run before delivery:

```bash
make format
make lint
make typecheck
make test
make security
```

## Forbidden Patterns

- No raw `eval` or shell execution tools.
- No committed secrets.
- No live LLM calls in unit tests.
- No mutating tools without authorization, idempotency, and tests.
- No prompt-only security controls.

## Framework Upgrades

Before changing LangChain or LangGraph versions, re-check official docs, update `uv.lock`, run all quality gates, and add regression tests for graph state and structured output behavior.

## Verifying AI-Generated Code

Follow `docs/AI_CODE_VERIFICATION.md`. In short: keep changes small (under 400 lines where possible), write tests that fail without the change, never add a dependency without stating why and confirming it is the intended PyPI project, fill in the PR template's AI assistance, risk tier and verification sections, and keep the `Co-Authored-By:` commit trailer. AI review comments are advisory; a human approves every merge.
