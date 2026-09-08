from __future__ import annotations

import pytest

from neuron_agent.errors.base import (
    AgentExecutionError,
    AppError,
    AuthorizationError,
    ConfigurationError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitError,
    StructuredOutputError,
    ToolExecutionError,
    ValidationAppError,
)


@pytest.mark.parametrize(
    ("error_cls", "code", "http_status", "retryable", "user_visible"),
    [
        (ValidationAppError, "validation_error", 400, False, True),
        (AuthorizationError, "authorization_error", 403, False, True),
        (ConfigurationError, "configuration_error", 500, False, False),
        (ProviderError, "provider_error", 502, True, False),
        (RateLimitError, "rate_limit_error", 429, True, True),
        (ProviderTimeoutError, "provider_timeout_error", 504, True, True),
        (ToolExecutionError, "tool_execution_error", 502, True, False),
        (StructuredOutputError, "structured_output_error", 502, True, False),
        (AgentExecutionError, "agent_execution_error", 500, True, False),
    ],
)
def test_error_context_metadata(
    error_cls: type[AppError],
    code: str,
    http_status: int,
    retryable: bool,
    user_visible: bool,
) -> None:
    context = error_cls.context
    assert context.code == code
    assert context.http_status == http_status
    assert context.retryable is retryable
    assert context.user_visible is user_visible


def test_all_taxonomy_errors_are_app_errors() -> None:
    for error_cls in (
        ValidationAppError,
        AuthorizationError,
        ConfigurationError,
        ProviderError,
        RateLimitError,
        ProviderTimeoutError,
        ToolExecutionError,
        StructuredOutputError,
        AgentExecutionError,
    ):
        assert issubclass(error_cls, AppError)
