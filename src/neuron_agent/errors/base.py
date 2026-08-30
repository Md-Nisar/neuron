"""Application error taxonomy."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorContext:
    """Machine-readable error metadata."""

    code: str
    retryable: bool = False
    user_visible: bool = True
    alert: bool = False


class AppError(Exception):
    """Base class for expected application failures."""

    context = ErrorContext(code="app_error")


class ValidationAppError(AppError):
    """Invalid caller input."""

    context = ErrorContext(code="validation_error")


class AuthorizationError(AppError):
    """Caller is not allowed to perform an action."""

    context = ErrorContext(code="authorization_error")


class ToolExecutionError(AppError):
    """Tool failed after local validation."""

    context = ErrorContext(code="tool_execution_error", retryable=True)


class ModelExecutionError(AppError):
    """Model or agent execution failed."""

    context = ErrorContext(code="model_execution_error", retryable=True, alert=True)
