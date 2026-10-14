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
    run_id: str
    user_id_hash: NotRequired[str | None]
    owner_key: NotRequired[str | None]
    # Per-run input: committed to `messages` together with the answer, only on success.
    user_message: NotRequired[str | None]
    answer: NotRequired[AgentAnswer]
    error: NotRequired[str]
