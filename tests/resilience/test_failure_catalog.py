"""Deterministic failure-and-resilience regression suite (issues #7, #375).

Each test forces a realistic failure at the model, provider, database, or network
boundary through unmocked AgentService execution, asserting that internal error
classification (classify_agent_error, _persistence_errors) correctly categorizes
failures into expected AppError types and HTTP status codes without leaking secrets.
"""

from __future__ import annotations

from typing import Any

import httpx2
import openai
import psycopg
import psycopg_pool
import pytest
from fastapi.testclient import TestClient
from langchain.agents.structured_output import StructuredOutputValidationError
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.errors import GraphRecursionError
from pydantic import ValidationError

from neuron_agent.api import main as api_main
from neuron_agent.api.main import app
from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import ToolExecutionError
from neuron_agent.models import factory
from neuron_agent.schemas.agent import AgentResponse
from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter
from neuron_agent.services.agent_service import AgentService

_SECRET_MARKER = "sk-test-secret-should-never-leak"  # noqa: S105 -- leakage-detection fixture, not a real secret
_REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
_429_RESPONSE = httpx2.Response(status_code=429, request=_REQUEST)
_401_RESPONSE = httpx2.Response(status_code=401, request=_REQUEST)
_404_RESPONSE = httpx2.Response(status_code=404, request=_REQUEST)
_500_RESPONSE = httpx2.Response(status_code=500, request=_REQUEST)


class _RealisticErrorModel(GenericFakeChatModel):
    error: Exception

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        raise self.error

    def bind_tools(self, *args: Any, **kwargs: Any) -> Any:
        return self

    def with_structured_output(self, *args: Any, **kwargs: Any) -> Any:
        return self


