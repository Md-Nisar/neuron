"""LangChain model and agent construction boundaries."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
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
from langgraph.errors import GraphBubbleUp, GraphRecursionError
from langgraph.types import Command
from opentelemetry.trace import Span, SpanKind

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import (
    AgentExecutionError,
    AgentStepLimitError,
    AppError,
    AuthorizationError,
    ConfigurationError,
    ProviderError,
    ProviderQuotaError,
    ProviderTimeoutError,
    ToolExecutionError,
    ValidationAppError,
)
from neuron_agent.errors.base import RateLimitError as AppRateLimitError
from neuron_agent.errors.base import StructuredOutputError as AppStructuredOutputError
from neuron_agent.observability import metrics, semconv, telemetry
from neuron_agent.observability.audit import audit
from neuron_agent.prompts.loader import load_prompt
from neuron_agent.schemas.agent import AgentAnswer
from neuron_agent.security.authorization import AuthorizationContext, require_permission

logger = structlog.get_logger(__name__)

_TOOL_PERMISSIONS = {"calculator": "tools:calculator"}

# Fixed text for a rejected tool input: the tool's own message can carry the model's input.
_TOOL_INPUT_ERROR = (
    "Error: the input to this tool was invalid. Correct it, or answer without the tool."
)
# Fixed text for a denied tool call: it names nothing the model or the user chose.
_TOOL_DENIED = "Error: this tool call was denied. Answer without the tool."
_ERROR_CODE_KEY = "error_code"


def tracing_middleware(settings: Settings) -> AgentMiddleware:
    """Trace each model call as `chat {model}` and each tool call as `execute_tool {tool}`.

    It runs outermost, so a model span covers its retries and a tool span shows authorization
    denials. Spans carry names, counts and error codes only, never messages or tool
    arguments and results (ADR 0007).
    """
    return _TracingMiddleware(settings)


class _TracingMiddleware(AgentMiddleware[Any, Any]):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._provider, self._model = _split_model_identifier(settings.default_model)

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        attributes = {
            semconv.GEN_AI_OPERATION_NAME: semconv.OPERATION_CHAT,
            semconv.GEN_AI_PROVIDER_NAME: self._provider,
            semconv.GEN_AI_REQUEST_MODEL: self._model,
        }
        name = f"{semconv.OPERATION_CHAT} {self._model}"
        started = time.monotonic()
        error_type: str | None = None
        usage: tuple[int, int] | None = None
        with telemetry.start_span(name, kind=SpanKind.CLIENT, attributes=attributes) as span:
            retries_before = get_retry_attempts()
            try:
                response = await handler(request)
            except Exception as exc:
                error_type = classify_agent_error(exc).context.code
                telemetry.record_error(span, error_type)
                raise
            else:
                messages = getattr(response, "result", [])
                usage = _record_model_response(
                    span, messages if isinstance(messages, list) else [messages]
                )
                return response
            finally:
                span.set_attribute(
                    semconv.NEURON_RETRY_COUNT, get_retry_attempts() - retries_before
                )
                metrics.record_model_call(
                    time.monotonic() - started,
                    provider=self._provider,
                    model=self._model,
                    error_type=error_type,
                    input_tokens=usage[0] if usage else None,
                    output_tokens=usage[1] if usage else None,
                )

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        # The registered tool's name, not the model's: an unknown name is model output.
        tool_name = request.tool.name if request.tool is not None else "unknown"
        attributes = {
            semconv.GEN_AI_OPERATION_NAME: semconv.OPERATION_EXECUTE_TOOL,
            semconv.GEN_AI_TOOL_NAME: tool_name,
        }
        name = f"{semconv.OPERATION_EXECUTE_TOOL} {tool_name}"
        started = time.monotonic()
        outcome = "error"
        error_type: str | None = None
        with telemetry.start_span(name, attributes=attributes) as span:
            try:
                result = await handler(request)
            except GraphBubbleUp:
                # Control flow (an interrupt), not a tool call that finished.
                outcome = "interrupted"
                raise
            except Exception as exc:
                outcome = "denied" if isinstance(exc, AuthorizationError) else "error"
                error_type = classify_agent_error(exc).context.code
                span.set_attribute(semconv.NEURON_OUTCOME, outcome)
                telemetry.record_error(span, error_type)
                raise
            else:
                if isinstance(result, ToolMessage) and result.status == "error":
                    code = result.additional_kwargs.get(_ERROR_CODE_KEY)
                    error_type = code or ToolExecutionError.context.code
                    if error_type == AuthorizationError.context.code:
                        outcome = "denied"
                    span.set_attribute(semconv.NEURON_OUTCOME, outcome)
                    telemetry.record_error(span, error_type)
                else:
                    outcome = "success"
                    span.set_attribute(semconv.NEURON_OUTCOME, outcome)
                return result
            finally:
                metrics.record_tool_call(
                    time.monotonic() - started,
                    tool=tool_name,
                    outcome=outcome,
                    error_type=error_type,
                )


def _record_model_response(span: Span, messages: list[Any]) -> tuple[int, int] | None:
    """Set the response model and token usage by kind, summed over the response messages.

    Returns the input and output token counts, or None when the provider reported no usage.
    """
    usage = dict.fromkeys(
        (
            semconv.GEN_AI_USAGE_INPUT_TOKENS,
            semconv.GEN_AI_USAGE_OUTPUT_TOKENS,
            semconv.GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS,
            semconv.GEN_AI_USAGE_REASONING_OUTPUT_TOKENS,
        ),
        0,
    )
    reported = False
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        if model := message.response_metadata.get("model_name"):
            span.set_attribute(semconv.GEN_AI_RESPONSE_MODEL, str(model))
        metadata = message.usage_metadata
        if metadata is None:
            continue
        reported = True
        usage[semconv.GEN_AI_USAGE_INPUT_TOKENS] += metadata.get("input_tokens", 0)
        usage[semconv.GEN_AI_USAGE_OUTPUT_TOKENS] += metadata.get("output_tokens", 0)
        usage[semconv.GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS] += metadata.get(
            "input_token_details", {}
        ).get("cache_read", 0)
        usage[semconv.GEN_AI_USAGE_REASONING_OUTPUT_TOKENS] += metadata.get(
            "output_token_details", {}
        ).get("reasoning", 0)
    if not reported:
        return None
    span.set_attributes(usage)
    return usage[semconv.GEN_AI_USAGE_INPUT_TOKENS], usage[semconv.GEN_AI_USAGE_OUTPUT_TOKENS]


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
        response = await handler(request.override(tools=visible))
        if isinstance(context, AuthorizationContext) and context.usage is not None:
            messages = getattr(response, "result", [])
            if not isinstance(messages, list):
                messages = [messages]
            for message in messages:
                metadata = getattr(message, "response_metadata", None)
                model = metadata.get("model_name") if isinstance(metadata, dict) else None
                context.usage.record(
                    getattr(message, "usage_metadata", None), str(model) if model else None
                )
        return response

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
                metrics.record_policy_block("insufficient_scope")
                audit(
                    "authorization_denied",
                    outcome="denied",
                    actor=context.actor if isinstance(context, AuthorizationContext) else None,
                    issuer_id=context.issuer_id
                    if isinstance(context, AuthorizationContext)
                    else None,
                    action=permission,
                    resource_type="tool",
                    resource_id=tool_name,
                    reason="insufficient_scope",
                )
                return _denied_tool_call(request, tool_name)
        elif tool_name != "utc_now":
            metrics.record_policy_block("unknown_tool")
            audit(
                "authorization_denied",
                outcome="denied",
                actor=context.actor if isinstance(context, AuthorizationContext) else None,
                issuer_id=context.issuer_id if isinstance(context, AuthorizationContext) else None,
                action="none",
                resource_type="tool",
                resource_id=tool_name,
                reason="unknown_tool",
            )
            return _denied_tool_call(request, tool_name)
        return await handler(request)


def _denied_tool_call(request: Any, tool_name: str) -> ToolMessage:
    """The tool never runs; the model gets fixed text, so it can answer without the tool."""
    return ToolMessage(
        content=_TOOL_DENIED,
        tool_call_id=request.tool_call["id"],
        name=tool_name,
        status="error",
        additional_kwargs={_ERROR_CODE_KEY: AuthorizationError.context.code},
    )


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


@dataclass
class _RetryCounter:
    count: int = 0


# A mutable counter, not an int: retries are counted in a child context of the agent loop,
# and a `set` there would never be seen by the invocation that reads the count.
_retry_counter: ContextVar[_RetryCounter | None] = ContextVar(
    "provider_retry_counter", default=None
)


def reset_retry_attempts() -> None:
    """Start a new provider retry counter for a new agent invocation."""
    _retry_counter.set(_RetryCounter())


def get_retry_attempts() -> int:
    """Return how many provider calls were retried during the current invocation."""
    counter = _retry_counter.get()
    return counter.count if counter is not None else 0


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
            if isinstance(exc, ValidationAppError):
                # The model chose the input, so let it correct the call or answer without it.
                return ToolMessage(
                    content=_TOOL_INPUT_ERROR,
                    tool_call_id=request.tool_call["id"],
                    name=tool_name,
                    status="error",
                    additional_kwargs={_ERROR_CODE_KEY: exc.context.code},
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
    counter = _retry_counter.get()
    if counter is None:
        counter = _RetryCounter()
        _retry_counter.set(counter)
    counter.count += 1
    attempt = counter.count
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


_MAX_EMPTY_REPLY_RETRIES = 2


def empty_reply_retry_middleware() -> AgentMiddleware:
    """Call the model again, up to twice, when it replies with nothing usable.

    A reasoning model can spend all of `APP_MAX_OUTPUT_TOKENS` thinking (finish reason
    `length`) and end the reply with no text and no tool call, so it never emits the
    `AgentAnswer` output tool. That would otherwise end the run as `structured_output_error`.
    Sampling is not deterministic, so a fresh call usually completes. The retry is bounded and
    only repeats the model call: tools, authorization and the step limit are untouched.
    """
    return _EmptyReplyRetryMiddleware()


class _EmptyReplyRetryMiddleware(AgentMiddleware[Any, Any]):
    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        for retry in range(_MAX_EMPTY_REPLY_RETRIES + 1):
            try:
                response = await handler(request)
            except LangChainStructuredOutputError as exc:
                # Under ProviderStrategy an empty reply fails to parse inside the model call.
                if retry == _MAX_EMPTY_REPLY_RETRIES or not _is_empty_message(exc.ai_message):
                    raise
                # The discarded attempt still spent tokens; the inner layer never saw a response.
                _charge_discarded_attempt(request, exc.ai_message)
            else:
                if retry == _MAX_EMPTY_REPLY_RETRIES or not _is_empty_reply(response):
                    return response
            logger.warning("model_empty_reply_retry", retry_attempt=retry + 1)
        raise AssertionError("unreachable")  # pragma: no cover


def _charge_discarded_attempt(request: Any, message: AIMessage) -> None:
    context = request.runtime.context
    if isinstance(context, AuthorizationContext) and context.usage is not None:
        model = message.response_metadata.get("model_name")
        context.usage.record(message.usage_metadata, str(model) if model else None)


def _is_empty_reply(response: Any) -> bool:
    """Whether the model's reply has no text and no tool call, valid or truncated."""
    messages = getattr(response, "result", None)
    return isinstance(messages, list) and len(messages) == 1 and _is_empty_message(messages[0])


