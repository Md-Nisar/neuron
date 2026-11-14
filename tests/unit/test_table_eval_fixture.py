"""The table eval fixture is what its generator builds (RAG-11.01)."""

from __future__ import annotations

import json

from scripts.build_table_eval import CASES, ROWS, build


def test_the_committed_fixture_matches_the_generator() -> None:
    table, cases = build()
    assert CASES.read_text(encoding="utf-8") == cases, "run scripts/build_table_eval.py"
    assert table.count("\n") == ROWS + 1  # the header and every row
    assert build() == (table, cases)  # the seed makes it reproducible


def test_most_cases_need_every_row_and_each_has_an_answer() -> None:
    cases = json.loads(CASES.read_text(encoding="utf-8"))["cases"]
    kinds = [case["kind"] for case in cases]
    assert kinds.count("aggregate") == 6 and kinds.count("lookup") == 2
    assert all(case["answers"] and all(case["answers"]) for case in cases)
