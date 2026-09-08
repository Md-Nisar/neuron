"""Main LangGraph workflow."""

from __future__ import annotations

from typing import Any

import structlog
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from neuron_agent.agents.factory import build_agent
from neuron_agent.config.settings import Settings, get_settings
from neuron_agent.models.factory import agent_invocation_config, classify_agent_error
from neuron_agent.schemas.agent import AgentAnswer
from neuron_agent.state.main import MainGraphState

logger = structlog.get_logger(__name__)


async def call_agent(
    state: MainGraphState, *, agent: Any, settings: Settings | None = None
) -> dict[str, Any]:
    """Invoke the LangChain agent and normalize its output into application state."""
    resolved_settings = settings or get_settings()
    request_id = state.get("request_id")
    thread_id = state.get("thread_id")
    logger.info(
        "agent_execution_started",
        request_id=request_id,
        thread_id=thread_id,
        recursion_limit=resolved_settings.max_agent_iterations,
    )
    try:
        result = await agent.ainvoke(
            {"messages": state["messages"]},
            config=agent_invocation_config(resolved_settings),
        )
    except Exception as exc:  # noqa: BLE001
        error = classify_agent_error(exc)
        log = logger.exception if error.context.alert else logger.warning
        log(
            "agent_execution_failed",
            request_id=request_id,
            thread_id=thread_id,
            error_code=error.context.code,
            retryable=error.context.retryable,
        )
        raise error from exc

    structured = result.get("structured_response")
    if isinstance(structured, AgentAnswer):
        answer = structured
    else:
        output_text = str(result["messages"][-1].content)
        answer = AgentAnswer(answer=output_text, used_tools=[], confidence=0.5)

    return {
        "messages": [AIMessage(content=answer.answer)],
        "answer": answer,
    }


def build_graph(settings: Settings | None = None) -> Any:
    """Build and compile the graph."""
    resolved_settings = settings or get_settings()
    agent = build_agent(resolved_settings)

    async def agent_node(state: MainGraphState) -> dict[str, Any]:
        return await call_agent(state, agent=agent, settings=resolved_settings)

    builder = StateGraph(MainGraphState)
    builder.add_node("agent", agent_node)
    builder.add_edge(START, "agent")
    builder.add_edge("agent", END)
    return builder.compile()


graph = build_graph()
