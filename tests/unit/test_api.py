from __future__ import annotations

import uuid

import pytest
import structlog.testing
from fastapi.testclient import TestClient

from neuron_agent.api import main as api_main
from neuron_agent.api.main import app
from neuron_agent.errors.base import (
    AgentExecutionError,
    AuthorizationError,
    ConfigurationError,
    PersistenceError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitError,
    StructuredOutputError,
    ThreadNotFoundError,
    ToolExecutionError,
    ValidationAppError,
)
from neuron_agent.schemas.agent import AgentRequest, AgentResponse
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
        (PersistenceError("db down"), 503, "internal_server_error"),
        (ThreadNotFoundError("missing"), 404, "thread_not_found"),
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


def test_agent_invoke_logs_request_id_thread_id_and_duration_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fast_invoke(self: object, request: object) -> AgentResponse:
        return AgentResponse(
            request_id="request-1", thread_id="thread-1", answer="ok", used_tools=[], confidence=1.0
        )

    monkeypatch.setattr(api_main.AgentService, "invoke", fast_invoke)
    client = TestClient(app)
    with structlog.testing.capture_logs() as logs:
        response = client.post("/v1/agent/invoke", json={"message": "hi"})
    assert response.status_code == 200

    completed = next(log for log in logs if log["event"] == "agent_request_completed")
    assert completed["request_id"] == "request-1"
    assert completed["thread_id"] == "thread-1"
    assert completed["duration_ms"] >= 0


def test_agent_invoke_logs_error_type_and_duration_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def raise_error(self: object, request: object) -> None:
        raise RateLimitError("slow down")

    monkeypatch.setattr(api_main.AgentService, "invoke", raise_error)
    client = TestClient(app)
    with structlog.testing.capture_logs() as logs:
        response = client.post("/v1/agent/invoke", json={"message": "hi"})
    assert response.status_code == 429

    failed = next(log for log in logs if log["event"] == "agent_request_failed")
    assert failed["error_type"] == "RateLimitError"
    assert failed["duration_ms"] >= 0


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


def test_ready_endpoint_reports_ready_when_dependencies_reachable() -> None:
    client = TestClient(app)
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_ready_endpoint_returns_503_when_checkpointer_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def not_ready(self: object) -> bool:
        return False

    monkeypatch.setattr(api_main.AgentService, "is_ready", not_ready)
    client = TestClient(app)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_lifespan_opens_and_closes_service(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def startup(self: object) -> None:
        calls.append("startup")

    async def shutdown(self: object) -> None:
        calls.append("shutdown")

    monkeypatch.setattr(api_main.AgentService, "startup", startup)
    monkeypatch.setattr(api_main.AgentService, "shutdown", shutdown)
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert calls == ["startup"]
    assert calls == ["startup", "shutdown"]


@pytest.mark.parametrize("thread_id", ["thread-1", "not-a-uuid", "", "1234"])
def test_agent_invoke_rejects_malformed_thread_id(thread_id: str) -> None:
    client = TestClient(app)
    response = client.post("/v1/agent/invoke", json={"message": "hi", "thread_id": thread_id})
    assert response.status_code == 422
    assert response.json() == {"detail": "validation_error"}


def test_agent_request_normalizes_thread_id_to_canonical_uuid() -> None:
    upper = "6F9619FF-8B86-D011-B42D-00C04FC964FF"
    assert AgentRequest(message="hi", thread_id=upper).thread_id == upper.lower()


def test_agent_invoke_returns_404_for_unknown_or_foreign_thread() -> None:
    client = TestClient(app)
    created = client.post("/v1/agent/invoke", json={"message": "hi", "user_id": "alice"})
    assert created.status_code == 200
    thread_id = created.json()["thread_id"]

    unknown = client.post(
        "/v1/agent/invoke", json={"message": "hi", "thread_id": str(uuid.uuid4())}
    )
    foreign = client.post(
        "/v1/agent/invoke", json={"message": "hi", "thread_id": thread_id, "user_id": "bob"}
    )
    assert unknown.status_code == foreign.status_code == 404
    assert unknown.json() == foreign.json() == {"detail": "thread_not_found"}

    owner = client.post(
        "/v1/agent/invoke", json={"message": "again", "thread_id": thread_id, "user_id": "alice"}
    )
    assert owner.status_code == 200
    assert owner.json()["thread_id"] == thread_id
