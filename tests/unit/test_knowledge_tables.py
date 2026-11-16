"""Typed tables from parsed spreadsheets (RAG-11.01; ADR 0014 amendment "tables")."""

from __future__ import annotations

from neuron_agent.knowledge.parsing import CSV, DOCX, XLSX, Block, ParsedDocument
from neuron_agent.knowledge.tables import MAX_TABLES, extract_tables


def _doc(*blocks: Block) -> ParsedDocument:
    return ParsedDocument(parser_version="test", blocks=blocks)


def _table(*rows: tuple[str, ...]) -> Block:
    return Block(kind="table", text="t", rows=rows)


def test_columns_are_typed_from_their_values_and_empty_cells_are_null() -> None:
    grid = _table(
        ("id", "units", "price", "zip", "day", "note"),
        ("1", "3", "2.5", "02134", "2026-01-02", "x"),
        ("2", "-12", "1e3", "90210", "2026-01-03", ""),
        ("3", "", "7", "10001", "2026-01-04", "7"),
    )
    (table,), skipped = extract_tables(_doc(grid), CSV, 1_000)
    assert skipped == 0
    assert table.columns == (
        ("id", "integer"),
        ("units", "integer"),
        ("price", "real"),
        ("zip", "text"),  # a leading zero makes it a code
        ("day", "text"),  # dates stay text
        ("note", "text"),
    )
    assert table.rows == (
        (1, 3, 2.5, "02134", "2026-01-02", "x"),
        (2, -12, 1000.0, "90210", "2026-01-03", None),
        (3, None, 7.0, "10001", "2026-01-04", "7"),
    )


def test_a_value_past_the_number_ranges_makes_the_column_text() -> None:
    grid = _table(
        ("big", "huge", "tiny", "inexact", "digits", "empty"),
        ("1" * 19, "1e999", "1e-999", str(2**53 + 1), "\u0661\u0662", ""),
        ("1", "1", "1", "1.5", "1", ""),
    )
    (table,), _ = extract_tables(_doc(grid), XLSX, 1_000)
    assert [kind for _, kind in table.columns] == ["text"] * 6
    assert table.rows[0] == ("1" * 19, "1e999", "1e-999", str(2**53 + 1), "\u0661\u0662", None)


def test_empty_and_repeated_names_become_column_n() -> None:
    grid = _table(("Units", "", "units", "column_4", " a  b ", "x"), ("1",) * 6)
    (table,), _ = extract_tables(_doc(grid), CSV, 1_000)
    names = [name for name, _ in table.columns]
    assert names == ["Units", "column_2", "column_3", "column_4", "a b", "x"]
    grid = _table(("column_2", ""), ("1", "2"))
    (table,), _ = extract_tables(_doc(grid), CSV, 1_000)
    assert [name for name, _ in table.columns] == ["column_2", "column_2_"]


def test_a_table_is_named_by_its_heading_or_its_place() -> None:
    blocks = (
        _table(("a",), ("1",)),
        Block(kind="heading", text="Orders", level=1),
        Block(kind="text", text="intro"),
        _table(("b",), ("2",)),
    )
    tables, _ = extract_tables(_doc(*blocks), XLSX, 1_000)
    assert [t.name for t in tables] == ["Table 1", "Orders"]


def test_only_spreadsheets_with_grids_and_rows_are_stored() -> None:
    grid = _table(("a",), ("1",))
    assert extract_tables(_doc(grid), DOCX, 1_000) == ([], 0)
    header_only = _table(("a", "b"))
    text_only = Block(kind="table", text="a | b")  # past the grid caps when parsed
    tables, skipped = extract_tables(_doc(header_only, text_only, grid), XLSX, 1_000)
    assert len(tables) == 1
    assert skipped == 1


def test_tables_past_the_document_caps_are_skipped_and_counted() -> None:
    small, big = _table(("a",), ("1",)), _table(("a", "b"), *[("1", "2")] * 10)
    tables, skipped = extract_tables(_doc(big, small, small), CSV, 24)
    assert [len(t.rows) for t in tables] == [10, 1]  # 22 cells and 2: a third table passes 24
    assert skipped == 1
    tables, skipped = extract_tables(_doc(*[small] * (MAX_TABLES + 2)), CSV, 1_000)
    assert len(tables) == MAX_TABLES
    assert skipped == 2
    assert extract_tables(_doc(small), CSV, 0) == ([], 1)
