.PHONY: install dev run api format lint typecheck test test-unit test-graph test-security test-resilience test-integration eval security build

install:
	uv sync --no-dev

dev:
	uv sync

run:
	uv run langgraph dev

api:
	uv run uvicorn neuron_agent.api.main:app --host 127.0.0.1 --port 8000

format:
	uv run python -m ruff format src tests

lint:
	uv run python -m ruff check src tests

typecheck:
	uv run python -m mypy src

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
	uv run python -m pytest tests/integration

eval:
	uv run python -m pytest tests/evals -m eval

security:
	uv run python -m bandit -q -r src

build:
	uv build
