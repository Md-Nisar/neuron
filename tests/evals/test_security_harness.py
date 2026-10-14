"""Deterministic checks of the dataset v3 (security) runner, with no model calls."""

from __future__ import annotations

from typing import Any, cast

import pytest
from langchain_core.messages import HumanMessage
from tests.conftest import jwt_settings

from neuron_agent.errors.base import ThreadNotFoundError
from neuron_agent.evaluation import SECURITY_CASES, load_eval_cases, run_security_suite
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
