"""Approval of mutating tools (#241, ADR 0009 decision 6) through the real agent and graph."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import structlog.testing
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from tests.conftest import StreamingFakeModel

from neuron_agent.config.settings import Settings
from neuron_agent.graphs import main_graph
from neuron_agent.graphs.main_graph import build_graph
from neuron_agent.models import factory
from neuron_agent.security.authorization import AuthorizationContext, TokenUsageAccumulator
from neuron_agent.tools.registry import ToolRegistry, ToolSpec, builtin_registry

pytestmark = pytest.mark.anyio

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
_SCOPES = frozenset({"tools:note_taker", "tools:calculator"})
_ran: list[str] = []


@tool
def note_taker(text: str) -> str:
    """Save a note. This changes data outside the conversation."""
    _ran.append(text)
    return "saved"


@pytest.fixture(autouse=True)
def _reset() -> None:
    _ran.clear()


def _registry() -> ToolRegistry:
    return ToolRegistry([*builtin_registry(), ToolSpec(note_taker, "tools:note_taker", "mutating")])


def _replies(*messages: AIMessage) -> StreamingFakeModel:
    return StreamingFakeModel(messages=iter(messages))


def _call(text: str = "buy milk") -> AIMessage:
    call = {"name": "note_taker", "args": {"text": text}, "id": f"call-{uuid.uuid4().hex[:6]}"}
    return AIMessage(content="", tool_calls=[call], usage_metadata=_USAGE)  # type: ignore[arg-type]


def _final(text: str) -> AIMessage:
    return AIMessage(content=text, usage_metadata=_USAGE)  # type: ignore[arg-type]


def _use(monkeypatch: pytest.MonkeyPatch, model: StreamingFakeModel) -> None:
    monkeypatch.setattr(factory, "create_chat_model", lambda _: model)


def _graph() -> Any:
    return build_graph(Settings(env="test"), checkpointer=InMemorySaver(), registry=_registry())


def _input(thread: str) -> dict[str, Any]:
    return {
        "messages": [],
        "user_message": "remember to buy milk",
        "request_id": "req-1",
        "thread_id": thread,
        "run_id": str(uuid.uuid4()),
    }


def _context() -> tuple[AuthorizationContext, TokenUsageAccumulator]:
    usage = TokenUsageAccumulator()
    return AuthorizationContext(_SCOPES, usage=usage), usage


async def _pause(graph: Any, thread: str) -> tuple[dict[str, Any], TokenUsageAccumulator]:
    context, usage = _context()
    config = {"configurable": {"thread_id": thread}}
    return await graph.ainvoke(_input(thread), config=config, context=context), usage


async def _resume(graph: Any, thread: str, decision: str) -> tuple[dict[str, Any], Any]:
    context, usage = _context()
    config = {"configurable": {"thread_id": thread}}
    decisions = {"decisions": [{"type": decision}]}
    result = await graph.ainvoke(Command(resume=decisions), config=config, context=context)
    return result, usage


async def test_a_gated_call_pauses_the_run_before_the_tool_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, _replies(_call("buy milk"), _final("saved it")))
    graph = _graph()

    with structlog.testing.capture_logs() as logs:
        result, _ = await _pause(graph, "t-pause")

    [interrupt] = result["__interrupt__"]
    [action] = interrupt.value["action_requests"]
    assert (action["name"], action["args"]) == ("note_taker", {"text": "buy milk"})
    assert interrupt.value["review_configs"][0]["allowed_decisions"] == ["approve", "reject"]
    assert _ran == []
    # A pause is neither a failure nor a completion.
    events = {log["event"] for log in logs}
    assert "agent_execution_failed" not in events
    assert "agent_execution_completed" not in events
    snapshot = await graph.aget_state({"configurable": {"thread_id": "t-pause"}})
    assert snapshot.values["messages"] == []  # nothing is committed to the thread yet


async def test_approve_runs_the_tool_exactly_once_and_commits_one_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, _replies(_call(), _final("saved it")))
    graph = _graph()
    await _pause(graph, "t-approve")

    result, _ = await _resume(graph, "t-approve", "approve")

    assert _ran == ["buy milk"]
    assert result["answer"].answer == "saved it"
    assert result["answer"].used_tools == ["note_taker"]
    stored = (await graph.aget_state({"configurable": {"thread_id": "t-approve"}})).values[
        "messages"
    ]
    # History is the user turn and the final answer, once each: no tool call, no tool result.
    assert [type(m) for m in stored] == [HumanMessage, AIMessage]
    assert [m.content for m in stored] == ["remember to buy milk", "saved it"]


async def test_reject_never_runs_the_tool_and_the_run_still_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, _replies(_call(), _final("ok, I did not save it")))
    graph = _graph()
    await _pause(graph, "t-reject")

    result, _ = await _resume(graph, "t-reject", "reject")

    assert _ran == []
    assert result["answer"].answer == "ok, I did not save it"
    assert result["answer"].used_tools == []
    stored = (await graph.aget_state({"configurable": {"thread_id": "t-reject"}})).values[
        "messages"
    ]
    assert [type(m) for m in stored] == [HumanMessage, AIMessage]


async def test_a_resumed_run_counts_each_model_call_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The call that asked for the tool is charged to the first run, not again on resume."""
    model = _replies(_call(), _final("saved it"))
    _use(monkeypatch, model)
    graph = _graph()

    _, first = await _pause(graph, "t-tokens")
    _, second = await _resume(graph, "t-tokens", "approve")

    assert first.total_tokens == 15
    assert second.total_tokens == 15  # only the answering call
    assert next(model.messages, None) is None  # exactly two model calls happened in all


async def test_the_resume_does_not_repeat_the_first_runs_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`call_agent` runs again from its start on resume: it must only log before the agent call."""
    _use(monkeypatch, _replies(_call(), _final("saved it")))
    graph = _graph()
    await _pause(graph, "t-idem")
    with structlog.testing.capture_logs() as logs:
        await _resume(graph, "t-idem", "approve")

    events = [log["event"] for log in logs]
    assert events.count("agent_execution_started") == 1
    assert events.count("agent_execution_completed") == 1
    assert "thread_created" not in events


async def test_without_a_checkpointer_gated_tools_are_not_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[ToolRegistry] = []

    def spy(settings: Settings, registry: ToolRegistry | None = None) -> Any:
        assert registry is not None
        built.append(registry)
        return object()

    monkeypatch.setattr(main_graph, "build_agent", spy)
    with structlog.testing.capture_logs() as logs:
        build_graph(Settings(env="test"), checkpointer=None, registry=_registry())

    assert built[0].names() == ("utc_now", "calculator")
    assert any(log["event"] == "approval_tools_disabled" for log in logs)


async def test_a_run_without_gated_tools_does_not_checkpoint_its_inner_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a gate the agent keeps ADR 0005's `checkpointer=False`: nothing extra is stored."""
    _use(monkeypatch, _replies(_final("hi")))
    saver = InMemorySaver()
    graph = build_graph(Settings(env="test"), checkpointer=saver)
    context, _ = _context()
    config = {"configurable": {"thread_id": "t-plain"}}

    await graph.ainvoke(_input("t-plain"), config=config, context=context)

    namespaces = {item.config["configurable"]["checkpoint_ns"] for item in saver.list(config)}
    assert namespaces == {""}
