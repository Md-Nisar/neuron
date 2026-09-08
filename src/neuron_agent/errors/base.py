"""Application error taxonomy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorContext:
    """Machine-readable error metadata driving centralized HTTP mapping."""

    code: str
    http_status: int = 500
    retryable: bool = False
    user_visible: bool = True
    alert: bool = False


class AppError(Exception):
    """Base class for expected application failures."""

    context = ErrorContext(code="app_error")


class ValidationAppError(AppError):
    """Invalid caller input."""

    context = ErrorContext(code="validation_error", http_status=400)


class AuthorizationError(AppError):
    """Caller is not allowed to perform an action."""

    context = ErrorContext(code="authorization_error", http_status=403)


class ConfigurationError(AppError):
    """Application or provider misconfiguration."""

    context = ErrorContext(
        code="configuration_error", http_status=500, user_visible=False, alert=True
    )


class ProviderError(AppError):
    """Model provider returned an unexpected failure."""

    context = ErrorContext(
        code="provider_error", http_status=502, retryable=True, user_visible=False, alert=True
    )


class RateLimitError(AppError):
    """Model provider rejected the request due to rate limiting."""

    context = ErrorContext(code="rate_limit_error", http_status=429, retryable=True)


class ProviderTimeoutError(AppError):
    """Model provider did not respond within the configured timeout."""

    context = ErrorContext(code="provider_timeout_error", http_status=504, retryable=True)


class ToolExecutionError(AppError):
    """Tool failed after local validation."""

    context = ErrorContext(
        code="tool_execution_error",
        http_status=502,
        retryable=True,
        user_visible=False,
        alert=True,
    )


class StructuredOutputError(AppError):
    """Agent failed to produce a valid structured response."""

    context = ErrorContext(
        code="structured_output_error",
        http_status=502,
        retryable=True,
        user_visible=False,
        alert=True,
    )


class AgentExecutionError(AppError):
    """Agent execution failed for a reason not otherwise classified."""

    context = ErrorContext(
        code="agent_execution_error",
        http_status=500,
        retryable=True,
        user_visible=False,
        alert=True,
    )
