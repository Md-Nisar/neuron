# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""LangChain model and agent construction boundaries."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import openai
import structlog
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    HumanInTheLoopMiddleware,
    InterruptOnConfig,
    ModelFallbackMiddleware,
    ModelRetryMiddleware,
    ToolCallRequest,
    wrap_tool_call,
)
from langchain.agents.structured_output import (
    StructuredOutputError as LangChainStructuredOutputError,
)
from langchain.agents.structured_output import StructuredOutputValidationError
from langchain_anthropic import ChatAnthropic
from langchain_core.exceptions import (
    ModelAuthenticationError,
    ModelError,
    ModelNotFoundError,
    ModelPermissionDeniedError,
    ModelRateLimitError,
    ModelTimeoutError,
)
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.errors import GraphBubbleUp, GraphRecursionError
from langgraph.types import Command
from opentelemetry.trace import Span, SpanKind

from neuron_agent.config.settings import SUPPORTED_PROVIDERS, Settings
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
from neuron_agent.security.input_policy import audit_tool_name
from neuron_agent.tools.registry import ToolRegistry, builtin_registry

logger = structlog.get_logger(__name__)


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
            semconv.GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS,
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
        usage[semconv.GEN_AI_USAGE_CACHE_CREATION_INPUT_TOKENS] += metadata.get(
            "input_token_details", {}
        ).get("cache_creation", 0)
        usage[semconv.GEN_AI_USAGE_REASONING_OUTPUT_TOKENS] += metadata.get(
            "output_token_details", {}
        ).get("reasoning", 0)
    if not reported:
        return None
    span.set_attributes(usage)
    return usage[semconv.GEN_AI_USAGE_INPUT_TOKENS], usage[semconv.GEN_AI_USAGE_OUTPUT_TOKENS]


def tool_authorization_middleware(registry: ToolRegistry | None = None) -> AgentMiddleware:
    """Filter model-visible tools and enforce the same decision at tool execution."""
    return _ToolAuthorizationMiddleware(registry or builtin_registry())


class _ToolAuthorizationMiddleware(AgentMiddleware[Any, Any]):
    """Combine model-side filtering and execution-side authorization hooks."""

    def __init__(self, registry: ToolRegistry) -> None:
        super().__init__()
        self._registry = registry

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        context = request.runtime.context
        permissions = (
            context.permissions if isinstance(context, AuthorizationContext) else frozenset()
        )
        allowed = set(self._registry.visible_to(permissions))
        visible = [tool for tool in request.tools if tool.name in allowed]
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
        spec = self._registry.spec(tool_name)
        permission = spec.scope if spec else None
        audit_name = audit_tool_name(tool_name, self._registry.names())
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
                    resource_id=audit_name,
                    reason="insufficient_scope",
                )
                return _denied_tool_call(request, tool_name)
        elif spec is None:
            metrics.record_policy_block("unknown_tool")
            audit(
                "authorization_denied",
                outcome="denied",
                actor=context.actor if isinstance(context, AuthorizationContext) else None,
                issuer_id=context.issuer_id if isinstance(context, AuthorizationContext) else None,
                action="none",
                resource_type="tool",
                resource_id=audit_name,
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
    retryable = isinstance(exc, _RETRYABLE_PROVIDER_ERRORS) or (
        isinstance(exc, ModelError) and exc.is_retryable
    )
    if not retryable or _is_quota_error(exc):
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


_MAX_STRUCTURED_OUTPUT_RETRIES = 2
_STRUCTURED_OUTPUT_TOOL = AgentAnswer.__name__


def structured_output_retry_middleware() -> AgentMiddleware:
    """Retry an invalid `AgentAnswer` at most twice, then fail as `structured_output_error`.

    `create_agent` answers a bad structured-output tool call with an error message and calls
    the model again, bounded only by the iteration limit; a provider-native schema fails to
    parse inside the model call and is not retried at all. Both are bounded here the same
    way. Every attempt's tokens are counted: a retried tool-call attempt is a response the
    inner layers see, and a discarded parse failure is charged below.
    """
    return _StructuredOutputRetryMiddleware()


class _StructuredOutputRetryMiddleware(AgentMiddleware[Any, Any]):
    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        failed = _failed_answers_this_run(request.messages)
        if failed > _MAX_STRUCTURED_OUTPUT_RETRIES:
            last = next(m for m in reversed(request.messages) if isinstance(m, AIMessage))
            logger.warning("structured_output_retries_exhausted", attempts=failed)
            raise StructuredOutputValidationError(
                _STRUCTURED_OUTPUT_TOOL, ValueError("retries exhausted"), last
            )
        for retry in range(_MAX_STRUCTURED_OUTPUT_RETRIES + 1 - failed):
            try:
                return await handler(request)
            except LangChainStructuredOutputError as exc:
                # An empty reply is the empty-reply retry's, which wraps this one.
                last_try = retry == _MAX_STRUCTURED_OUTPUT_RETRIES - failed
                if last_try or _is_empty_message(exc.ai_message):
                    raise
                _charge_discarded_attempt(request, exc.ai_message)
                logger.warning("structured_output_retry", retry_attempt=failed + retry + 1)
        raise AssertionError("unreachable")  # pragma: no cover


def _failed_answers_this_run(messages: Sequence[Any]) -> int:
    """Structured-output tool calls this run that were answered with an error, not accepted."""
    failed = 0
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, ToolMessage) and message.name == _STRUCTURED_OUTPUT_TOOL:
            failed += 1
    return failed


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


