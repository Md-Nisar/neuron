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
from neuron_agent.observability import semconv, telemetry
from neuron_agent.observability.logging import configure_logging
from neuron_agent.schemas.agent import AgentAnswer
from neuron_agent.security.authorization import AuthorizationContext
from neuron_agent.state.main import MainGraphState

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
        recursion_limit=resolved_settings.max_agent_iterations,
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
    settings: Settings | None = None, checkpointer: BaseCheckpointSaver[Any] | None = None
) -> Any:
    """Build and compile the graph, persisting thread state when a checkpointer is given."""
    resolved_settings = settings or get_settings()
    agent = build_agent(resolved_settings)

    async def agent_node(state: MainGraphState, config: RunnableConfig) -> dict[str, Any]:
        context = get_runtime().context
        authorization = _run_authorization(context, config, resolved_settings)
        attributes = _run_span_attributes(
            state, config, from_service=isinstance(context, AuthorizationContext)
        )
        name = f"{semconv.OPERATION_INVOKE_AGENT} {semconv.AGENT_NAME}"
        with telemetry.start_span(name, attributes=attributes) as span:
            try:
                return await call_agent(
                    state, agent=agent, settings=resolved_settings, authorization=authorization
                )
            except AppError as exc:
                telemetry.record_error(span, exc.context.code)
                raise

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
    )


# Agent Server loads only this module, so it configures logging itself (ADR 0007).
_settings = get_settings()
configure_logging(
    level=_settings.log_level,
    service=_settings.name,
    version=_settings.version,
    environment=_settings.env,
)

# Exported to langgraph.json. Compiled without a checkpointer: Agent Server supplies its own.
graph = build_graph(_settings)
