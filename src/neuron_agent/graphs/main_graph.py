# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Main LangGraph workflow."""

from __future__ import annotations

import time
from typing import Any

import structlog
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    ToolMessage,
    trim_messages,
)
from langchain_core.messages.utils import count_tokens_approximately
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import get_runtime

from neuron_agent.agents.factory import build_agent
from neuron_agent.config.settings import Settings, get_settings
from neuron_agent.errors.base import AppError
from neuron_agent.errors.base import StructuredOutputError as AppStructuredOutputError
from neuron_agent.models.factory import (
    agent_invocation_config,
    classify_agent_error,
    get_retry_attempts,
    reset_retry_attempts,
)
from neuron_agent.observability import metrics, semconv, telemetry
from neuron_agent.observability.audit import audit
from neuron_agent.observability.langsmith_governance import configure_langsmith
from neuron_agent.observability.logging import configure_logging
from neuron_agent.observability.telemetry import configure_telemetry
from neuron_agent.schemas.agent import AgentAnswer
from neuron_agent.security.authorization import AuthorizationContext, TokenUsageAccumulator
from neuron_agent.security.output_policy import (
    POLICY_RULE,
    SYSTEM_PROMPT_REFUSAL,
    leaks_system_prompt,
)
from neuron_agent.state.main import MainGraphState
from neuron_agent.tools.registry import ToolRegistry

logger = structlog.get_logger(__name__)


