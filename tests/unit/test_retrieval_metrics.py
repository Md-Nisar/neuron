"""Retrieval and citation metrics (RAG-08.01), on cases from the RAG-00.03 dataset."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from neuron_agent.retrieval_metrics import (
    Located,
    abstention_accuracy,
    below_baseline,
    citation_precision,
    cited_correctly,
    first_hit_rank,
    is_correct,
    mean_reciprocal_rank,
    recall_at_k,
    retrieval_report,
)

_DATASET = json.loads(Path("tests/fixtures/knowledge_cases.json").read_text(encoding="utf-8"))
_CASES = {case["id"]: case for case in _DATASET["cases"]}
# answerable-001: nist-ai-100-1, page 17. answerable-042: rfc9457, two sections.
_PAGED = _CASES["answerable-001"]["expected_sources"]
_SECTIONED = _CASES["answerable-042"]["expected_sources"]


def test_the_cases_used_here_are_what_the_tests_assume() -> None:
    assert _PAGED == [{"document": "nist-ai-100-1", "pages": [17]}]
    assert _SECTIONED[0]["document"] == "rfc9457"
    assert "3.  The Problem Details JSON Object" in _SECTIONED[0]["sections"]


@pytest.mark.parametrize(
    ("located", "correct"),
    [
        (Located("nist-ai-100-1", 17, 17), True),
        (Located("nist-ai-100-1", 15, 18), True),  # a passage spanning the page
        (Located("nist-ai-100-1", 17), True),  # no end page: the start page alone
        (Located("nist-ai-100-1", 16, 16), False),
        (Located("nist-ai-100-1"), False),  # no page at all
        (Located("nist-ai-600-1", 17, 17), False),  # right page, wrong document
    ],
)
def test_a_paged_source_matches_on_an_overlapping_page(located: Located, correct: bool) -> None:
    assert is_correct(_PAGED, located) is correct


@pytest.mark.parametrize(
    ("headings", "correct"),
    [
        (("3. The Problem Details JSON Object",), True),  # spacing differs
        (("RFC 9457", "3.  THE PROBLEM DETAILS JSON OBJECT"), True),  # any heading, any case
        (("3.  The Problem Details JSON Object", "3.1.  Members"), True),
        (("4.  Defining New Problem Types",), False),
        ((), False),
    ],
)
def test_a_sectioned_source_matches_on_a_heading(headings: tuple[str, ...], correct: bool) -> None:
    assert is_correct(_SECTIONED, Located("rfc9457", headings=headings)) is correct


def test_the_rank_is_the_first_correct_passage_counted_from_one() -> None:
    wrong, right = Located("nist-ai-100-1", 3, 3), Located("nist-ai-100-1", 17, 17)
    assert first_hit_rank(_PAGED, [right, wrong]) == 1
    assert first_hit_rank(_PAGED, [wrong, wrong, right, right]) == 3
    assert first_hit_rank(_PAGED, [wrong]) is None
    assert first_hit_rank(_PAGED, []) is None


def test_recall_and_mrr_over_ranks() -> None:
    ranks = [1, 2, 5, 6, None]
    assert recall_at_k(ranks) == 3 / 5
    assert recall_at_k(ranks, k=1) == 1 / 5
    assert mean_reciprocal_rank(ranks) == pytest.approx((1 + 1 / 2 + 1 / 5 + 1 / 6) / 5)
    assert (recall_at_k([None]), mean_reciprocal_rank([None])) == (0.0, 0.0)
    assert (recall_at_k([]), mean_reciprocal_rank([])) == (None, None)


def test_citation_precision_counts_citations_and_cited_correctly_counts_answers() -> None:
    right, wrong = Located("nist-ai-100-1", 17, 17), Located("nist-ai-100-1", 2, 2)
    answers: list[tuple[Any, list[Located]]] = [
        (_PAGED, [right, wrong]),  # one of two citations correct: the answer counts
        (_PAGED, [wrong]),
        (_PAGED, []),  # cited nothing: no citation to score, but a miss for the answer
        (_SECTIONED, [Located("rfc9457", headings=("1.  Introduction",))]),
    ]
    assert citation_precision(answers) == 2 / 4
    assert cited_correctly(answers) == 2 / 4
    assert citation_precision([(_PAGED, [])]) is None
    assert (citation_precision([]), cited_correctly([])) == (None, None)


def test_abstention_accuracy() -> None:
    assert abstention_accuracy([True, True, False, True]) == 3 / 4
    assert abstention_accuracy([]) is None


def _retrieval_schema() -> dict[str, Any]:
    schema = json.loads(Path("tests/fixtures/eval_report.schema.json").read_text("utf-8"))
    assert schema["properties"]["retrieval"] == {"$ref": "#/$defs/retrieval"}
    return {"$ref": "#/$defs/retrieval", "$defs": schema["$defs"]}


def test_the_report_section_holds_the_four_metrics_and_matches_the_schema() -> None:
    right = Located("nist-ai-100-1", 17, 17)
    section = retrieval_report("1.0.0", [1, 3, None], [(_PAGED, [right])], [True, False])
    assert section == {
        "dataset_version": "1.0.0",
        "answerable_cases": 3,
        "unanswerable_cases": 2,
        "recall_at_5": 0.667,
        "mrr": 0.444,
        "citation_precision": 1.0,
        "cited_correctly": 1.0,
        "abstention_accuracy": 0.5,
    }
    validator = jsonschema.Draft202012Validator(_retrieval_schema())
    validator.validate(section)
    # Search alone, without a model run: the model's rates are null, which the schema allows.
    validator.validate(retrieval_report("1.0.0", [1]))
    for broken in (
        {**section, "recall_at_5": 1.5},
        {**section, "extra": 1},
        {k: v for k, v in section.items() if k != "mrr"},
    ):
        with pytest.raises(jsonschema.ValidationError):
            validator.validate(broken)


def test_a_drop_beyond_the_tolerance_fails_and_a_small_one_does_not() -> None:
    baseline = {"recall_at_5": 0.918, "mrr": 0.819, "citation_precision": None}
    assert below_baseline({"recall_at_5": 0.9, "mrr": 0.82}, baseline, tolerance=0.02) == []
    assert below_baseline({"recall_at_5": 0.89, "mrr": 0.82}, baseline, tolerance=0.02) == [
        "recall_at_5 0.890 is below the baseline 0.918 - 0.020"
    ]
    # A metric the run did not measure, or the baseline lacks, is not compared.
    assert below_baseline({"citation_precision": 0.1}, baseline, tolerance=0.02) == []
    assert below_baseline({"mrr": None}, baseline, tolerance=0.02) == []
