from __future__ import annotations

import pytest

from neuron_agent.errors.base import ValidationAppError
from neuron_agent.tools.calculator import calculator


def test_calculator_evaluates_bounded_arithmetic() -> None:
    assert calculator.invoke({"expression": "2 + 3 * 4"}) == "14"


def test_calculator_rejects_function_calls() -> None:
    with pytest.raises(ValidationAppError):
        calculator.invoke({"expression": "__import__('os').system('whoami')"})


def test_calculator_rejects_huge_result() -> None:
    with pytest.raises(ValidationAppError):
        calculator.invoke({"expression": "10 ** 20"})


def test_calculator_rejects_oversized_expression() -> None:
    with pytest.raises(ValidationAppError):
        calculator.invoke({"expression": "1" + "+1" * 200})
