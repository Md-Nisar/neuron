from __future__ import annotations

from neuron_agent.evaluation import evaluate_case

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