_APPROVAL_PROMPT = "Run this tool? It changes data outside this conversation."


def approval_middleware(registry: ToolRegistry) -> AgentMiddleware | None:
    """Pause the run for a human decision before any `mutating` tool runs (ADR 0009 decision 6).

    All the model's gated calls in one turn are decided together in one interrupt, by `approve`
    or `reject` only: a reviewer cannot edit the call or answer in the tool's place, so what
    runs is exactly what was shown. The run resumes from the thread's checkpoint, which is why
    an agent with gated tools is compiled to inherit its caller's checkpointer.
    """
    gated: dict[str, InterruptOnConfig] = {}
    for spec in registry.mutating():
        config = InterruptOnConfig(
            allowed_decisions=["approve", "reject"], description=_APPROVAL_PROMPT
        )
        if spec.approval_when is not None:
            config["when"] = spec.approval_when
        gated[spec.name] = config
    if not gated:
        return None
    return HumanInTheLoopMiddleware(interrupt_on=dict(gated), interrupt_mode="batched")


def agent_middleware(settings: Settings, registry: ToolRegistry) -> list[AgentMiddleware]:
    """The agent's middleware, outermost first."""
    fallback = model_fallback_middleware(settings)
    approval = approval_middleware(registry)
    return [
        # Outside the tracing layer: each attempt is its own `chat` span.
        empty_reply_retry_middleware(),
        structured_output_retry_middleware(),
        tracing_middleware(settings),
        tool_authorization_middleware(registry),
        *([approval] if approval else []),
        tool_failure_isolation_middleware(),
        tool_timeout_middleware(settings.tool_timeout_seconds),
        # Directly outside the provider retries: a model is retried, then the next is tried.
        *([fallback] if fallback else []),
        provider_retry_middleware(settings),
    ]


def create_main_agent(settings: Settings, registry: ToolRegistry) -> Any:
    """Create the configurable LangChain agent harness with the registry's tools."""
    model = create_chat_model(settings)
    return create_agent(
        model=model,
        tools=registry.tools(),
        system_prompt=load_prompt("system/main.md"),
        response_format=AgentAnswer,
        middleware=agent_middleware(settings, registry),
        name="neuron_main_agent",
        context_schema=AuthorizationContext,
        # Runs as a subgraph of the main graph. Thread history is only the main graph's user
        # turns and final answers (ADR 0005), so without gated tools its internal state (tool
        # calls and results) is not checkpointed. With them it must inherit the main graph's
        # checkpointer (`None`), or an approved call would be lost on resume (ADR 0009).
        checkpointer=None if registry.mutating() else False,
    )


def _tool_name(tool: dict[str, Any] | type | Callable[..., Any] | BaseTool) -> str | None:
    if isinstance(tool, BaseTool):
        return tool.name
    if isinstance(tool, dict):
        function = tool.get("function")
        name = function.get("name") if isinstance(function, dict) else tool.get("name")
        return name if isinstance(name, str) else None
    return getattr(tool, "__name__", None)


