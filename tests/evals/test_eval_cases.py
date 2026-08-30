from __future__ import annotations

from pathlib import Path

import pytest

from neuron_agent.evaluation import load_eval_cases

pytestmark = pytest.mark.eval


def test_eval_cases_have_required_fields() -> None:
    cases = load_eval_cases(Path("tests/fixtures/eval_cases.json"))
    assert cases
    for case in cases:
        assert set(case) >= {"id", "input", "expected_behavior", "category"}
