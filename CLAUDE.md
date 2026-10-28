# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Behavioral guidelines

Adapted from [andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills).

1. **Think before coding.** Don't assume, don't hide confusion. State assumptions explicitly; if multiple interpretations exist, present them instead of picking silently; if something is unclear, stop and ask.
2. **Simplicity first.** Minimum code that solves the problem — no features beyond what was asked, no speculative abstractions or configurability, no error handling for scenarios that can't happen. If it could be half the size, rewrite it.
3. **Surgical changes.** Touch only what the request requires. Don't refactor or restyle adjacent code. Remove imports/vars/functions your own change orphaned; leave pre-existing dead code alone unless asked. Every changed line should trace to the request.
4. **Goal-driven execution.** Turn vague tasks into verifiable success criteria (e.g. "fix the bug" → "write a failing test reproducing it, then make it pass") and verify against them before declaring done.

## Commands

```bash
uv sync                     # install deps (add --no-dev for prod-only)
cp .env.example .env        # local config; set OPENAI_API_KEY for live model calls

make format                 # ruff format src tests
make lint                   # ruff check src tests
make typecheck               # mypy --strict src
make test                   # unit + graph + security + evals (no external calls)
make test-integration        # requires OPENAI_API_KEY; live provider calls
make eval                   # agent quality regression checks (pytest -m eval)
make security                # bandit -r src
make build                  # uv build
make api                    # run FastAPI app (uvicorn) on 127.0.0.1:8000
make dev-auth >> .env       # development only: local JWT signing key + jwt settings
make dev-jwks               # development only: serve that key's JWKS on 127.0.0.1:8765
make dev-token              # development only: print a bearer token for the local API
make run                    # run via `langgraph dev` (LangGraph Studio-compatible)
```

Run a single test: `uv run pytest tests/unit/test_calculator.py::test_name -q`.
Test suites are split by directory (`tests/unit`, `tests/graph`, `tests/security`, `tests/integration`, `tests/evals`); `tests/integration` and `tests/evals` are marker-gated (`integration`, `eval` in `pyproject.toml`) and excluded from `make test`. Without `OPENAI_API_KEY`, dev/test environments fall back to a fake local chat model, so `make test` never makes live calls — only `make test-integration` and `make eval` need real credentials.

Run all gates before considering work done: `make format lint typecheck test security`.

## Architecture

Request flow is linear and single-directional: `FastAPI (api/) -> AgentService (services/) -> LangGraph StateGraph (graphs/) -> LangChain create_agent harness (agents/ + models/) -> model provider + tools`. The graph itself is intentionally trivial (`START -> agent -> END`, see `ARCHITECTURE.md`); LangGraph exists for explicit typed state and Agent Server deployment compatibility, while `create_agent` owns the actual model/tool loop.

Module boundaries (enforced, see `AGENTS.md`):
- `api/` — HTTP transport, health endpoints, HTTP error mapping only.
- `services/` — request normalization/orchestration, no HTTP or graph internals.
- `graphs/` — `StateGraph` construction and node routing (`MainGraphState` in `state/`).
- `agents/` — agent composition and approved-tool wiring (`agents/factory.py`).
- `models/` — the `create_agent`/provider boundary (`models/factory.py`).
- `tools/` — bounded, read-only tool implementations.
- `security/` — authentication and authorization, plus input, URL, and tool-allowlist policy (`security/input_policy.py`). `auth.py` owns JWT verification (`TokenVerifier`), the `Principal`, the owner-key HMAC and the single `/v1` route dependency `require_permission`; `authorization.py` owns permissions and the per-run `AuthorizationContext`; `agent_server.py` holds the Agent Server auth handlers. Routes never parse tokens themselves, and the principal reaches graphs and tools only through the runtime `context` (ADR 0006).
- `config/` — the only place environment variables are read (`config/settings.py`, `APP_*` prefixed, see `Settings`).
- `prompts/` — versioned prompt assets (`prompts/system/main.md`), loaded via `prompts/loader.py`.
- `observability/` — structlog JSON logging, audit events and OpenTelemetry setup (`telemetry.py`; names only in `semconv.py`).
- `schemas/` — public API contracts and the `AgentAnswer` structured-output schema.

