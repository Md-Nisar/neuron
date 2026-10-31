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


def test_calculator_rejects_dangerous_exponentiation() -> None:
    # Large exponent or nested exponentiation that would cause CPU/GIL starvation
    with pytest.raises(ValidationAppError, match="exponent exceeds safety limit"):
        calculator.invoke({"expression": "9 ** 9 ** 9"})
    with pytest.raises(ValidationAppError, match="exponent exceeds safety limit"):
        calculator.invoke({"expression": "2 ** 1000000"})


@pytest.mark.parametrize(
    "expression",
    [
        "7 // 2",  # floor division is not on the allow-list
        "1 << 2",
        "5 & 3",
        "~5",  # unsupported unary operator
        "not 1",
        "x + 1",  # names are not evaluated
        "'a' + 'b'",  # strings are not numbers
        "[1, 2][0]",
        "1 if 1 else 2",
        "1 / 0",
        "(-8) ** 0.5",  # the result is complex, not a number
    ],
)
def test_calculator_rejects_everything_outside_plain_arithmetic(expression: str) -> None:
    with pytest.raises(ValidationAppError):
        calculator.invoke({"expression": expression})


@pytest.mark.parametrize(
    ("expression", "expected"),
    [("-3 + 5", "2"), ("+4", "4"), ("7 % 4", "3"), ("2 ** 10", "1024"), ("9 / 2", "4.5")],
)
def test_calculator_supports_the_documented_operators(expression: str, expected: str) -> None:
    assert calculator.invoke({"expression": expression}) == expected