async def call_agent(
    state: MainGraphState,
    *,
    agent: Any,
    settings: Settings | None = None,
    authorization: AuthorizationContext | None = None,
) -> dict[str, Any]:
    """Invoke the LangChain agent and normalize its output into application state.

    When `user_message` is set (the `AgentService` path), the new `HumanMessage` and the
    final `AIMessage` are committed to `messages` together, so a failed run leaves no
    dangling user turn in the thread (ADR 0005). Inputs that already carry the user turn in
    `messages` (Agent Server, LangGraph Studio) are supported unchanged.
    """
    resolved_settings = settings or get_settings()
    request_id = state.get("request_id")
    thread_id = state.get("thread_id")
    run_id = state.get("run_id")
    model = resolved_settings.default_model
    new_turn: list[BaseMessage] = []
    user_message = state.get("user_message")
    if user_message:
        new_turn.append(HumanMessage(content=user_message))
    stored = list(state.get("messages", []))
    logger.info(
        "agent_execution_started",
        request_id=request_id,
        thread_id=thread_id,
        run_id=run_id,
        model=model,
        max_agent_iterations=resolved_settings.max_agent_iterations,
        # Conversation position: 1-based user turn number and stored history size.
        turn=_turn(state),
        history_messages=len(stored),
    )
    history = bound_model_history(
        [*stored, *new_turn], max_tokens=resolved_settings.max_history_tokens
    )
    if len(history) < len(stored) + len(new_turn):
        logger.info(
            "history_trimmed",
            messages_total=len(stored) + len(new_turn),
            messages_sent=len(history),
            max_history_tokens=resolved_settings.max_history_tokens,
        )
    reset_retry_attempts()
    started = time.monotonic()
    try:
        invocation: dict[str, Any] = {
            "config": agent_invocation_config(resolved_settings, run_id=run_id),
        }
        if authorization is not None:
            invocation["context"] = authorization
        result = await agent.ainvoke({"messages": history}, **invocation)
        answer = _final_answer(result, run_messages=result.get("messages", [])[len(history) :])
    except GraphBubbleUp:
        # A tool is waiting for a human decision: the run pauses, it did not fail.
        raise
    except Exception as exc:  # noqa: BLE001
        error = classify_agent_error(exc)
        log = logger.exception if error.context.alert else logger.warning
        log(
            "agent_execution_failed",
            request_id=request_id,
            thread_id=thread_id,
            run_id=run_id,
            model=model,
            error_code=error.context.code,
            error_type=type(exc).__name__,
            retryable=error.context.retryable,
            retry_count=get_retry_attempts(),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        raise error from exc

    answer = _guard_answer(answer, state, authorization)
    logger.info(
        "agent_execution_completed",
        request_id=request_id,
        thread_id=thread_id,
        run_id=run_id,
        model=model,
        retry_count=get_retry_attempts(),
        duration_ms=round((time.monotonic() - started) * 1000, 2),
    )
    # Only the user turn and the final answer are persisted; the agent's intermediate
    # tool-call/tool-result messages stay inside this run.
    turn = [*new_turn, AIMessage(content=answer.answer)]
    evicted = evict_oldest_turns(
        stored, incoming=len(turn), limit=resolved_settings.max_thread_messages
    )
    return {
        "messages": [*(RemoveMessage(id=m.id) for m in evicted if m.id), *turn],
        "answer": answer,
        "user_message": None,
    }


def _guard_answer(
    answer: AgentAnswer, state: MainGraphState, authorization: AuthorizationContext | None
) -> AgentAnswer:
    """Replace an answer that reproduces the system prompt with a fixed refusal.

    Runs for every path that produces an answer (`AgentService.invoke`, streaming and Agent
    Server), before the answer is stored; live Agent Server message streams are not covered.
    Logs and audits the block without any text.
    """
    if not leaks_system_prompt(answer.answer):
        return answer
    metrics.record_policy_block(POLICY_RULE)
    logger.warning(
        "system_prompt_disclosure_blocked",
        request_id=state.get("request_id"),
        thread_id=state.get("thread_id"),
        run_id=state.get("run_id"),
        answer_chars=len(answer.answer),
    )
    audit(
        "output_blocked",
        outcome="denied",
        actor=authorization.actor if authorization else None,
        issuer_id=authorization.issuer_id if authorization else None,
        action="agent:invoke",
        resource_type="agent_output",
        request_id=state.get("request_id"),
        run_id=state.get("run_id"),
        reason=POLICY_RULE,
    )
    return answer.model_copy(
        update={
            "answer": SYSTEM_PROMPT_REFUSAL,
            "refused": True,
            "clarification_needed": False,
            "confidence": min(answer.confidence, 0.5),
        }
    )


def _turn(state: MainGraphState) -> int:
    """The run's 1-based user turn number in its thread."""
    stored = sum(isinstance(m, HumanMessage) for m in state.get("messages", []))
    return stored + (1 if state.get("user_message") else 0)


def _final_answer(result: dict[str, Any], *, run_messages: list[BaseMessage]) -> AgentAnswer:
    """The run's answer, with `used_tools` taken from the tool calls that actually ran.

    The model's own `used_tools` is not trusted: it can omit tools it called or list ones it
    did not, such as the `AgentAnswer` structured-output tool.
    """
    structured = result.get("structured_response")
    if isinstance(structured, AgentAnswer):
        answer = structured
    else:
        output_text = str(result["messages"][-1].content) if result.get("messages") else ""
        if not output_text.strip():
            raise AppStructuredOutputError("agent returned an empty answer")
        answer = AgentAnswer(answer=output_text, confidence=0.5)
    return answer.model_copy(update={"used_tools": _tools_run(run_messages)})


def _tools_run(messages: list[BaseMessage]) -> list[str]:
    """Names of the tools that ran successfully, in first-use order."""
    names = {
        call["id"]: call["name"]
        for message in messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    }
    used: list[str] = []
    for message in messages:
        if not isinstance(message, ToolMessage) or message.status == "error":
            continue
        name = names.get(message.tool_call_id) or message.name
        if name and name != AgentAnswer.__name__ and name not in used:
            used.append(name)
    return used


def bound_model_history(messages: list[BaseMessage], *, max_tokens: int) -> list[BaseMessage]:
    """Keep the newest messages within `max_tokens`, starting on a user turn.

    Trimming keeps a contiguous suffix that begins with a `HumanMessage`, so a tool call is
    never separated from its result. The newest message (the current user turn) is always
    kept, even when it alone exceeds the budget; `APP_MAX_PROMPT_CHARS` bounds it instead.
    """
    trimmed = trim_messages(
        messages,
        max_tokens=max_tokens,
        token_counter=count_tokens_approximately,
        strategy="last",
        start_on="human",
        allow_partial=False,
    )
    return trimmed or messages[-1:]


def evict_oldest_turns(
    stored: list[BaseMessage], *, incoming: int, limit: int
) -> list[BaseMessage]:
    """Return the oldest stored messages to drop so the thread holds at most `limit` messages.

    Whole turns are dropped: the remaining history always starts on a `HumanMessage`.
    """
    cut = len(stored) + incoming - limit
    if cut <= 0:
        return []
    while cut < len(stored) and not isinstance(stored[cut], HumanMessage):
        cut += 1
    return stored[:cut]


def build_graph(
    settings: Settings | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    registry: ToolRegistry | None = None,
) -> Any:
    """Build and compile the graph, persisting thread state when a checkpointer is given.

    `registry` is the tool set (the builtin tools when omitted).
    """
    resolved_settings = settings or get_settings()
    if registry is not None and checkpointer is None and registry.mutating():
        # A run can pause only where its state is saved: without a checkpointer (stateless
        # deployments, Agent Server) a gated tool would be lost, so it is not offered.
        logger.warning("approval_tools_disabled", reason="no_checkpointer")
        registry = registry.without_mutating()
    agent = (
        build_agent(resolved_settings, registry)
        if registry is not None
        else build_agent(resolved_settings)
    )

    async def agent_node(state: MainGraphState, config: RunnableConfig) -> dict[str, Any]:
        context = get_runtime().context
        authorization = _run_authorization(context, config, resolved_settings)
        attributes = _run_span_attributes(
            state, config, from_service=isinstance(context, AuthorizationContext)
        )
        name = f"{semconv.OPERATION_INVOKE_AGENT} {semconv.AGENT_NAME}"
        started = time.monotonic()
        outcome = "cancelled"
        error_type: str | None = None
        with telemetry.start_span(name, attributes=attributes) as span:
            try:
                result = await call_agent(
                    state, agent=agent, settings=resolved_settings, authorization=authorization
                )
            except GraphBubbleUp:
                outcome = "interrupted"
                raise
            except AppError as exc:
                outcome, error_type = "error", exc.context.code
                telemetry.record_error(span, error_type)
                raise
            else:
                outcome = "success"
                return result
            finally:
                metrics.record_run(
                    time.monotonic() - started, outcome=outcome, error_type=error_type
                )
                # `AgentService` counts its own runs' errors where it reports them.
                if error_type and not isinstance(context, AuthorizationContext):
                    metrics.record_error(error_type)
                # `AgentService` logs its own runs' usage when it charges the budget.
                if not isinstance(context, AuthorizationContext) and authorization.usage:
                    logger.info(
                        "model_token_usage",
                        run_id=attributes.get(semconv.NEURON_RUN_ID),
                        owner_key_prefix=attributes.get(semconv.NEURON_OWNER_KEY_PREFIX),
                        **authorization.usage.log_fields(),
                    )

    # No `context_schema`: LangGraph would build one from the run's `context`, which Agent
    # Server takes from the client's request.
    builder = StateGraph(MainGraphState)
    builder.add_node("agent", agent_node)
    builder.add_edge(START, "agent")
    builder.add_edge("agent", END)
    return builder.compile(checkpointer=checkpointer)


def _run_span_attributes(
    state: MainGraphState, config: RunnableConfig, *, from_service: bool
) -> dict[str, str | int]:
    """The `invoke_agent` span's attributes, from trusted sources only.

    `AgentService` (`from_service`) puts the IDs and owner key in state. Under Agent Server
    the state is the client's input, so the thread, run and owner come from the run's
    config, where Agent Server records them in keys clients can't set.
    """
    configurable = config.get("configurable", {})
    thread_id: object
    run_id: object
    owner: object
    if from_service:
        thread_id, run_id = state.get("thread_id"), state.get("run_id")
        owner = state.get("owner_key") or state.get("user_id_hash")
    else:
        thread_id, run_id = configurable.get("thread_id"), configurable.get("run_id")
        owner = configurable.get("langgraph_auth_user_id")
    attributes: dict[str, str | int] = {
        semconv.GEN_AI_OPERATION_NAME: semconv.OPERATION_INVOKE_AGENT,
        semconv.GEN_AI_AGENT_NAME: semconv.AGENT_NAME,
        semconv.NEURON_TURN: _turn(state),
    }
    if thread_id:
        attributes[semconv.GEN_AI_CONVERSATION_ID] = str(thread_id)
    if run_id:
        attributes[semconv.NEURON_RUN_ID] = str(run_id)
    if isinstance(owner, str) and owner:
        attributes[semconv.NEURON_OWNER_KEY_PREFIX] = owner[:12]
    return attributes


def _run_authorization(
    context: object, config: RunnableConfig, settings: Settings
) -> AuthorizationContext:
    """The run's authorization, from trusted sources only (ADR 0006).

    `AgentService` passes an `AuthorizationContext` object, which no HTTP client can send.
    Anything else is a client-supplied Agent Server `context` and grants nothing: there the
    permissions and owner come from the authenticated user, which Agent Server records in
    reserved `configurable` keys that clients can't set.
    """
    if isinstance(context, AuthorizationContext):
        return context
    configurable = config.get("configurable", {})
    permissions = configurable.get("langgraph_auth_permissions")
    owner = configurable.get("langgraph_auth_user_id")
    return AuthorizationContext(
        frozenset(p for p in permissions if isinstance(p, str))
        if isinstance(permissions, list | tuple)
        else frozenset(),
        actor=owner[:12] if settings.auth_mode == "jwt" and isinstance(owner, str) else None,
        issuer_id=settings.auth_issuer_id,
        # Counted for the run's `model_token_usage` log; Agent Server enforces no budget.
        usage=TokenUsageAccumulator(),
    )


# Agent Server loads only this module, so it configures logging, LangSmith and telemetry itself
# (ADR 0007).
_settings = get_settings()
configure_logging(
    level=_settings.log_level,
    service=_settings.name,
    version=_settings.version,
    environment=_settings.env,
)
configure_langsmith(_settings)
configure_telemetry(_settings)

# Exported to langgraph.json. Compiled without a checkpointer: Agent Server supplies its own.
graph = build_graph(_settings)
