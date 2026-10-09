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


class AuthenticationError(AppError):
    """Caller credentials are missing or invalid."""

    context = ErrorContext(code="authentication_error", http_status=401)


class AuthenticationUnavailableError(AppError):
    """The identity provider's signing keys are temporarily unavailable."""

    context = ErrorContext(
        code="authentication_unavailable", http_status=503, retryable=True, user_visible=False
    )


class ThreadNotFoundError(AppError):
    """Thread does not exist or belongs to another user (deliberately indistinguishable)."""

    context = ErrorContext(code="thread_not_found", http_status=404)


class ThreadBusyError(AppError):
    """Another run is already in flight on this thread (ADR 0005 reject strategy)."""

    context = ErrorContext(code="thread_busy", http_status=409, retryable=True)


class ExportTooLargeError(AppError):
    """A user export page exceeds the configured response-size cap."""

    context = ErrorContext(code="export_too_large", http_status=413)


class CapacityError(AppError):
    """The process is at its concurrent-stream limit."""

    context = ErrorContext(code="too_many_streams", http_status=503, retryable=True)


class ConcurrentRunsExceededError(AppError):
    """Caller exceeded its concurrent invoke/stream run allowance."""

    context = ErrorContext(code="too_many_concurrent_runs", http_status=429, retryable=True)


class QuotaExceededError(AppError):
    """Caller exceeded the rolling provider-token budget."""

    context = ErrorContext(code="quota_exceeded", http_status=429, retryable=True)

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("user token budget exceeded")
        self.retry_after_seconds = max(1, retry_after_seconds)


class RunTimeoutError(AppError):
    """A whole agent run exceeded `APP_RUN_TIMEOUT_SECONDS`."""

    context = ErrorContext(code="run_timeout", http_status=504, retryable=True)


class ShuttingDownError(AppError):
    """The server is shutting down; the run was stopped."""

    context = ErrorContext(code="service_shutting_down", http_status=503, retryable=True)


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


class ProviderQuotaError(AppError):
    """Model provider account has no remaining credit or quota; retrying cannot help."""

    context = ErrorContext(
        code="provider_quota_exhausted", http_status=503, user_visible=False, alert=True
    )


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


class PersistenceError(AppError):
    """Thread persistence backend (checkpointer) is unavailable or failed."""

    context = ErrorContext(
        code="persistence_error",
        http_status=503,
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
