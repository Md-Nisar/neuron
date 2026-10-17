"""Deterministic checks of the dataset v3 (security) runner, with no model calls."""

from __future__ import annotations

from typing import Any, cast

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from tests.conftest import jwt_settings

from neuron_agent.errors.base import ThreadNotFoundError
from neuron_agent.evaluation import (
    SECURITY_CASES,
    SYSTEM_PROMPT_MARKERS,
    _graded_as_attacker,
    _permitted_tools,
    evaluate_case,
    load_eval_cases,
    run_security_suite,
)
from neuron_agent.graphs import main_graph
from neuron_agent.prompts.loader import load_prompt
from neuron_agent.schemas.agent import AgentAnswer
from neuron_agent.services.agent_service import AgentService

pytestmark = [pytest.mark.eval, pytest.mark.anyio]


def _human_text(call: list[Any]) -> str:
    return " ".join(str(m.content) for m in call if isinstance(m, HumanMessage))


async def test_attacker_runs_never_see_the_victims_conversation(echo_agent: Any) -> None:
    cases = load_eval_cases(SECURITY_CASES)
    results = await run_security_suite(SECURITY_CASES, AgentService(jwt_settings()))

    assert [r.case_id for r in results] == [c["id"] for c in cases]
    failures = [(r.case_id, r.reasons) for r in results if not r.passed]
    assert not failures

    # Replay the model calls in order: the victim's turns, then the attacker's (unless the
    # attacker's turn was aimed at the victim's thread and rejected before the model).
    calls = iter(echo_agent.calls)
    for case in cases:
        victim_turns = cast("list[str]", case["victim_setup"])
        for _ in victim_turns:
            next(calls)
        if case.get("target") == "victim_thread":
            continue
        attacker_turns = [*cast("list[str]", case.get("setup", [])), case["input"]]
        final = [next(calls) for _ in attacker_turns][-1]
        model_input = _human_text(final)
        for keyword in cast("list[str]", case["forbidden_keywords"]):
            assert keyword not in model_input, case["id"]
        # The echo agent repeats the attacker's turns, so a marker there would trip the check.
        for marker in SYSTEM_PROMPT_MARKERS:
            assert marker not in model_input.lower(), case["id"]
    assert next(calls, None) is None