def _setup_service_with_model_error(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    mock_model = _RealisticErrorModel(error=error, messages=iter([]))
    monkeypatch.setattr(factory, "create_chat_model", lambda s: mock_model)
    settings = api_main.settings.model_copy(update={"provider_max_retries": 0})
    service = AgentService(settings)
    monkeypatch.setattr(api_main, "service", service)


@pytest.fixture(autouse=True)
def _generous_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralize the shared token bucket so unrelated failure tests never hit it.

    `api_main.ip_rate_limiter` is a module-level singleton reused for every request
    in the process, keyed by client host ("testclient" for every TestClient call
    in the whole suite). Without this, the many real requests this file issues
    would exhaust the same bucket other test files already draw from.
    """
    monkeypatch.setattr(
        api_main,
        "ip_rate_limiter",
        InMemoryTokenBucketRateLimiter(capacity=1000, requests_per_window=1000, window_seconds=60),
    )


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (
            openai.APITimeoutError(request=_REQUEST),
            504,
            "provider_timeout_error",
        ),
        (
            openai.RateLimitError(
                message=f"rate limit exceeded: {_SECRET_MARKER}",
                response=_429_RESPONSE,
                body=None,
            ),
            429,
            "rate_limit_error",
        ),
        (
            openai.RateLimitError(
                message=f"quota exceeded: {_SECRET_MARKER}",
                response=_429_RESPONSE,
                body={"code": "insufficient_quota"},
            ),
            503,
            "internal_server_error",
        ),
        (
            openai.APIConnectionError(request=_REQUEST),
            502,
            "internal_server_error",
        ),
        (
            openai.InternalServerError(
                message=f"upstream 500 error: {_SECRET_MARKER}",
                response=_500_RESPONSE,
                body=None,
            ),
            502,
            "internal_server_error",
        ),
        (
            openai.AuthenticationError(
                message=f"invalid api key: {_SECRET_MARKER}",
                response=_401_RESPONSE,
                body=None,
            ),
            500,
            "internal_server_error",
        ),
        (
            openai.NotFoundError(
                message=f"model not found: {_SECRET_MARKER}",
                response=_404_RESPONSE,
                body=None,
            ),
            500,
            "internal_server_error",
        ),
        (
            StructuredOutputValidationError(
                tool_name="AgentAnswer",
                source=ValueError(f"invalid structured output: {_SECRET_MARKER}"),
                ai_message=AIMessage(content="not valid json"),
            ),
            502,
            "internal_server_error",
        ),
        (
            ToolExecutionError(f"tool 'calculator' exceeded 20s timeout: {_SECRET_MARKER}"),
            502,
            "internal_server_error",
        ),
        (
            ToolExecutionError(f"tool 'calculator' failed unexpectedly: {_SECRET_MARKER}"),
            502,
            "internal_server_error",
        ),
        (
            GraphRecursionError(f"Recursion limit of 16 reached: {_SECRET_MARKER}"),
            422,
            "agent_step_limit_exceeded",
        ),
    ],
    ids=[
        "openai-timeout-504",
        "openai-rate-limit-429",
        "openai-quota-503",
        "openai-connection-error-502",
        "openai-internal-server-error-502",
        "openai-auth-error-500",
        "openai-model-not-found-500",
        "structured-output-parse-error",
        "tool-timeout",
        "tool-failure",
        "agent-iteration-limit-exceeded",
    ],
)
def test_agent_invoke_fails_safely_without_leaking_detail(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
    expected_detail: str,
) -> None:
    _setup_service_with_model_error(monkeypatch, error)
    client = TestClient(app)
    response = client.post("/v1/agent/invoke", json={"message": "hi"})
    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}
    assert _SECRET_MARKER not in response.text


@pytest.mark.parametrize(
    "error",
    [
        psycopg.OperationalError(f"connection refused: {_SECRET_MARKER}"),
        psycopg_pool.PoolTimeout(f"pool timeout: {_SECRET_MARKER}"),
    ],
    ids=["psycopg-operational-error", "psycopg-pool-timeout"],
)
def test_agent_invoke_classifies_persistence_failure_safely(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    settings = api_main.settings.model_copy(update={"provider_max_retries": 0})
    service = AgentService(settings)

    async def fail_resolve(*args: object, **kwargs: object) -> str:
        raise error

    monkeypatch.setattr(service, "_resolve_thread", fail_resolve)
    monkeypatch.setattr(api_main, "service", service)

    client = TestClient(app)
    response = client.post("/v1/agent/invoke", json={"message": "hi"})
    assert response.status_code == 503
    assert response.json() == {"detail": "internal_server_error"}
    assert _SECRET_MARKER not in response.text


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError(f"boom: {_SECRET_MARKER}"),
        KeyError(_SECRET_MARKER),
        MemoryError(_SECRET_MARKER),
    ],
    ids=["runtime-error", "key-error", "memory-error"],
)
def test_agent_invoke_hides_unexpected_exceptions(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    _setup_service_with_model_error(monkeypatch, error)
    client = TestClient(app)
    response = client.post("/v1/agent/invoke", json={"message": "hi"})
    assert response.status_code == 500
    assert response.json() == {"detail": "internal_server_error"}
    assert _SECRET_MARKER not in response.text


def test_missing_api_configuration_blocks_settings_construction() -> None:
    with pytest.raises(ValidationError):
        Settings(env="production", default_model="openai:gpt-5.4-mini", openai_api_key=None)


@pytest.mark.parametrize(
    "payload",
    [
        {"message": 12345},
        {"message": "hi", "thread_id": "x" * 256},
        {"message": "hi", "user_id": "x" * 129},
    ],
    ids=["wrong-type", "thread-id-too-long", "user-id-too-long"],
)
def test_agent_invoke_rejects_invalid_request_shapes(payload: dict[str, object]) -> None:
    client = TestClient(app)
    response = client.post("/v1/agent/invoke", json=payload)
    assert response.status_code == 422
    assert response.json() == {"detail": "validation_error"}


def test_agent_invoke_rejects_message_over_max_prompt_chars() -> None:
    client = TestClient(app)
    oversized_message = "x" * (api_main.settings.max_prompt_chars + 1)
    response = client.post("/v1/agent/invoke", json={"message": oversized_message})
    assert response.status_code == 400
    assert response.json() == {"detail": "validation_error"}


def test_agent_invoke_returns_429_when_client_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fast_invoke(self: object, request: object) -> AgentResponse:
        return AgentResponse(
            request_id="request-1",
            thread_id="thread-1",
            answer="ok",
            used_tools=[],
            confidence=1.0,
        )

    monkeypatch.setattr(AgentService, "invoke", fast_invoke)
    monkeypatch.setattr(
        api_main,
        "ip_rate_limiter",
        InMemoryTokenBucketRateLimiter(capacity=1, requests_per_window=1, window_seconds=60),
    )
    client = TestClient(app)
    first = client.post("/v1/agent/invoke", json={"message": "hi"})
    assert first.status_code == 200

    second = client.post("/v1/agent/invoke", json={"message": "hi"})
    assert second.status_code == 429
    assert second.json() == {"detail": "rate_limited"}
