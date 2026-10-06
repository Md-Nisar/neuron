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
    trim_messages,
)
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from neuron_agent.agents.factory import build_agent
from neuron_agent.config.settings import Settings, get_settings
from neuron_agent.models.factory import (
    agent_invocation_config,
    classify_agent_error,
    get_retry_attempts,
    reset_retry_attempts,
)
from neuron_agent.schemas.agent import AgentAnswer
from neuron_agent.state.main import MainGraphState

logger = structlog.get_logger(__name__)


async def call_agent(
    state: MainGraphState, *, agent: Any, settings: Settings | None = None
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
    logger.info(
        "agent_execution_started",
        request_id=request_id,
        thread_id=thread_id,
        run_id=run_id,
        model=model,
        recursion_limit=resolved_settings.max_agent_iterations,
    )
    new_turn: list[BaseMessage] = []
    user_message = state.get("user_message")
    if user_message:
        new_turn.append(HumanMessage(content=user_message))
    stored = list(state.get("messages", []))
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
        result = await agent.ainvoke(
            {"messages": history},
            config=agent_invocation_config(resolved_settings, run_id=run_id),
        )
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

    structured = result.get("structured_response")
    if isinstance(structured, AgentAnswer):
        answer = structured
    else:
        output_text = str(result["messages"][-1].content)
        answer = AgentAnswer(answer=output_text, used_tools=[], confidence=0.5)

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

    async def agent_node(state: MainGraphState) -> dict[str, Any]:
        return await call_agent(state, agent=agent, settings=resolved_settings)

    builder = StateGraph(MainGraphState)
    builder.add_node("agent", agent_node)
    builder.add_edge(START, "agent")
    builder.add_edge("agent", END)
    return builder.compile(checkpointer=checkpointer)


# Exported to langgraph.json. Compiled without a checkpointer: Agent Server supplies its own.
graph = build_graph()
