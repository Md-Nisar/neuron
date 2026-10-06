from __future__ import annotations

from typing import Any

import pytest
import structlog.testing
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately
from langgraph.checkpoint.memory import InMemorySaver

from neuron_agent.config.settings import Settings
from neuron_agent.graphs.main_graph import bound_model_history, build_graph, evict_oldest_turns

pytestmark = pytest.mark.anyio


def _turns(n: int, size: int = 400) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for i in range(n):
        messages += [
            HumanMessage(content=f"q{i} " + "x" * size, id=f"h{i}"),
            AIMessage(content=f"a{i} " + "y" * size, id=f"a{i}"),
        ]
    return messages


def test_bound_model_history_keeps_newest_messages_within_budget() -> None:
    history = [*_turns(20), HumanMessage(content="now", id="now")]
    bounded = bound_model_history(history, max_tokens=1000)

    assert count_tokens_approximately(bounded) <= 1000
    assert bounded[-1].id == "now"
    assert isinstance(bounded[0], HumanMessage)
    assert len(bounded) < len(history)


def test_bound_model_history_keeps_current_turn_even_if_over_budget() -> None:
    huge = HumanMessage(content="z" * 50_000, id="huge")
    assert bound_model_history([*_turns(2), huge], max_tokens=256) == [huge]


def test_bound_model_history_never_starts_on_an_orphaned_tool_result() -> None:
    tool_call = {"name": "calculator", "args": {}, "id": "c1"}
    history: list[BaseMessage] = [
        HumanMessage(content="x" * 2000, id="h0"),
        AIMessage(content="", tool_calls=[tool_call], id="a0"),
        ToolMessage(content="2", tool_call_id="c1", id="t0"),
        AIMessage(content="y" * 2000, id="a1"),
        HumanMessage(content="now", id="now"),
    ]
    bounded = bound_model_history(history, max_tokens=300)
    assert bounded[0].id == "now"
    assert not any(isinstance(m, ToolMessage) for m in bounded)


def test_evict_oldest_turns_drops_whole_turns() -> None:
    stored = _turns(5)  # 10 messages
    evicted = evict_oldest_turns(stored, incoming=2, limit=9)
    # 12 would exceed 9 by 3 -> drop through the end of the second turn (4 messages).
    assert [m.id for m in evicted] == ["h0", "a0", "h1", "a1"]
    assert evict_oldest_turns(stored, incoming=2, limit=12) == []


async def test_long_thread_stays_bounded_in_model_input_and_storage(echo_agent: Any) -> None:
    settings = Settings(env="test", max_history_tokens=600, max_thread_messages=6)
    compiled = build_graph(settings, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t"}}
    base = {"request_id": "r", "thread_id": "t", "run_id": "12345678-1234-5678-1234-567812345678"}

    for i in range(12):
        await compiled.ainvoke(
            {**base, "messages": [], "user_message": f"turn {i} " + "w" * 300}, config=config
        )

    sent = echo_agent.calls[-1]
    assert count_tokens_approximately(sent) <= 600
    assert sent[-1].content.startswith("turn 11")
    stored = (await compiled.aget_state(config)).values["messages"]
    assert len(stored) <= 6
    assert isinstance(stored[0], HumanMessage)
    assert stored[-2].content.startswith("turn 11")


async def test_trimming_is_logged_without_message_content(echo_agent: Any) -> None:
    settings = Settings(env="test", max_history_tokens=256)
    compiled = build_graph(settings, checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "t"}}
    base = {"request_id": "r", "thread_id": "t", "run_id": "12345678-1234-5678-1234-567812345678"}
    for i in range(3):
        with structlog.testing.capture_logs() as logs:
            await compiled.ainvoke(
                {**base, "messages": [], "user_message": f"secret-{i} " + "w" * 600},
                config=config,
            )
    trimmed = next(log for log in logs if log["event"] == "history_trimmed")
    assert trimmed["messages_sent"] < trimmed["messages_total"]
    assert "secret-" not in repr(logs)