Do not add retrieval, queues, custom persistence, subgraphs, or multi-agent orchestration without a concrete product requirement **and** a new or updated ADR in `docs/decisions/`. This is a deliberate constraint, not an oversight (see ADR 0001, 0002, 0005).

Thread persistence follows ADR 0005:
- `persistence/` selects a LangGraph checkpointer from `APP_CHECKPOINTER`: `auto`, `memory`, `postgres` or `none`.
- `AgentService` owns thread rules, run leases and streaming (`POST /v1/agent/stream`).
- The `langgraph.json` graph is compiled without a checkpointer, because Agent Server supplies its own.

## Security model

The model is never trusted as a security boundary — enforcement lives in code (`security/input_policy.py`), not the system prompt. Tools are currently read-only and explicitly allow-listed; high-impact/mutating tool names are deny-listed until an authorization + idempotency + audit-log story exists (ADR 0003, `SECURITY.md`). User input, tool output, and any external/retrieved content are all untrusted. Identity comes only from a verified bearer token in `APP_AUTH_MODE=jwt` (required in staging/production); it enters graph state only as an HMAC owner key, and request `user_id`/`X-User-Id` are ignored. No `eval`/shell-executing tools.

## Extending the codebase

Use the project skills instead of re-deriving the checklist: `add-tool` for a new tool under `src/neuron_agent/tools/`, `add-graph-node` for changes to the `StateGraph`/`MainGraphState`. Both sequence the requirements already defined in `DEVELOPMENT.md`, `AGENTS.md`, and `SECURITY.md` (input contract, authorization wiring, timeout/failure tests, doc/ADR updates) so steps don't get skipped.

Framework upgrades (LangChain/LangGraph major/minor bumps): re-check upstream docs, update `uv.lock`, run all quality gates, and add regression tests for graph state and structured-output behavior before merging (`AGENTS.md`).

## Project stage

The latest tagged release is v0.8.0 ("User Application", ADR 0010 and 0011): a `web/` single-page app with Keycloak sign-in (PKCE), streaming chat, approvals, memories, data rights, conversation titles and feedback. v0.6.0 ("Production Deployment", ADR 0008) and v0.7.0 ("Extensible Agent Platform", ADR 0009) were tagged on 2026-10-28 as well. All three shipped with their release gates open (#160, #253, #293), deferred by the owner until after v1.0.0; nothing has run on a real Render deployment, a real browser against Keycloak, or the OpenAI production model.

v0.9.0 ("Production Candidate", ADR 0012) is prepared on the branch and **not tagged**: a local reference stack (`docker-compose.reference.yml`, `make reference-up`), Locust load tests (`loadtest/`, `make load`), a threat model, a DAST workflow, a restore drill and a rollback rehearsal, with evidence in `docs/releases/v0.9.0-gate/`. The release freeze (`CONTRIBUTING.md`) starts at the tag.

Release verification is recorded in `docs/releases/vX.Y.Z-release-verification.md`. Check `docs/ROADMAP.md` and open issues before assuming a not-yet-released feature already exists.

## AI code verification

Every PR passes the gates in `docs/AI_CODE_VERIFICATION.md` (`ci`, `ai-code-verification`, `codeql`, advisory `ai-review` on NVIDIA's free API catalog). Before opening a PR: keep it under 400 changed lines, add tests that fail without the change, justify any new dependency (the `new-dependencies` job rejects packages missing from PyPI or under 90 days old), and fill in `.github/pull_request_template.md`. Run the `security-reviewer` agent for critical-tier paths. Never claim the work is verified unless `make format lint typecheck test security` passed.
