"""Bounded arithmetic tool."""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from typing import Any

from langchain_core.tools import tool

from neuron_agent.errors.base import ValidationAppError

Number = int | float

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[Number, Number], Number]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPERATORS: dict[type[ast.unaryop], Callable[[Number], Number]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_MAX_ABS_RESULT = 10**12
_MAX_EXPRESSION_LENGTH = 200


@tool
def calculator(expression: str) -> str:
    """Evaluate a simple arithmetic expression with no names, calls, or attributes."""
    if len(expression) > _MAX_EXPRESSION_LENGTH:
        raise ValidationAppError(f"expression exceeds {_MAX_EXPRESSION_LENGTH} character limit")
    try:
        parsed = ast.parse(expression, mode="eval")
        result = _evaluate(parsed.body)
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, RecursionError) as exc:
        raise ValidationAppError(f"invalid arithmetic expression: {exc}") from exc
    if abs(float(result)) > _MAX_ABS_RESULT:
        raise ValidationAppError("calculator result exceeds configured bound")
    return str(result)


def _evaluate(node: ast.AST) -> Number:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return node.value
    if isinstance(node, ast.BinOp):
        operator_fn = _BINARY_OPERATORS.get(type(node.op))
        if operator_fn is None:
            raise ValueError("unsupported operator")
        return _coerce_number(operator_fn(_evaluate(node.left), _evaluate(node.right)))
    if isinstance(node, ast.UnaryOp):
        unary_operator_fn = _UNARY_OPERATORS.get(type(node.op))
        if unary_operator_fn is None:
            raise ValueError("unsupported unary operator")
        return _coerce_number(unary_operator_fn(_evaluate(node.operand)))
    raise ValueError("unsupported expression syntax")


def _coerce_number(value: Any) -> Number:
    if not isinstance(value, int | float):
        raise ValueError("expression did not produce a number")
    return value
