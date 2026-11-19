"""The documents list's title search and orders (RAG-03.01): wildcards are matched literally,
and only fixed SQL fragments are used for the order."""

from __future__ import annotations

from typing import get_args

import pytest

from neuron_agent.knowledge.service import (
    _DOCUMENT_ORDER,
    _STATUS_GROUP,
    DocumentSort,
    DocumentStatusGroup,
    _title_pattern,
)


@pytest.mark.parametrize(
    ("query", "pattern"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("plan", "%plan%"),
        ("  plan  ", "%plan%"),
        ("50% off", "%50\\% off%"),
        ("a_b", "%a\\_b%"),
        ("c:\\temp", "%c:\\\\temp%"),
        ("\\%", "%\\\\\\%%"),
    ],
)
def test_the_title_search_matches_the_text_literally(
    query: str | None, pattern: str | None
) -> None:
    assert _title_pattern(query) == pattern


def test_every_sort_and_status_group_has_a_fixed_fragment() -> None:
    assert set(_DOCUMENT_ORDER) == set(get_args(DocumentSort))
    assert set(_STATUS_GROUP) == set(get_args(DocumentStatusGroup))
    # Each order ends on the id, so pages are stable when the first key ties.
    assert all(order.endswith("d.doc_id") for order in _DOCUMENT_ORDER.values())
