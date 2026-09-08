"""Deterministic failure-and-resilience regression suite (issue #7).

Each test forces a failure at the same boundary the production code already
classifies it at (AgentService.invoke, the rate limiter, or Settings
construction) and asserts the HTTP contract plus the absence of leaked
internal detail. Deeper unit-level coverage for each error's classification
lives alongside the module that owns it: `tests/unit/test_model_factory.py`,
`tests/graph/test_main_graph.py`, `tests/unit/test_tool_timeout_middleware.py`,
`tests/unit/test_tool_failure_isolation_middleware.py`,
`tests/unit/test_rate_limiter.py`, `tests/unit/test_settings.py`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from neuron_agent.api import main as api_main
from neuron_agent.api.main import app
from neuron_agent.errors.base import (
    AgentExecutionError,
    ConfigurationError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitError,
    StructuredOutputError,
    ToolExecutionError,
)

_SECRET_MARKER = "sk-test-secret-should-never-leak"


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (
            ProviderTimeoutError(f"model provider timed out: {_SECRET_MARKER}"),
            504,
            "provider_timeout_error",
        ),
        (
            RateLimitError(f"model provider rate limit exceeded: {_SECRET_MARKER}"),
            429,
            "rate_limit_error",
        ),
        (
            ProviderError(f"model provider request failed: {_SECRET_MARKER}"),
            502,
            "internal_server_error",
        ),
        (
            ConfigurationError(f"model provider authentication failed: {_SECRET_MARKER}"),
            500,
            "internal_server_error",
        ),
        (
            StructuredOutputError(f"agent produced invalid structured output: {_SECRET_MARKER}"),
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
            AgentExecutionError(f"agent execution failed: {_SECRET_MARKER}"),
            500,
            "internal_server_error",
        ),
    ],
    ids=[
        "provider-timeout",
        "provider-rate-limit-429",
        "provider-5xx",
        "provider-authentication-failure",
        "malformed-structured-output",
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
    async def raise_error(self: object, request: object) -> None:
        raise error

    monkeypatch.setattr(api_main.AgentService, "invoke", raise_error)
    client = TestClient(app)
    response = client.post("/v1/agent/invoke", json={"message": "hi"})
    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}
    assert _SECRET_MARKER not in response.text
