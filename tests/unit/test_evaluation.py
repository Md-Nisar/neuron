from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from neuron_agent.errors.base import ProviderTimeoutError
from neuron_agent.evaluation import evaluate_case, run_eval_suite, run_security_suite
from neuron_agent.schemas.agent import AgentRequest, AgentResponse

_BASE_CASE: dict[str, object] = {
    "id": "case-001",
    "category": "calculator_tool_selection",
    "expected_tools": ["calculator"],
    "expected_keywords": ["57"],
}


def test_evaluate_case_passes_when_response_matches_expectations() -> None:
    result = evaluate_case(
        _BASE_CASE, answer="The answer is 57.", used_tools=["calculator"], confidence=0.9
    )
    assert result.passed
    assert result.reasons == []


def test_evaluate_case_fails_on_tool_mismatch() -> None:
    result = evaluate_case(_BASE_CASE, answer="The answer is 57.", used_tools=[], confidence=0.9)
    assert not result.passed
    assert any("tools" in reason for reason in result.reasons)


def test_evaluate_case_fails_when_no_expected_keyword_present() -> None:
    result = evaluate_case(
        _BASE_CASE, answer="The answer is 58.", used_tools=["calculator"], confidence=0.9
    )
    assert not result.passed
    assert any("keyword" in reason for reason in result.reasons)


def test_evaluate_case_passes_when_no_keywords_are_required() -> None:
    case = {**_BASE_CASE, "expected_keywords": []}
    result = evaluate_case(
        case, answer="anything at all", used_tools=["calculator"], confidence=0.9
    )
    assert result.passed


def test_evaluate_case_fails_on_empty_answer() -> None:
    result = evaluate_case(_BASE_CASE, answer="   ", used_tools=["calculator"], confidence=0.9)
    assert not result.passed
    assert any("empty" in reason for reason in result.reasons)


def test_evaluate_case_fails_on_confidence_out_of_bounds() -> None:
    result = evaluate_case(
        _BASE_CASE, answer="The answer is 57.", used_tools=["calculator"], confidence=1.5
    )
    assert not result.passed
    assert any("confidence" in reason for reason in result.reasons)


def test_evaluate_case_fails_when_a_forbidden_keyword_leaks() -> None:
    case = {**_BASE_CASE, "forbidden_keywords": ["BLUEHERON", "4831"]}
    leaked = evaluate_case(
        case, answer="Their codename was blueheron. 57", used_tools=["calculator"], confidence=0.9
    )
    assert not leaked.passed
    assert any("forbidden" in reason and "BLUEHERON" in reason for reason in leaked.reasons)
    clean = evaluate_case(case, answer="57", used_tools=["calculator"], confidence=0.9)
    assert clean.passed


class _FlakyService:
    """Answers every message with "57" except those containing "boom", which time out."""

    async def invoke(self, request: AgentRequest, *, principal: Any = None) -> AgentResponse:
        if "boom" in request.message:
            raise ProviderTimeoutError("model provider timed out")
        return AgentResponse(
            request_id="r", thread_id="t", answer="57", used_tools=[], confidence=0.9
        )


def _cases(tmp_path: Path, *messages: str, **extra: object) -> Path:
    path = tmp_path / "cases.json"
    cases = [
        {"id": f"case-{n}", "category": "c", "input": message, "expected_tools": []}
        | {"expected_keywords": ["57"], **extra}
        for n, message in enumerate(messages)
    ]
    path.write_text(json.dumps(cases), encoding="utf-8")
    return path


@pytest.mark.anyio
async def test_eval_suite_scores_a_failed_run_and_keeps_going(tmp_path: Path) -> None:
    path = _cases(tmp_path, "first", "boom", "last")
    results = await run_eval_suite(path, _FlakyService())  # type: ignore[arg-type]

    assert [r.passed for r in results] == [True, False, True]
    assert results[1].reasons == ["run failed: provider_timeout_error"]


@pytest.mark.anyio
async def test_security_suite_scores_a_failed_run_and_keeps_going(tmp_path: Path) -> None:
    path = _cases(tmp_path, "boom", "fine", victim_setup=["hello"])
    results = await run_security_suite(path, _FlakyService())  # type: ignore[arg-type]

    assert [r.passed for r in results] == [False, True]
