"""Framework contract (AGENTS.md: framework upgrades): the LangChain/LangGraph behaviour that
neuron's graph state and structured output depend on, pinned against the real `create_agent`."""

from __future__ import annotations

from importlib.metadata import version

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from packaging.version import Version
from tests.conftest import StreamingFakeModel

from neuron_agent.config.settings import Settings
from neuron_agent.graphs.main_graph import build_graph
from neuron_agent.models import factory
from neuron_agent.security.authorization import AuthorizationContext
from neuron_agent.state.main import MainGraphState

pytestmark = pytest.mark.anyio

_ALLOWED = AuthorizationContext(frozenset({"tools:calculator"}))
_CALL = {"name": "calculator", "args": {"expression": "6*7"}, "id": "call-1"}


def _graph(monkeypatch: pytest.MonkeyPatch, replies: list[AIMessage]) -> object:
    monkeypatch.setattr(
        factory, "create_chat_model", lambda _: StreamingFakeModel(messages=iter(replies))
    )
    return build_graph(Settings(env="test"), checkpointer=InMemorySaver())


@pytest.mark.parametrize(
    ("package", "floor"),
    [("langchain", "1.4.7"), ("langchain-core", "1.7.0"), ("langgraph", "1.2.18")],
)
def test_framework_versions_meet_the_adr_0009_floor(package: str, floor: str) -> None:
    assert Version(version(package)) >= Version(floor)


async def test_a_tool_turn_commits_only_the_user_turn_and_the_final_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Thread history is user turns and final answers (ADR 0005): the tool call and its
    result live inside the agent run and are not checkpointed."""
    graph = _graph(
        monkeypatch, [AIMessage(content="", tool_calls=[_CALL]), AIMessage(content="42")]
    )
    config = {"configurable": {"thread_id": "t1"}}

    result = await graph.ainvoke(  # type: ignore[attr-defined]
        {"messages": [HumanMessage(content="6*7?")], "thread_id": "t1"},
        config=config,
        context=_ALLOWED,
    )
    stored = (await graph.aget_state(config)).values["messages"]  # type: ignore[attr-defined]

    assert result["answer"].answer == "42"
    assert result["answer"].used_tools == ["calculator"]
    assert [type(m).__name__ for m in stored] == ["HumanMessage", "AIMessage"]
    assert not any(getattr(m, "tool_calls", None) for m in stored)


async def test_state_keys_after_a_run_are_the_documented_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = _graph(monkeypatch, [AIMessage(content="hello")])
    result = await graph.ainvoke(  # type: ignore[attr-defined]
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": "t2"}},
        context=_ALLOWED,
    )
    assert {"messages", "answer"} <= set(result)
    assert set(result) <= set(MainGraphState.__annotations__)


async def test_the_structured_output_tool_call_is_parsed_into_the_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call = {
        "name": "AgentAnswer",
        "args": {"answer": "structured", "used_tools": [], "confidence": 0.5},
        "id": "call-s",
    }
    graph = _graph(monkeypatch, [AIMessage(content="", tool_calls=[call])])
    result = await graph.ainvoke(  # type: ignore[attr-defined]
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": "t4"}},
        context=_ALLOWED,
    )
    assert result["answer"].answer == "structured"
    assert result["answer"].confidence == 0.5


async def test_a_plain_text_reply_becomes_the_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A model that answers in plain text rather than the structured tool still yields an
    `AgentAnswer` (the raw-text fallback in `call_agent`), with no tools recorded."""
    graph = _graph(monkeypatch, [AIMessage(content="plain")])
    result = await graph.ainvoke(  # type: ignore[attr-defined]
        {"messages": [HumanMessage(content="hi")]},
        config={"configurable": {"thread_id": "t3"}},
        context=_ALLOWED,
    )
    assert result["answer"].answer == "plain"
    assert result["answer"].used_tools == []
