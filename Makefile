.PHONY: install dev run api db-setup prune-threads dev-auth dev-jwks dev-token format lint typecheck test test-unit test-graph test-security test-resilience test-integration eval security build

install:
	uv sync --no-dev

dev:
	uv sync

run:
	uv run langgraph dev

api:
	uv run uvicorn neuron_agent.api.main:app --host 127.0.0.1 --port 8000

db-setup:
	uv run python -m neuron_agent.persistence.cli setup

prune-threads:
	uv run python -m neuron_agent.persistence.cli prune

# Development only: a local signing key and JWKS instead of an identity provider.
dev-auth:
	@uv run python scripts/dev_token.py setup

dev-jwks:
	@uv run python scripts/dev_token.py serve

dev-token:
	@uv run python scripts/dev_token.py

format:
	uv run python -m ruff format src tests scripts

lint:
	uv run python -m ruff check src tests scripts

typecheck:
	uv run python -m mypy src scripts/dev_token.py

test:
	uv run python -m pytest tests/unit tests/graph tests/security tests/resilience tests/evals

test-unit:
	uv run python -m pytest tests/unit

test-graph:
	uv run python -m pytest tests/graph

test-security:
	uv run python -m pytest tests/security

test-resilience:
	uv run python -m pytest tests/resilience

test-integration:
	uv run python -m pytest tests/integration -m integration

eval:
	uv run python -m pytest tests/evals -m eval

# Dependency audit ignores: each needs an entry, with a review date, in SECURITY.md
# (Dependency Vulnerabilities).
# Format: --ignore-vuln <ID> per entry. Currently none.
AUDIT_IGNORES :=

security:
	uv run python -m bandit -q -r src scripts/dev_token.py
	@# Two steps, not a pipe: /bin/sh has no pipefail, so a failed export would audit nothing.
	@reqs=$$(mktemp) \
		&& uv export --frozen --format requirements-txt --no-emit-project --all-groups -q -o "$$reqs" \
		&& uv run pip-audit -r "$$reqs" --disable-pip --progress-spinner off $(AUDIT_IGNORES); \
		status=$$?; rm -f "$$reqs"; exit $$status

build:
	uv build
