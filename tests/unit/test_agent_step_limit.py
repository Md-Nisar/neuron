"""Agent loop bound (#102): `APP_MAX_AGENT_ITERATIONS` counts model calls, not graph steps."""

from __future__ import annotations

import itertools
from collections.abc import Iterator
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError
from tests.conftest import StreamingFakeModel

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import AgentStepLimitError
from neuron_agent.graphs.main_graph import build_graph
from neuron_agent.models import factory
from neuron_agent.models.factory import agent_invocation_config, classify_agent_error
from neuron_agent.security.authorization import AuthorizationContext

pytestmark = pytest.mark.anyio

_ALLOWED = AuthorizationContext(frozenset({"tools:calculator"}))


def _calculator_call(n: int) -> AIMessage:
    call = {"name": "calculator", "args": {"expression": "6*7"}, "id": f"call-{n}"}
    return AIMessage(content="", tool_calls=[call])


class _Script:
    """Scripted model replies that count how many the model asked for."""

    def __init__(self, replies: Iterator[AIMessage]) -> None:
        self._replies = replies
        self.calls = 0

    def __iter__(self) -> Iterator[AIMessage]:
        return self

    def __next__(self) -> AIMessage:
        self.calls += 1
        return next(self._replies)


def _graph(monkeypatch: pytest.MonkeyPatch, script: _Script, **settings: int) -> object:
    monkeypatch.setattr(factory, "create_chat_model", lambda _: StreamingFakeModel(messages=script))
    return build_graph(Settings(env="test", **settings))


def test_recursion_limit_allows_one_tool_round_per_model_call() -> None:
    """Each model call and each tool call is a LangGraph step: N model calls need 2N steps."""
    settings = Settings(env="test", max_agent_iterations=8)
    assert agent_invocation_config(settings, run_id=None)["recursion_limit"] == 16


def test_default_iterations_allow_multi_step_tool_use() -> None:
    assert Settings(env="test").max_agent_iterations == 8


def test_recursion_error_is_a_classified_user_visible_step_limit_error() -> None:
    error = classify_agent_error(GraphRecursionError("Recursion limit of 16 reached"))
    assert isinstance(error, AgentStepLimitError)
    assert error.context.code == "agent_step_limit_exceeded"
    assert error.context.user_visible is True
    assert error.context.http_status == 422


async def test_four_sequential_tool_rounds_finish_within_the_default_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Five model calls and four tool calls is 9 steps: over the old limit of 5 steps."""
    replies = [*(_calculator_call(n) for n in range(4)), AIMessage(content="84")]
    script = _Script(iter(replies))
    graph = _graph(monkeypatch, script)

    result = await graph.ainvoke({"messages": [HumanMessage(content="hi")]}, context=_ALLOWED)  # type: ignore[attr-defined]

    assert script.calls == 5
    assert result["answer"].answer == "84"
    assert result["answer"].used_tools == ["calculator"]


async def test_a_looping_model_stops_at_the_iteration_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    looping = (_calculator_call(n) for n in itertools.count())
    script = _Script(looping)
    graph = _graph(monkeypatch, script, max_agent_iterations=3)

    # The last call is offered no tools; a model that calls one anyway still ends at the limit.
    with pytest.raises(AgentStepLimitError):
        await graph.ainvoke({"messages": [HumanMessage(content="hi")]}, context=_ALLOWED)  # type: ignore[attr-defined]

    assert script.calls == 3


async def test_the_last_allowed_model_call_is_offered_no_tools_so_it_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    offered: list[list[str]] = []

    class _Recording(StreamingFakeModel):
        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:  # type: ignore[override]
            offered.append(sorted(str(factory._tool_name(tool)) for tool in tools))
            return self

    replies = [_calculator_call(0), _calculator_call(1), AIMessage(content="84")]
    monkeypatch.setattr(factory, "create_chat_model", lambda _: _Recording(messages=iter(replies)))
    graph = build_graph(Settings(env="test", max_agent_iterations=3))

    result = await graph.ainvoke({"messages": [HumanMessage(content="hi")]}, context=_ALLOWED)  # type: ignore[attr-defined]

    assert result["answer"].answer == "84"
    assert len(offered) == 3
    assert all("calculator" in names for names in offered[:2])
    assert "calculator" not in offered[2]
    assert offered[2]  # the structured answer is still offered


async def test_with_one_model_call_allowed_it_is_offered_no_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A tool result would have no model call left to answer it, so the single call answers.
    offered: list[list[str]] = []

    class _Recording(StreamingFakeModel):
        def bind_tools(self, tools: Any, **kwargs: Any) -> Any:  # type: ignore[override]
            offered.append(sorted(str(factory._tool_name(tool)) for tool in tools))
            return self

    replies = iter([AIMessage(content="84")])
    monkeypatch.setattr(factory, "create_chat_model", lambda _: _Recording(messages=replies))
    graph = build_graph(Settings(env="test", max_agent_iterations=1))

    result = await graph.ainvoke({"messages": [HumanMessage(content="hi")]}, context=_ALLOWED)  # type: ignore[attr-defined]

    assert result["answer"].answer == "84"
    assert len(offered) == 1
    assert "calculator" not in offered[0]
