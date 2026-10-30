"""The tool registry (#237, ADR 0009 decision 4): one spec per tool drives every check."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from langchain.agents.middleware import ModelRequest, ModelResponse
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.runtime import Runtime

from neuron_agent.config.settings import Settings
from neuron_agent.models.factory import tool_authorization_middleware
from neuron_agent.security.authorization import DEV_PERMISSIONS, AuthorizationContext
from neuron_agent.security.input_policy import HIGH_RISK_TOOL_NAMES
from neuron_agent.tools import calculator, utc_now
from neuron_agent.tools.registry import ToolRegistry, ToolSpec, builtin_registry

pytestmark = pytest.mark.anyio


@tool
def note_taker(text: str) -> str:
    """Store a note (a stand-in for any tool that changes state)."""
    return text


@tool
def send_email(to: str) -> str:
    """Send an email."""
    return to


def test_the_builtin_registry_holds_exactly_the_shipped_tools() -> None:
    registry = builtin_registry()
    assert registry.names() == ("utc_now", "calculator")
    assert registry.scope_for("utc_now") is None
    assert registry.scope_for("calculator") == "tools:calculator"
    assert registry.mutating() == []
    assert {spec.source for spec in registry} == {"builtin"}


def test_visibility_follows_the_scope() -> None:
    registry = builtin_registry()
    assert registry.visible_to(frozenset()) == ["utc_now"]
    assert registry.visible_to(frozenset({"tools:calculator"})) == ["utc_now", "calculator"]
    assert registry.visible_to(frozenset({"tools:other"})) == ["utc_now"]


def test_the_dev_permissions_cover_every_builtin_scope() -> None:
    scopes = {spec.scope for spec in builtin_registry() if spec.scope}
    assert scopes <= DEV_PERMISSIONS


def test_no_shipped_tool_is_on_the_independent_deny_list() -> None:
    """The deny-list is checked separately from the registry, which also enforces it."""
    assert not set(builtin_registry().names()) & HIGH_RISK_TOOL_NAMES


@pytest.mark.parametrize(
    "spec",
    [
        lambda: ToolSpec(note_taker, scope="calculator"),
        lambda: ToolSpec(note_taker, scope="tools:Upper Case"),
        lambda: ToolSpec(note_taker, scope=None, risk="mutating"),
        lambda: ToolSpec(note_taker, scope=None, source="mcp"),
        lambda: ToolSpec(send_email, scope="tools:send_email"),
    ],
)
def test_invalid_specs_are_refused(spec: Any) -> None:
    with pytest.raises(ValueError):
        spec()


def test_duplicate_names_are_refused() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        ToolRegistry([ToolSpec(calculator, "tools:calculator"), ToolSpec(calculator, None)])


def test_a_mutating_tool_gets_an_approval_gate_and_a_read_tool_does_not() -> None:
    from langchain.agents.middleware import HumanInTheLoopMiddleware

    from neuron_agent.models.factory import agent_middleware

    gated = ToolRegistry(
        [*builtin_registry(), ToolSpec(note_taker, "tools:note_taker", "mutating")]
    )
    [hitl] = [
        m
        for m in agent_middleware(Settings(env="test"), gated)
        if isinstance(m, HumanInTheLoopMiddleware)
    ]
    assert hitl.interrupt_on["note_taker"]["allowed_decisions"] == ["approve", "reject"]
    assert set(hitl.interrupt_on) == {"note_taker"}
    assert not [
        m
        for m in agent_middleware(Settings(env="test"), builtin_registry())
        if isinstance(m, HumanInTheLoopMiddleware)
    ]


def _request(tools: list[Any], permissions: frozenset[str]) -> ModelRequest[Any]:
    return ModelRequest(
        model=FakeListChatModel(responses=["ok"]),
        messages=[],
        tools=tools,
        runtime=Runtime(context=AuthorizationContext(permissions)),
    )


async def test_a_tool_without_a_spec_is_neither_offered_nor_callable() -> None:
    """Even with its scope granted, a tool the registry does not hold is refused."""
    registry = ToolRegistry([ToolSpec(utc_now, scope=None)])
    middleware = tool_authorization_middleware(registry)
    permissions = frozenset({"tools:calculator"})
    offered: list[str] = []

    async def model_handler(filtered: ModelRequest[Any]) -> ModelResponse:
        offered.extend(t.name for t in filtered.tools)
        return ModelResponse(result=[AIMessage(content="ok")])

    await middleware.awrap_model_call(_request([utc_now, calculator], permissions), model_handler)
    assert offered == ["utc_now"]

    ran = False

    async def tool_handler(_: object) -> str:
        nonlocal ran
        ran = True
        return "executed"

    call = SimpleNamespace(
        tool_call={"name": "calculator", "args": {"expression": "1+1"}, "id": "c1"},
        runtime=SimpleNamespace(context=AuthorizationContext(permissions)),
    )
    result = await middleware.awrap_tool_call(call, tool_handler)
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert not ran
