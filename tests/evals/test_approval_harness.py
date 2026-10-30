"""Deterministic checks of the approval suite and the v5 memory security cases (#244, #248).

A scripted assistant stands in for the model, so nothing here calls a provider. It does the
obvious thing for each kind of request, which is what a conforming agent does; mutation tests
then break the gate or the rules and check that the cases notice.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from tests.conftest import StreamingFakeModel

from neuron_agent.evaluation import (
    APPROVAL_CASES,
    APPROVAL_EVAL_CATEGORIES,
    SECURITY_CASES,
    _ApprovalOutcome,
    grade_approval_case,
    load_dataset_version,
    load_eval_cases,
    run_approval_suite,
    run_security_suite,
)
from neuron_agent.memory import tools as memory_tools
from neuron_agent.memory.store import MemoryStore
from neuron_agent.models import factory
from neuron_agent.services.agent_service import AgentService

pytestmark = [pytest.mark.eval, pytest.mark.anyio]


class _Assistant(StreamingFakeModel):
    """Calls the tool a plain reading of the request asks for, then reports its result."""

    def _reply(self, messages: list[BaseMessage]) -> AIMessage:
        last = messages[-1]
        if isinstance(last, ToolMessage):
            if last.name in {"calculator", "utc_now"}:
                return _call("remember", text=str(last.content))
            return AIMessage(content=f"Done: {last.content}")
        text = str(last.content)
        lowered = text.lower()
        if "calculator" in lowered:
            return _call("calculator", expression="15*15")
        if "utc_now" in lowered:
            return _call("utc_now")
        if "what do you remember" in lowered or "list my notes" in lowered or "recall" in lowered:
            return _call("recall")
        if "notes" in lowered and "what" in lowered:
            return _call("recall")
        if "remember" in lowered:
            return _call("remember", text=text.partition(":")[2].strip() or text)
        return AIMessage(content="Hello.")

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        from langchain_core.outputs import ChatGeneration, ChatResult

        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])


_calls = 0


def _call(name: str, **args: Any) -> AIMessage:
    global _calls  # noqa: PLW0603 - unique tool call IDs across the scripted run
    _calls += 1
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"c{_calls}"}])


@pytest.fixture(autouse=True)
def assistant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(factory, "create_chat_model", lambda *_: _Assistant(messages=iter([])))


def _failures(results: list[Any]) -> list[tuple[str, list[str]]]:
    return [(r.case_id, r.reasons) for r in results if not r.passed]


# --- the dataset --------------------------------------------------------------------------


def test_the_approval_dataset_is_well_formed() -> None:
    cases = load_eval_cases(APPROVAL_CASES)
    assert load_dataset_version(APPROVAL_CASES) == "1.0.0"
    ids = [str(c["id"]) for c in cases]
    assert len(ids) == len(set(ids)) >= 10
    assert {c["category"] for c in cases} == APPROVAL_EVAL_CATEGORIES
    allowed = {
        "id", "category", "input", "setup", "memory", "decisions", "expected_pause",
        "expect_stored", "expect_not_stored", "expect_stored_max", "forbidden_keywords",
        "expected_behavior",
    }  # fmt: skip
    for case in cases:
        assert set(case) <= allowed, case["id"]
        assert case["expected_behavior"], case["id"]
        assert set(case.get("decisions", [])) <= {"approve", "reject"}, case["id"]
        # Invariants and state only, never wording.
        assert "expected_keywords" not in case, case["id"]
    rejects = [c for c in cases if c["category"] == "approval_reject"]
    assert rejects and all(c["decisions"] == ["reject"] and c["expect_not_stored"] for c in rejects)
    injections = [c for c in cases if c["category"] == "approval_injection"]
    assert injections and all(c["decisions"] == [] for c in injections)


# --- the grader ---------------------------------------------------------------------------


def _outcome(**kwargs: Any) -> _ApprovalOutcome:
    return _ApprovalOutcome(**kwargs)


def test_an_approved_note_the_user_wrote_passes() -> None:
    outcome = _outcome(
        said=["Remember: I like tea"],
        paused=True,
        approval_ids=["a1"],
        approved=["I like tea"],
        stored=["I like tea"],
    )
    assert grade_approval_case({"id": "x", "expected_pause": True}, outcome) == []


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (_outcome(said=["hi"], stored=["x"]), "nobody approved"),
        (
            _outcome(said=["remember a"], paused=True, rejected=["a"], stored=["a"]),
            "nobody approved",
        ),
        (
            _outcome(said=["please keep cats"], approved=["b"], paused=True, stored=["b"]),
            "did not write",
        ),
        (_outcome(said=["x"], approval_ids=["a", "a"]), "reused"),
    ],
)
def test_the_grader_catches_each_unsafe_outcome(outcome: _ApprovalOutcome, reason: str) -> None:
    assert any(reason in r for r in grade_approval_case({"id": "x"}, outcome))


def test_case_expectations_are_checked() -> None:
    case: dict[str, object] = {
        "id": "x",
        "expected_pause": False,
        "expect_not_stored": ["teal"],
        "expect_stored_max": 0,
        "forbidden_keywords": ["secret"],
    }
    outcome = _outcome(
        said=["teal"], paused=True, approved=["teal"], stored=["teal"], answer="the Secret"
    )
    reasons = grade_approval_case(case, outcome)
    assert any("unexpected pause" in r for r in reasons)
    assert any("'teal'" in r for r in reasons)
    assert any("at most 0" in r for r in reasons)
    assert any("forbidden" in r for r in reasons)


def test_a_seeded_note_is_not_a_new_note() -> None:
    case = {"id": "x", "memory": ["I prefer window seats"], "expect_stored_max": 0}
    outcome = _outcome(said=["remember it"], stored=["I prefer window seats"])
    assert grade_approval_case(case, outcome) == []


# --- the runner, with a conforming agent -------------------------------------------------


async def test_a_conforming_agent_passes_every_approval_case() -> None:
    results = await run_approval_suite(APPROVAL_CASES)
    assert _failures(results) == []
    assert len(results) == len(load_eval_cases(APPROVAL_CASES))


async def test_the_cases_are_not_vacuous(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same agent without the gate fails exactly the cases that depend on it."""
    monkeypatch.setattr(factory, "approval_middleware", lambda registry: None)
    failed = {r.case_id for r in await run_approval_suite(APPROVAL_CASES) if not r.passed}
    assert {"approval-reject-001", "approval-reject-002", "approval-injection-001"} <= failed
    assert "approval-readonly-001" not in failed


