.PHONY: install dev run api db-setup prune-threads dev-auth dev-jwks dev-token dev-keycloak reference-up reference-down reference-digest reference-token load web-install web-dev web-format web-lint web-typecheck web-test web-build web-audit web format lint typecheck test test-unit test-graph test-security test-resilience test-integration eval security build

install:
	uv sync --no-dev

dev:
	uv sync

run:
	uv run langgraph dev

api:
	uv run uvicorn neuron_agent.api.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers

db-setup:
	uv run python -m neuron_agent.persistence.cli setup

prune-threads:
	uv run python -m neuron_agent.persistence.cli prune

# The v0.9.0 reference stack (ADR 0012): two API replicas, Postgres and Keycloak, from an
# image passed in. `NEURON_IMAGE=neuron:ref make reference-up`; local use only.
reference-up:
	docker compose -f docker-compose.reference.yml up -d --wait

reference-down:
	docker compose -f docker-compose.reference.yml down -v

reference-digest:
	@sh scripts/reference_digest.sh

# Prints an access token for a reference-stack user (default alice) for the smoke test.
reference-token:
	@sh scripts/reference_token.sh $(USER_NAME)

# Load scenarios against the running reference stack (ADR 0012): LOAD_SCENARIO=mix|new_thread|
# follow_up|approval, LOAD_STEP_SECONDS, LOAD_STEP_USERS. Steps are written to LOAD_RESULTS_FILE.
load:
	uv run python -m loadtest.provision
	uv run python -m locust -f loadtest/locustfile.py --headless --only-summary

# Development only: a local signing key and JWKS instead of an identity provider.
dev-auth:
	@uv run python scripts/dev_token.py setup

dev-jwks:
	@uv run python scripts/dev_token.py serve

dev-token:
	@uv run python scripts/dev_token.py

# Development only: API settings for the compose `keycloak` profile (ADR 0010).
dev-keycloak:
	@uv run python scripts/dev_keycloak.py

format:
	uv run python -m ruff format src tests loadtest

lint:
	uv run python -m ruff check src tests loadtest

typecheck:
	uv run python -m mypy src loadtest scripts/dev_token.py scripts/smoke_test.py scripts/token_report.py scripts/validate_observability.py

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
	uv run python -m bandit -q -r src loadtest scripts/dev_token.py scripts/smoke_test.py scripts/deploy_tools.py scripts/token_report.py scripts/validate_observability.py
	@# Two steps, not a pipe: /bin/sh has no pipefail, so a failed export would audit nothing.
	@reqs=$$(mktemp) \
		&& uv export --frozen --format requirements-txt --no-emit-project --all-groups -q -o "$$reqs" \
		&& uv run pip-audit -r "$$reqs" --disable-pip --progress-spinner off $(AUDIT_IGNORES); \
		status=$$?; rm -f "$$reqs"; exit $$status

build:
	uv build

# The web application (ADR 0010). Install from the lockfile only; `make web` runs every gate.
web-install:
	npm --prefix web ci

web-dev:
	npm --prefix web run dev

web-format:
	npm --prefix web run format:check

web-lint:
	npm --prefix web run lint

web-typecheck:
	npm --prefix web run typecheck

web-test:
	npm --prefix web test

web-build:
	npm --prefix web run build

web-audit:
	npm --prefix web audit --audit-level=low

web: web-format web-lint web-typecheck web-test web-build web-audit
