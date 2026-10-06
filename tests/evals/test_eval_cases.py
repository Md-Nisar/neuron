from __future__ import annotations

from pathlib import Path

import pytest

from neuron_agent.evaluation import (
    EVAL_CATEGORIES,
    MULTI_TURN_CASES,
    MULTI_TURN_EVAL_CATEGORIES,
    SINGLE_TURN_CASES,
    load_eval_cases,
)

pytestmark = pytest.mark.eval

_REQUIRED_FIELDS = {
    "id",
    "input",
    "expected_behavior",
    "category",
    "expected_tools",
    "expected_keywords",
}


def test_eval_cases_have_required_fields() -> None:
    cases = load_eval_cases(Path("tests/fixtures/eval_cases.json"))
    assert cases
    for case in cases:
        assert set(case) >= _REQUIRED_FIELDS
        assert isinstance(case["expected_tools"], list)
        assert isinstance(case["expected_keywords"], list)


def test_eval_cases_cover_every_required_category() -> None:
    cases = load_eval_cases(Path("tests/fixtures/eval_cases.json"))
    categories = {case["category"] for case in cases}
    assert categories == EVAL_CATEGORIES


def test_eval_case_ids_are_unique() -> None:
    cases = load_eval_cases(Path("tests/fixtures/eval_cases.json"))
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))


def test_multi_turn_cases_have_required_fields() -> None:
    cases = load_eval_cases(MULTI_TURN_CASES)
    assert len(cases) >= 10
    for case in cases:
        assert set(case) >= _REQUIRED_FIELDS | {"setup"}
        setup = case["setup"]
        assert isinstance(setup, list) and setup, f"{case['id']} needs earlier turns"
        assert all(isinstance(turn, str) and turn for turn in setup)


def test_multi_turn_cases_cover_every_required_category() -> None:
    categories = {case["category"] for case in load_eval_cases(MULTI_TURN_CASES)}
    assert categories == MULTI_TURN_EVAL_CATEGORIES


def test_eval_case_ids_are_unique_across_datasets() -> None:
    ids = [
        case["id"]
        for path in (SINGLE_TURN_CASES, MULTI_TURN_CASES)
        for case in load_eval_cases(path)
    ]
    assert len(ids) == len(set(ids))
