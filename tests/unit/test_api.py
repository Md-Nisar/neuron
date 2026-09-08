from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from neuron_agent.api import main as api_main
from neuron_agent.api.main import app
from neuron_agent.errors.base import (
    AgentExecutionError,
    AuthorizationError,
    ConfigurationError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitError,
    StructuredOutputError,
    ToolExecutionError,
    ValidationAppError,
)
from neuron_agent.schemas.agent import AgentResponse
from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter


def test_live_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_agent_invoke_rejects_empty_message() -> None:
    client = TestClient(app)
    response = client.post("/v1/agent/invoke", json={"message": ""})
    assert response.status_code == 422
    assert response.json() == {"detail": "validation_error"}


def test_agent_invoke_rejects_unexpected_fields() -> None:
    client = TestClient(app)
    response = client.post("/v1/agent/invoke", json={"message": "hi", "unexpected_field": "value"})
    assert response.status_code == 422
    assert response.json() == {"detail": "validation_error"}


def test_agent_invoke_rejects_malformed_json() -> None:
    client = TestClient(app)
    response = client.post(
        "/v1/agent/invoke",
        content=b"{not valid json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "validation_error"}


def test_agent_invoke_rejects_oversized_body_via_content_length() -> None:
    client = TestClient(app)
    oversized = api_main.settings.max_request_body_bytes + 1
    response = client.post(
        "/v1/agent/invoke",
        content=b"x" * oversized,
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "payload_too_large"}


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (ValidationAppError("bad input"), 400, "validation_error"),
        (AuthorizationError("not allowed"), 403, "authorization_error"),
        (RateLimitError("slow down"), 429, "rate_limit_error"),
        (ProviderTimeoutError("timed out"), 504, "provider_timeout_error"),
        (ConfigurationError("bad config"), 500, "internal_server_error"),
        (ProviderError("upstream failed"), 502, "internal_server_error"),
        (ToolExecutionError("tool failed"), 502, "internal_server_error"),
        (StructuredOutputError("bad structured output"), 502, "internal_server_error"),
        (AgentExecutionError("agent failed"), 500, "internal_server_error"),
    ],
)
def test_agent_invoke_maps_app_errors_to_http(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
    expected_detail: str,
) -> None:
    async def raise_error(self: object, request: object) -> None:
        raise error

    monkeypatch.setattr(api_main.AgentService, "invoke", raise_error)
    client = TestClient(app)
    response = client.post("/v1/agent/invoke", json={"message": "hi"})
    assert response.status_code == expected_status
    assert response.json()["detail"] == expected_detail


def test_agent_invoke_maps_unexpected_exception_to_500(monkeypatch: pytest.MonkeyPatch) -> None:
    async def raise_error(self: object, request: object) -> None:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(api_main.AgentService, "invoke", raise_error)
    client = TestClient(app)
    response = client.post("/v1/agent/invoke", json={"message": "hi"})
    assert response.status_code == 500
    assert response.json()["detail"] == "internal_server_error"


def test_agent_invoke_returns_429_when_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fast_invoke(self: object, request: object) -> AgentResponse:
        return AgentResponse(
            request_id="request-1", thread_id="thread-1", answer="ok", used_tools=[], confidence=1.0
        )

    monkeypatch.setattr(api_main.AgentService, "invoke", fast_invoke)
    monkeypatch.setattr(
        api_main,
        "rate_limiter",
        InMemoryTokenBucketRateLimiter(capacity=1, requests_per_window=1, window_seconds=60),
    )
    client = TestClient(app)
    first = client.post("/v1/agent/invoke", json={"message": "hi"})
    assert first.status_code == 200

    second = client.post("/v1/agent/invoke", json={"message": "hi"})
    assert second.status_code == 429
    assert second.json() == {"detail": "rate_limited"}
    assert 1 <= int(second.headers["Retry-After"]) <= 60


def test_health_endpoints_are_not_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api_main,
        "rate_limiter",
        InMemoryTokenBucketRateLimiter(capacity=1, requests_per_window=1, window_seconds=60),
    )
    client = TestClient(app)
    for _ in range(3):
        response = client.get("/health/live")
        assert response.status_code == 200
