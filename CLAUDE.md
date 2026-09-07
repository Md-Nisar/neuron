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
- `security/` — input, URL, and tool-allowlist policy (`security/input_policy.py`).
- `config/` — the only place environment variables are read (`config/settings.py`, `APP_*` prefixed, see `Settings`).
- `prompts/` — versioned prompt assets (`prompts/system/main.md`), loaded via `prompts/loader.py`.
- `observability/` — structlog JSON logging setup.
- `schemas/` — public API contracts and the `AgentAnswer` structured-output schema.

Do not add retrieval, queues, custom persistence, subgraphs, or multi-agent orchestration without a concrete product requirement **and** a new/updated ADR in `docs/decisions/` — this is a deliberate constraint, not an oversight (see ADR 0001, 0002). There is currently no checkpointer for local invocation; durable thread state is deferred to LangGraph Agent Server persistence when deployed.

## Security model

The model is never trusted as a security boundary — enforcement lives in code (`security/input_policy.py`), not the system prompt. Tools are currently read-only and explicitly allow-listed; high-impact/mutating tool names are deny-listed until an authorization + idempotency + audit-log story exists (ADR 0003, `SECURITY.md`). User input, tool output, and any external/retrieved content are all untrusted. User IDs are hashed before entering graph state. No `eval`/shell-executing tools.

## Extending the codebase

Use the project skills instead of re-deriving the checklist: `add-tool` for a new tool under `src/neuron_agent/tools/`, `add-graph-node` for changes to the `StateGraph`/`MainGraphState`. Both sequence the requirements already defined in `DEVELOPMENT.md`, `AGENTS.md`, and `SECURITY.md` (input contract, authorization wiring, timeout/failure tests, doc/ADR updates) so steps don't get skipped.

Framework upgrades (LangChain/LangGraph major/minor bumps): re-check upstream docs, update `uv.lock`, run all quality gates, and add regression tests for graph state and structured-output behavior before merging (`AGENTS.md`).

## Project stage

Currently v0.1.0 ("Functional Agent Runtime") per `docs/ROADMAP.md`. v0.2.0 ("Reliable Agent Runtime") is the active target — error taxonomy, enforced runtime limits, provider retry/backoff, hardened tool/input boundaries, rate limiting, an expanded failure-path test suite, and eval dataset v1. Check `docs/ROADMAP.md` and open issues/milestones before assuming a reliability feature (retries, rate limiting, structured error taxonomy) already exists — most are planned, not yet implemented.