class _FakeChatModel(FakeListChatModel):
    """`FakeListChatModel` that tolerates `create_agent`'s unconditional `bind_tools` call.

    `create_agent` always calls `model.bind_tools(...)` to wire the approved tool set,
    even when `create_chat_model` falls back to this model because no provider key is
    configured. The base `bind_tools` raises `NotImplementedError`; this fake model
    never calls tools, so binding is a no-op that returns itself unchanged.

    With `ttft_ms`, `tokens_per_second` or `output_tokens` set it streams one word per
    token after a first-token delay, so load tests see a realistic latency profile.
    """

    ttft_ms: int = 0
    tokens_per_second: int = 0
    output_tokens: int | None = None
    bound_tool_names: tuple[str, ...] = ()

    def _shaped(self) -> bool:
        return bool(self.ttft_ms or self.tokens_per_second or self.output_tokens is not None)

    def _note_to_remember(self, messages: list[BaseMessage]) -> str | None:
        """The text of a `remember: ...` user turn when the memory tool is bound."""
        if "remember" not in self.bound_tool_names or not messages:
            return None
        last = messages[-1]
        if not isinstance(last, HumanMessage) or not isinstance(last.content, str):
            return None
        prefix = "remember:"
        return last.content[len(prefix) :].strip() if last.content.startswith(prefix) else None

    def _words(self) -> list[str]:
        if self.output_tokens is None:
            return [self.responses[0]]
        return ["token"] * self.output_tokens

    def _call(self, *args: Any, **kwargs: Any) -> str:
        if not self._shaped():
            return super()._call(*args, **kwargs)
        words = self._words()
        delay = self.ttft_ms / 1000
        if self.tokens_per_second:
            delay += len(words) / self.tokens_per_second
        time.sleep(delay)
        return " ".join(words)

    async def _agenerate(
        self, messages: list[BaseMessage], *args: Any, **kwargs: Any
    ) -> ChatResult:
        note = self._note_to_remember(messages) if self._shaped() else None
        if note is None:
            return await super()._agenerate(messages, *args, **kwargs)
        await asyncio.sleep(self.ttft_ms / 1000)
        call = {"name": "remember", "args": {"text": note}, "id": uuid.uuid4().hex}
        return ChatResult(generations=[ChatGeneration(message=AIMessage("", tool_calls=[call]))])

    async def _astream(
        self, messages: list[BaseMessage], *args: Any, **kwargs: Any
    ) -> AsyncIterator[ChatGenerationChunk]:
        if not self._shaped():
            async for chunk in super()._astream(messages, *args, **kwargs):
                yield chunk
            return
        note = self._note_to_remember(messages)
        if note is not None:
            # Load scenario (c): a mutating tool call, so the run pauses for approval.
            await asyncio.sleep(self.ttft_ms / 1000)
            call = {"name": "remember", "args": json.dumps({"text": note}), "id": uuid.uuid4().hex}
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[{**call, "index": 0}],
                    chunk_position="last",
                )
            )
            return
        words = self._words()
        await asyncio.sleep(self.ttft_ms / 1000)
        for index, word in enumerate(words):
            last = index == len(words) - 1
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=word if last else f"{word} ",
                    chunk_position="last" if last else None,
                )
            )
            if self.tokens_per_second and not last:
                await asyncio.sleep(1 / self.tokens_per_second)

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        names = tuple(name for tool in tools if isinstance(name := _tool_name(tool), str) and name)
        return self.model_copy(update={"bound_tool_names": names})


# NVIDIA's API catalog is OpenAI-compatible, so both providers share `ChatOpenAI` and the
# `openai` error taxonomy that retries and error classification rely on.
_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"


def create_chat_model(
    settings: Settings, identifier: str | None = None
) -> ChatOpenAI | ChatAnthropic | _FakeChatModel:
    """Create the chat model (default: `APP_DEFAULT_MODEL`) with provider-specific limits."""
    provider, model_name = _split_model_identifier(identifier or settings.default_model)
    if provider not in SUPPORTED_PROVIDERS:
        raise ConfigurationError(f"unsupported model provider: {provider}")

    api_key = settings.provider_api_key(provider)
    if settings.env in {"development", "test"} and api_key is None:
        return _FakeChatModel(
            responses=["Local test response."],
            ttft_ms=settings.fake_model_ttft_ms,
            tokens_per_second=settings.fake_model_tokens_per_second,
            output_tokens=settings.fake_model_output_tokens,
        )

    if provider == "anthropic":
        return ChatAnthropic(
            model=model_name,
            api_key=api_key,
            timeout=settings.request_timeout_seconds,
            max_tokens=settings.max_output_tokens,
            max_retries=0,
        )

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


def model_fallback_middleware(settings: Settings) -> AgentMiddleware | None:
    """Try `APP_FALLBACK_MODELS` in order when the default model's call has failed.

    It sits outside the provider retries, so a model is retried before the next one is tried,
    and each fallback model gets the same retries.
    """
    if not settings.fallback_models:
        return None
    models = [create_chat_model(settings, identifier) for identifier in settings.fallback_models]
    return _ModelFallbackMiddleware(settings.default_model, settings.fallback_models, models)


class _ModelFallbackMiddleware(ModelFallbackMiddleware):
    """`ModelFallbackMiddleware` that counts and logs each switch, with identifiers only."""

    def __init__(self, primary: str, identifiers: Sequence[str], models: Sequence[Any]) -> None:
        super().__init__(*models)
        self._chain = [primary, *identifiers]

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        attempt = 0

        async def counting_handler(req: Any) -> Any:
            nonlocal attempt
            if attempt:
                source, target = self._chain[attempt - 1], self._chain[attempt]
                metrics.record_model_fallback(source, target)
                logger.warning("model_fallback", from_model=source, to_model=target)
            attempt += 1
            return await handler(req)

        return await super().awrap_model_call(request, counting_handler)


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
    # `langchain-core`'s provider-neutral types come first so any provider is classified the
    # same way; the `openai` types stay for errors raised outside a LangChain integration.
    if isinstance(exc, ModelRateLimitError | openai.RateLimitError):
        return AppRateLimitError("model provider rate limit exceeded")
    if isinstance(exc, ModelTimeoutError | openai.APITimeoutError):
        return ProviderTimeoutError("model provider timed out")
    if isinstance(
        exc, ModelAuthenticationError | ModelPermissionDeniedError | openai.AuthenticationError
    ):
        return ConfigurationError("model provider authentication failed")
    if isinstance(exc, ModelNotFoundError | openai.NotFoundError):
        # An unknown model or one the account can't use: retrying never helps.
        return ConfigurationError("model provider has no such model for this account")
    if isinstance(exc, ModelError | openai.OpenAIError):
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