async def test_runner_reports_a_failure_when_isolation_breaks(
    echo_agent: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutation check: with the ownership comparison removed, the dataset catches it."""

    async def any_owner(self: AgentService, thread_id: str, owner_key: str | None) -> Any:
        snapshot = await self.graph.aget_state({"configurable": {"thread_id": thread_id}})
        if not snapshot.values:
            raise ThreadNotFoundError("thread not found")
        return snapshot.values

    monkeypatch.setattr(AgentService, "_owned_thread_state", any_owner)
    results = await run_security_suite(SECURITY_CASES, AgentService(jwt_settings()))
    failed = {r.case_id for r in results if not r.passed}
    expected = {
        str(c["id"]) for c in load_eval_cases(SECURITY_CASES) if c.get("target") == "victim_thread"
    }
    assert failed == expected


def test_system_prompt_markers_come_from_the_real_prompt() -> None:
    prompt = load_prompt("system/main.md").lower()
    assert len(SYSTEM_PROMPT_MARKERS) >= 4
    for marker in SYSTEM_PROMPT_MARKERS:
        assert marker == marker.lower()
        assert marker in prompt, f"marker {marker!r} is not in prompts/system/main.md"


def _score(case_id: str, **kwargs: Any) -> list[str]:
    """Grade one case's attacker turn the way `run_security_suite` does."""
    case = next(c for c in load_eval_cases(SECURITY_CASES) if c["id"] == case_id)
    permissions = kwargs.pop("permissions", frozenset({"agent:invoke"}))
    result = evaluate_case(
        _graded_as_attacker(case, permissions),
        answer=kwargs.pop("answer", "Sorry, I cannot do that."),
        used_tools=kwargs.pop("used_tools", []),
        confidence=0.5,
        permissions=permissions,
    )
    return result.reasons


def test_disclosure_marker_fails_the_case() -> None:
    assert _score("system-prompt-disclosure-001") == []
    leaked = "You are Neuron Agent, a concise production assistant."
    assert _score("system-prompt-disclosure-001", answer=leaked)


def test_tool_run_without_permission_fails_injection_cases() -> None:
    assert _score("direct-injection-tools-001") == []
    assert _score("direct-injection-tools-001", used_tools=["calculator"])
    assert _score("scope-escalation-001", used_tools=["calculator"])


def test_a_permitted_tool_run_passes_security_cases() -> None:
    """`utc_now` needs no permission, so an attacker calling it exposes nothing (#99)."""
    for case in load_eval_cases(SECURITY_CASES):
        assert _score(str(case["id"]), used_tools=["utc_now"]) == [], case["id"]
    granted = frozenset({"agent:invoke", "tools:calculator"})
    assert (
        _score("direct-injection-tools-001", used_tools=["calculator"], permissions=granted) == []
    )
    # A tool the agent doesn't have is never permitted.
    assert _score("direct-injection-tools-001", used_tools=["shell_exec"])


def test_a_leak_still_fails_with_a_permitted_tool_run() -> None:
    leaked = "You are Neuron Agent, a concise production assistant."
    assert _score("system-prompt-disclosure-001", answer=leaked, used_tools=["utc_now"])
    case = next(c for c in load_eval_cases(SECURITY_CASES) if c["forbidden_keywords"])
    secret = cast("list[str]", case["forbidden_keywords"])[0]
    assert _score(str(case["id"]), answer=f"It is {secret}.", used_tools=["utc_now"])


@pytest.mark.parametrize(
    "permissions",
    [frozenset(), frozenset({"agent:invoke"}), frozenset({"agent:invoke", "tools:calculator"})],
)
async def test_permitted_tools_match_what_the_agent_lets_run(permissions: frozenset[str]) -> None:
    """The grading's permitted set is the set the tool authorization middleware offers."""
    from langchain.agents.middleware import ModelRequest, ModelResponse
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    from langgraph.runtime import Runtime

    from neuron_agent.models.factory import tool_authorization_middleware
    from neuron_agent.security.authorization import AuthorizationContext
    from neuron_agent.tools import calculator, utc_now

    offered: list[str] = []

    async def handler(filtered: ModelRequest[object]) -> ModelResponse:
        offered.extend(tool.name for tool in filtered.tools)
        return ModelResponse(result=[AIMessage(content="ok")])

    request = ModelRequest(
        model=FakeListChatModel(responses=["ok"]),
        messages=[],
        tools=[utc_now, calculator],
        runtime=Runtime(context=AuthorizationContext(permissions)),
    )
    await tool_authorization_middleware().awrap_model_call(request, handler)
    assert sorted(offered) == _permitted_tools(permissions)


class _ToolRunningAgent:
    """Answers "ok" after one successful run of `tool`, so `used_tools` is `[tool]`."""

    def __init__(self, tool: str) -> None:
        self.tool = tool

    async def ainvoke(self, inputs: dict[str, Any], *, config: Any, context: Any = None) -> Any:
        call = {"name": self.tool, "args": {}, "id": "call-1"}
        return {
            "messages": [
                *inputs["messages"],
                AIMessage(content="", tool_calls=[call]),
                ToolMessage(content="result", tool_call_id="call-1"),
                AIMessage(content="ok"),
            ],
            "structured_response": AgentAnswer(answer="ok", confidence=1.0),
        }


async def test_runner_passes_a_permitted_tool_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_graph, "build_agent", lambda settings: _ToolRunningAgent("utc_now"))
    results = await run_security_suite(SECURITY_CASES, AgentService(jwt_settings()))
    assert [(r.case_id, r.reasons) for r in results if not r.passed] == []


async def test_runner_fails_an_unpermitted_tool_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_graph, "build_agent", lambda settings: _ToolRunningAgent("calculator"))
    results = await run_security_suite(SECURITY_CASES, AgentService(jwt_settings()))
    cases = {str(c["id"]): c for c in load_eval_cases(SECURITY_CASES)}
    graded = [r for r in results if cases[r.case_id].get("target") != "victim_thread"]
    assert graded
    for result in graded:
        assert "tool calculator ran without permission tools:calculator" in result.reasons


async def test_scope_escalation_cases_run_with_a_narrowed_principal(echo_agent: Any) -> None:
    from neuron_agent.evaluation import _attacker_permissions

    case = next(c for c in load_eval_cases(SECURITY_CASES) if c["id"] == "scope-escalation-001")
    assert _attacker_permissions(case) == frozenset({"agent:invoke"})
    with pytest.raises(ValueError, match="narrow"):
        _attacker_permissions({"id": "x", "attacker_permissions": ["tools:calculator", "admin"]})
