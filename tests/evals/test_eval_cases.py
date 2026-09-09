from __future__ import annotations

from pathlib import Path

import pytest

from neuron_agent.evaluation import EVAL_CATEGORIES, load_eval_cases

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
