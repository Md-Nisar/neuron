"""Typed Tier 1 metric requests. The model emits this structure (JSON-schema constrained);
it never writes filter SQL. Names are validated against the semantic model, values are
typed and escaped by the server, operators come from a closed enum."""
from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Union

from pydantic import BaseModel, Field, field_validator

Scalar = Union[int, float, dt.date, str]


class Op(str, Enum):
    eq = "="
    ne = "!="
    gt = ">"
    gte = ">="
    lt = "<"
    lte = "<="
    in_ = "in"
    between = "between"


class Filter(BaseModel):
    dimension: str = Field(pattern=r"^[a-z][a-z0-9_]{0,62}(__[a-z0-9_]{1,62})?$")
    op: Op
    values: list[Scalar] = Field(min_length=1, max_length=100)

    @field_validator("values")
    @classmethod
    def no_control_chars(cls, v):
        for x in v:
            if isinstance(x, str) and any(ord(c) < 32 for c in x):
                raise ValueError("control characters not allowed in filter values")
        return v


class MetricRequest(BaseModel):
    metrics: list[str] = Field(min_length=1, max_length=10)
    group_by: list[str] = Field(default_factory=list, max_length=10)
    filters: list[Filter] = Field(default_factory=list, max_length=20)
    order_by: list[str] = Field(default_factory=list, max_length=5)
    limit: int = Field(default=1000, ge=1, le=1000)


class SemanticModel(BaseModel):
    metrics: set[str]
    dimensions: dict[str, str]   # name -> type: "categorical" | "time" | "number"


def validate_request(req: MetricRequest, model: SemanticModel) -> list[str]:
    errors = []
    errors += [f"unknown metric: {m}" for m in req.metrics if m not in model.metrics]
    errors += [f"unknown dimension: {d}" for d in req.group_by if d not in model.dimensions]
    for f in req.filters:
        if f.dimension not in model.dimensions:
            errors.append(f"unknown filter dimension: {f.dimension}")
        if f.op == Op.between and len(f.values) != 2:
            errors.append(f"between needs exactly 2 values: {f.dimension}")
        if f.op not in (Op.in_, Op.between) and len(f.values) != 1:
            errors.append(f"{f.op.value} needs exactly 1 value: {f.dimension}")
    return errors


def _literal(v: Scalar) -> str:
    if isinstance(v, bool):
        raise ValueError("booleans not supported")
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, dt.date):
        return "'" + v.isoformat() + "'"
    return "'" + str(v).replace("'", "''") + "'"


def to_metricflow_where(f: Filter, model: SemanticModel) -> str:
    """Compile one typed filter to a MetricFlow where-clause string, server-side only."""
    kind = model.dimensions[f.dimension]
    ref = (f"{{{{ TimeDimension('{f.dimension}') }}}}" if kind == "time"
           else f"{{{{ Dimension('{f.dimension}') }}}}")
    if f.op == Op.in_:
        return f"{ref} IN (" + ", ".join(_literal(v) for v in f.values) + ")"
    if f.op == Op.between:
        return f"{ref} BETWEEN {_literal(f.values[0])} AND {_literal(f.values[1])}"
    return f"{ref} {f.op.value} {_literal(f.values[0])}"
