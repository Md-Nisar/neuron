"""Typed LangGraph state."""

from __future__ import annotations

from typing import Annotated, NotRequired, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from neuron_agent.schemas.agent import AgentAnswer


class MainGraphState(TypedDict):
    """Shared state for the main graph."""

    messages: Annotated[list[BaseMessage], add_messages]
    request_id: str
    thread_id: str
    run_id: NotRequired[str]
    user_id_hash: NotRequired[str]
    answer: NotRequired[AgentAnswer]
    error: NotRequired[str]