def _is_empty_message(reply: Any) -> bool:
    return (
        isinstance(reply, AIMessage)
        and not reply.tool_calls
        and not reply.invalid_tool_calls
        and not reply.text.strip()
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
            # Outside the tracing layer: each attempt is its own `chat` span.
            empty_reply_retry_middleware(),
            tracing_middleware(settings),
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


# NVIDIA's API catalog is OpenAI-compatible, so both providers share `ChatOpenAI` and the
# `openai` error taxonomy that retries and error classification rely on.
_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


def create_chat_model(settings: Settings) -> ChatOpenAI | _FakeChatModel:
    """Create the chat model with provider-specific runtime limits."""
    provider, model_name = _split_model_identifier(settings.default_model)
    if provider not in {"openai", "nvidia"}:
        raise ConfigurationError(f"unsupported model provider: {provider}")

    api_key = settings.provider_api_key(provider)
    if settings.env in {"development", "test"} and api_key is None:
        return _FakeChatModel(responses=["Local test response."])

    provider_options: dict[str, Any] = {}
    if provider == "nvidia":
        # ChatOpenAI only reports streamed token usage by default for OpenAI's own endpoint;
        # per-user token budgets need it here too.
        provider_options = {"base_url": _NVIDIA_BASE_URL, "stream_usage": True}
    return ChatOpenAI(
        model=model_name,
        api_key=api_key.get_secret_value() if api_key else None,
        timeout=settings.request_timeout_seconds,
        max_tokens=settings.max_output_tokens,
        max_retries=0,
        **provider_options,
    )


def agent_invocation_config(settings: Settings, *, run_id: str | None) -> dict[str, Any]:
    """Return the runtime recursion budget and, when known, the run ID for the agent loop.

    `APP_MAX_AGENT_ITERATIONS` counts model calls. LangGraph's `recursion_limit` counts steps,
    and every model call and every tool call is one, so N model calls need 2N steps. The
    empty-reply retry runs inside one model step, so a step can make up to three provider calls.

    `AgentService` always supplies a run ID. Agent Server and LangGraph Studio inputs carry
    only `messages`, so LangGraph generates the run ID for those.
    """
    config: dict[str, Any] = {"recursion_limit": 2 * settings.max_agent_iterations}
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
    if isinstance(exc, openai.NotFoundError):
        # An unknown model or one the account can't use: retrying never helps.
        return ConfigurationError("model provider has no such model for this account")
    if isinstance(exc, openai.OpenAIError):
        return ProviderError("model provider request failed")
    if isinstance(exc, GraphRecursionError):
        return AgentStepLimitError("agent did not finish within the iteration limit")
    if isinstance(exc, LangChainStructuredOutputError):
        return AppStructuredOutputError("agent produced invalid structured output")
    return AgentExecutionError("agent execution failed")


def _split_model_identifier(identifier: str) -> tuple[str, str]:
    provider, separator, model_name = identifier.partition(":")
    if not separator or not provider or not model_name:
        raise ConfigurationError("model identifier must use provider:model format")
    return provider, model_name
