"""LangChain model and agent construction boundaries."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from contextvars import ContextVar
from typing import Any

import openai
import structlog
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRetryMiddleware,
    ToolCallRequest,
    wrap_tool_call,
)
from langchain.agents.structured_output import (
    StructuredOutputError as LangChainStructuredOutputError,
)
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphBubbleUp
from langgraph.types import Command

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import (
    AgentExecutionError,
    AppError,
    AuthorizationError,
    ConfigurationError,
    ProviderError,
    ProviderQuotaError,
    ProviderTimeoutError,
    ToolExecutionError,
)
from neuron_agent.errors.base import RateLimitError as AppRateLimitError
from neuron_agent.errors.base import StructuredOutputError as AppStructuredOutputError
from neuron_agent.prompts.loader import load_prompt
from neuron_agent.schemas.agent import AgentAnswer
from neuron_agent.security.authorization import AuthorizationContext, require_permission

logger = structlog.get_logger(__name__)

_TOOL_PERMISSIONS = {"calculator": "tools:calculator"}


def tool_authorization_middleware() -> AgentMiddleware:
    """Filter model-visible tools and enforce the same decision at tool execution."""
    return _ToolAuthorizationMiddleware()


class _ToolAuthorizationMiddleware(AgentMiddleware[Any, Any]):
    """Combine model-side filtering and execution-side authorization hooks."""

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        context = request.runtime.context
        permissions = (
            context.permissions if isinstance(context, AuthorizationContext) else frozenset()
        )
        visible = [
            tool
            for tool in request.tools
            if tool.name == "utc_now"
            or (tool.name in _TOOL_PERMISSIONS and _TOOL_PERMISSIONS[tool.name] in permissions)
        ]
        return await handler(request.override(tools=visible))

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        tool_name = request.tool_call.get("name", "unknown")
        permission = _TOOL_PERMISSIONS.get(tool_name)
        context = request.runtime.context
        permissions = (
            context.permissions if isinstance(context, AuthorizationContext) else frozenset()
        )
        if permission is not None:
            try:
                require_permission(permission, permissions)
            except AuthorizationError:
                logger.warning("authorization_denied", permission=permission, tool=tool_name)
                raise
        elif tool_name != "utc_now":
            logger.warning("authorization_denied", permission="none", tool=tool_name)
            raise AuthorizationError("tool is not authorized")
        return await handler(request)


_RETRYABLE_PROVIDER_ERRORS: tuple[type[Exception], ...] = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)

# OpenAI reports an exhausted account as a 429, like a rate limit, but it never clears on retry.
_QUOTA_ERROR_MARKERS = frozenset({"insufficient_quota", "credit_balance_exhausted"})


def _is_quota_error(exc: Exception) -> bool:
    return isinstance(exc, openai.RateLimitError) and bool(
        _QUOTA_ERROR_MARKERS & {exc.code, exc.type}
    )


_retry_attempts: ContextVar[int] = ContextVar("provider_retry_attempts", default=0)


def reset_retry_attempts() -> None:
    """Zero the provider retry counter for a new agent invocation."""
    _retry_attempts.set(0)


def get_retry_attempts() -> int:
    """Return how many provider calls were retried during the current invocation."""
    return _retry_attempts.get()


def tool_failure_isolation_middleware() -> AgentMiddleware:
    """Log every tool call safely and isolate unclassified failures as `ToolExecutionError`."""

    @wrap_tool_call
    async def isolate_tool_failure(
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        tool_name = request.tool_call.get("name", "unknown")
        started = time.monotonic()
        try:
            result = await handler(request)
        except GraphBubbleUp:
            raise
        except AppError as exc:
            logger.warning(
                "tool_call_failed",
                tool_name=tool_name,
                error_code=exc.context.code,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            raise
        except Exception as exc:
            logger.warning(
                "tool_call_failed",
                tool_name=tool_name,
                error_code=ToolExecutionError.context.code,
                error_type=type(exc).__name__,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            raise ToolExecutionError(f"tool '{tool_name}' failed unexpectedly") from exc
        logger.info(
            "tool_call_succeeded",
            tool_name=tool_name,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        return result

    return isolate_tool_failure


def tool_timeout_middleware(timeout_seconds: float) -> AgentMiddleware:
    """Bound every tool call to `timeout_seconds`, raising ToolExecutionError past it."""

    @wrap_tool_call
    async def enforce_tool_timeout(
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        try:
            return await asyncio.wait_for(handler(request), timeout=timeout_seconds)
        except TimeoutError as exc:
            tool_name = request.tool_call.get("name", "unknown")
            raise ToolExecutionError(
                f"tool '{tool_name}' exceeded {timeout_seconds}s timeout"
            ) from exc

    return enforce_tool_timeout


def _is_retryable_provider_error(exc: Exception) -> bool:
    """Classify raw provider exceptions as retryable without exposing secrets in logs."""
    if not isinstance(exc, _RETRYABLE_PROVIDER_ERRORS) or _is_quota_error(exc):
        return False
    attempt = _retry_attempts.get() + 1
    _retry_attempts.set(attempt)
    logger.warning(
        "provider_call_retry_candidate", error_type=type(exc).__name__, retry_attempt=attempt
    )
    return True


def provider_retry_middleware(settings: Settings) -> AgentMiddleware:
    """Bound retries for transient model-provider failures with backoff and jitter."""
    return ModelRetryMiddleware(
        max_retries=settings.provider_max_retries,
        retry_on=_is_retryable_provider_error,
        on_failure="error",
    )


def create_main_agent(settings: Settings, tools: Sequence[BaseTool]) -> Any:
    """Create the configurable LangChain agent harness."""
    model = create_chat_model(settings)
    return create_agent(
        model=model,
        tools=list(tools),
        system_prompt=load_prompt("system/main.md"),
        response_format=AgentAnswer,
        middleware=[
            tool_authorization_middleware(),
            tool_failure_isolation_middleware(),
            tool_timeout_middleware(settings.tool_timeout_seconds),
            provider_retry_middleware(settings),
        ],
        name="neuron_main_agent",
        context_schema=AuthorizationContext,
        # Runs as a subgraph of the main graph. Never checkpoint its internal state
        # (tool calls/results, intermediate steps): only the main graph's user turns and
        # final answers are thread history (ADR 0005).
        checkpointer=False,
    )


class _FakeChatModel(FakeListChatModel):
    """`FakeListChatModel` that tolerates `create_agent`'s unconditional `bind_tools` call.

    `create_agent` always calls `model.bind_tools(...)` to wire the approved tool set,
    even when `create_chat_model` falls back to this model because no provider key is
    configured. The base `bind_tools` raises `NotImplementedError`; this fake model
    never calls tools, so binding is a no-op that returns itself unchanged.
    """

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        return self


def create_chat_model(settings: Settings) -> ChatOpenAI | _FakeChatModel:
    """Create the chat model with provider-specific runtime limits."""
    if settings.env in {"development", "test"} and settings.openai_api_key is None:
        return _FakeChatModel(responses=["Local test response."])

    provider, model_name = _split_model_identifier(settings.default_model)
    if provider != "openai":
        raise ConfigurationError(f"unsupported model provider: {provider}")

    api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        timeout=settings.request_timeout_seconds,
        max_tokens=settings.max_output_tokens,
        max_retries=0,
    )


def agent_invocation_config(settings: Settings, *, run_id: str | None) -> dict[str, Any]:
    """Return the runtime recursion budget and, when known, the run ID for the agent loop.

    `AgentService` always supplies a run ID. Agent Server and LangGraph Studio inputs carry
    only `messages`, so LangGraph generates the run ID for those.
    """
    config: dict[str, Any] = {"recursion_limit": settings.max_agent_iterations}
    if run_id:
        config["run_id"] = uuid.UUID(run_id)
    return config


def classify_agent_error(exc: Exception) -> AppError:
    """Map a raw exception from the agent harness to the application error taxonomy."""
    if isinstance(exc, AppError):
        return exc
    if _is_quota_error(exc):
        return ProviderQuotaError("model provider has no API credit; add credit to the account")
    if isinstance(exc, openai.RateLimitError):
        return AppRateLimitError("model provider rate limit exceeded")
    if isinstance(exc, openai.APITimeoutError):
        return ProviderTimeoutError("model provider timed out")
    if isinstance(exc, openai.AuthenticationError):
        return ConfigurationError("model provider authentication failed")
    if isinstance(exc, openai.OpenAIError):
        return ProviderError("model provider request failed")
    if isinstance(exc, LangChainStructuredOutputError):
        return AppStructuredOutputError("agent produced invalid structured output")
    return AgentExecutionError("agent execution failed")


def _split_model_identifier(identifier: str) -> tuple[str, str]:
    provider, separator, model_name = identifier.partition(":")
    if not separator or not provider or not model_name:
        raise ConfigurationError("model identifier must use provider:model format")
    return provider, model_name