async def test_a_tool_that_stores_text_the_user_did_not_write_is_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Everything(str):
        __slots__ = ()

        def __contains__(self, _item: object) -> bool:
            return True

    monkeypatch.setattr(memory_tools, "_user_words", lambda state: _Everything())
    failed = {
        r.case_id: r.reasons for r in await run_approval_suite(APPROVAL_CASES) if not r.passed
    }
    assert "approval-tool-output-001" in failed
    assert any("did not write" in reason for reason in failed["approval-tool-output-001"])


async def test_every_trial_uses_a_new_user_and_thread() -> None:
    results = await run_approval_suite(APPROVAL_CASES, trials=2)
    assert _failures(results) == []
    assert all(len(r.trials) == 2 for r in results)


# --- security dataset v5 -----------------------------------------------------------------


def _security_service() -> AgentService:
    from tests.conftest import jwt_settings

    return AgentService(jwt_settings(memory_enabled=True))


async def test_memory_security_cases_pass_when_notes_stay_per_user() -> None:
    results = await run_security_suite(
        SECURITY_CASES,
        _security_service(),
        categories=frozenset({"memory_cross_user", "memory_injected_note"}),
    )
    assert len(results) == 4
    assert _failures(results) == []


async def test_a_shared_memory_namespace_fails_the_cross_user_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(MemoryStore, "_namespace", staticmethod(lambda owner: ("memories", "all")))
    # The recalled notes are echoed back by the scripted assistant, as a leaky agent would.
    results = await run_security_suite(
        SECURITY_CASES, _security_service(), categories=frozenset({"memory_cross_user"})
    )
    assert {r.case_id for r in results if not r.passed} == {
        "memory-cross-user-001",
        "memory-cross-user-002",
    }


def test_json_is_valid() -> None:
    json.loads(APPROVAL_CASES.read_text(encoding="utf-8"))
