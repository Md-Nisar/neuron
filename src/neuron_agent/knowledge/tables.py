# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Typed tables from a parsed spreadsheet, stored for `query_table` (RAG-11.01).

ADR 0014 amendment "tables": only XLSX and CSV tables are stored, from `table` blocks that
carry a cell grid. The first row is the header; an empty or repeated name (SQLite compares
names without case) becomes `column_<n>`. A column is `integer` or `real` when every value in it
is one, else `text`, and dates stay text. A table over a cap stays searchable but is not stored.
"""

from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass

from neuron_agent.knowledge.parsing import CSV, XLSX, ParsedDocument

MAX_TABLES = 20
QUERYABLE_TYPES = frozenset({XLSX, CSV})
_NAME_CHARS = 100
_TITLE_CHARS = 300
# ASCII digits, no leading zeros (`02134` is a code), at most 18 digits (SQLite's int64). A
# two-digit exponent keeps a real from overflowing or silently underflowing to 0.
_INTEGER = re.compile(r"[+-]?(?:0|[1-9](?:[0-9]{0,17}|[0-9]{0,2}(?:,[0-9]{3}){1,5}))")
_REAL = re.compile(
    r"[+-]?(?:(?:0|[1-9](?:[0-9]*|[0-9]{0,2}(?:,[0-9]{3})+))(?:\.[0-9]+)?|\.[0-9]+)"
    r"(?:[eE][+-]?[0-9]{1,2})?"
)
_EXACT = 2**53  # the largest integer a float holds exactly

Value = int | float | str | None


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[tuple[str, str], ...]  # (name, type)
    rows: tuple[tuple[Value, ...], ...]


@dataclass(frozen=True)
class FoundTable:
    """A stored table as `find_tables` lists it (RAG-11.01)."""

    doc_id: uuid.UUID
    position: int
    title: str
    name: str
    columns: list[dict[str, str]]
    row_count: int
    sample: list[list[Value]]


@dataclass(frozen=True)
class StoredTable:
    """A stored table as `query_table` loads it."""

    title: str
    name: str
    columns: list[dict[str, str]]
    rows: list[list[Value]]


def extract_tables(
    parsed: ParsedDocument, media_type: str, max_cells: int
) -> tuple[list[Table], int]:
    """The document's tables in order, and how many were left out over a cap."""
    if media_type not in QUERYABLE_TYPES:
        return [], 0
    tables: list[Table] = []
    skipped = cells = 0
    heading: str | None = None
    named: Counter[str] = Counter()
    for block in parsed.blocks:
        if block.kind == "heading":
            heading = block.text
        if block.kind != "table":
            continue
        if block.rows is None:
            skipped += 1
            continue
        if len(block.rows) < 2:  # a header alone has nothing to query
            continue
        size = len(block.rows) * len(block.rows[0])
        if len(tables) == MAX_TABLES or cells + size > max_cells:
            skipped += 1
            continue
        cells += size
        name = (heading or f"Table {len(tables) + 1}")[: _TITLE_CHARS - 5]
        named[name] += 1
        if named[name] > 1:  # two tables under one heading
            name = f"{name} ({named[name]})"
        tables.append(_typed(name, block.rows))
    return tables, skipped


def _typed(name: str, grid: tuple[tuple[str, ...], ...]) -> Table:
    header, body = grid[0], grid[1:]
    kinds = [_kind([row[i] for row in body]) for i in range(len(header))]
    rows = tuple(
        tuple(_value(cell, kind) for cell, kind in zip(row, kinds, strict=True)) for row in body
    )
    return Table(name, tuple(zip(_names(header), kinds, strict=True)), rows)


def _names(header: tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    names = []
    for n, raw in enumerate(header, 1):
        name = " ".join(raw.split())[:_NAME_CHARS]
        if not name or name.casefold() in seen:
            name = f"column_{n}"
            while name.casefold() in seen:  # a header that already names one `column_<n>`
                name += "_"
        seen.add(name.casefold())
        names.append(name)
    return names


def _kind(values: list[str]) -> str:
    present = [v for v in values if v]
    if present and all(_INTEGER.fullmatch(v) for v in present):
        return "integer"
    if present and all(_real(v) for v in present):
        return "real"
    return "text"


def _real(value: str) -> bool:
    """A decimal, or an integer a float holds exactly: a longer one is an id, not a number to
    round."""
    if _INTEGER.fullmatch(value):
        return abs(int(value.replace(",", ""))) <= _EXACT
    return (
        _REAL.fullmatch(value) is not None
        and not value.lstrip("+-").replace(",", "").isdigit()
        and math.isfinite(float(value.replace(",", "")))
    )


def _value(cell: str, kind: str) -> Value:
    if not cell:
        return None
    if kind == "integer":
        return int(cell.replace(",", ""))
    if kind == "real":
        return float(cell.replace(",", ""))
    return cell
