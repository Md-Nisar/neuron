"""Retrieval and citation metrics (RAG-08.01), on cases from the RAG-00.03 dataset."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from neuron_agent.retrieval_metrics import (
    ACCEPTABLE,
    INCORRECT,
    MISSING,
    PERFECT,
    Grade,
    Located,
    abstention_accuracy,
    answer_report,
    below_baseline,
    ci95,
    citation_source_precision,
    cited_correctly,
    first_hit_rank,
    grade_answer,
    is_correct,
    mean_reciprocal_rank,
    recall_at_k,
    retrieval_report,
    states,
)

_DATASET = json.loads(Path("tests/fixtures/knowledge_cases.json").read_text(encoding="utf-8"))
_CASES = {case["id"]: case for case in _DATASET["cases"]}
# answerable-001: nist-ai-100-1, page 17. answerable-042: rfc9457, two sections (a plain-text
# RFC without headings the parser sees). answerable-050: pgvector-readme, Markdown sections.
_PAGED = _CASES["answerable-001"]
_SECTIONED = _CASES["answerable-042"]
_MARKDOWN = _CASES["answerable-050"]


def test_the_cases_used_here_are_what_the_tests_assume() -> None:
    assert _PAGED["expected_sources"] == [{"document": "nist-ai-100-1", "pages": [17]}]
    [rfc] = _SECTIONED["expected_sources"]
    assert rfc["document"] == "rfc9457"
    assert "3.  The Problem Details JSON Object" in rfc["sections"]
    assert _SECTIONED["evidence"] == "application/problem+json"
    assert _MARKDOWN["expected_sources"][0]["sections"] == ["## HNSW", "## Half-Precision Indexing"]


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
        (("3.  The Problem Details JSON Object, continued",), False),  # whole headings only
        ((), False),
    ],
)
def test_a_sectioned_source_matches_on_a_heading(headings: tuple[str, ...], correct: bool) -> None:
    assert is_correct(_SECTIONED, Located("rfc9457", headings=headings)) is correct


@pytest.mark.parametrize(
    ("headings", "correct"),
    [
        (("pgvector", "Indexing", "HNSW"), True),  # the parser drops the `##`
        (("pgvector", "## Half-Precision Indexing"), True),
        (("pgvector", "IVFFlat"), False),
    ],
)
def test_a_markdown_section_matches_without_its_hashes(
    headings: tuple[str, ...], correct: bool
) -> None:
    assert is_correct(_MARKDOWN, Located("pgvector-readme", headings=headings)) is correct


def test_a_sectioned_source_matches_a_passage_holding_the_evidence() -> None:
    # A plain-text RFC's chunks have no headings: the case's evidence quote places them.
    holding = Located("rfc9457", text="...uses the media type\nApplication/Problem+JSON for...")
    assert is_correct(_SECTIONED, holding)
    assert not is_correct(_SECTIONED, Located("rfc9457", text="no quote here"))
    assert not is_correct(_SECTIONED, Located("rfc7519", text=holding.text))  # other document
    # Only sections are placed by text: a paged source needs its page.
    assert not is_correct(_PAGED, Located("nist-ai-100-1", 3, 3, text=_PAGED["evidence"]))


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
    answers: list[tuple[dict[str, Any], list[Located]]] = [
        (_PAGED, [right, wrong]),  # one of two citations correct: the answer counts
        (_PAGED, [wrong]),
        (_PAGED, []),  # cited nothing: no citation to score, but a miss for the answer
        (_SECTIONED, [Located("rfc9457", headings=("1.  Introduction",))]),
    ]
    assert citation_source_precision(answers) == 2 / 4
    assert cited_correctly(answers) == 2 / 4
    assert citation_source_precision([(_PAGED, [])]) is None
    assert (citation_source_precision([]), cited_correctly([])) == (None, None)


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
        "citation_source_precision": 1.0,
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
    baseline = {"recall_at_5": 0.918, "mrr": 0.819, "citation_source_precision": None}
    assert below_baseline({"recall_at_5": 0.9, "mrr": 0.82}, baseline, tolerance=0.02) == []
    assert below_baseline({"recall_at_5": 0.89, "mrr": 0.82}, baseline, tolerance=0.02) == [
        "recall_at_5 0.890 is below the baseline 0.918 - 0.020"
    ]
    # A metric the run did not measure, or the baseline lacks, is not compared.
    assert below_baseline({"citation_source_precision": 0.1}, baseline, tolerance=0.02) == []
    assert below_baseline({"mrr": None}, baseline, tolerance=0.02) == []


# answerable-037: two vital facts, 43 and 128.
_PKCE = _CASES["answerable-037"]


def test_a_fact_is_stated_by_any_of_its_phrases_as_a_whole_phrase() -> None:
    fact = {"fact": "UTF-8", "vital": True, "any": ["utf-8", "utf8"]}
    assert states(fact, "JSON text MUST use UTF-8.")
    assert states(fact, "encoded as  utf8")
    assert not states(fact, "UTF-16 only")
    # A number inside a longer number is not the fact.
    assert not states({"fact": "43", "vital": True, "any": ["43"]}, "between 143 and 1280")


def test_an_answer_is_graded_by_the_vital_facts_it_states() -> None:
    assert grade_answer(_PKCE, "From 43 to 128 characters.", False) == Grade(PERFECT, 2, 2)
    assert grade_answer(_PKCE, "At least 43 characters.", False) == Grade(ACCEPTABLE, 1, 2)
    assert grade_answer(_PKCE, "Between 32 and 96 characters.", False) == Grade(INCORRECT, 0, 2)
    # An abstention is a missing answer, whatever its text says.
    assert grade_answer(_PKCE, "43 to 128, but I am not sure.", True) == Grade(MISSING, 0, 2)


def test_every_answerable_case_has_a_vital_fact() -> None:
    for case in _DATASET["cases"]:
        if case["category"] == "answerable":
            assert any(fact["vital"] for fact in case["expected_facts"]), case["id"]


def test_the_interval_brackets_the_rate_and_narrows_with_more_cases() -> None:
    assert ci95(0, 0) is None
    low, high = ci95(9, 10) or [0.0, 0.0]
    assert low < 0.9 < high <= 1.0
    wide, narrow = ci95(45, 50), ci95(450, 500)
    assert wide and narrow and narrow[1] - narrow[0] < wide[1] - wide[0]
    assert ci95(10, 10) == [0.722, 1.0]


def _answers_schema() -> dict[str, Any]:
    schema = json.loads(Path("tests/fixtures/eval_report.schema.json").read_text("utf-8"))
    assert schema["properties"]["answers"] == {"$ref": "#/$defs/answers"}
    return {"$ref": "#/$defs/answers", "$defs": schema["$defs"]}


def test_the_answers_section_counts_labels_and_penalises_wrong_answers() -> None:
    grades = [
        Grade(PERFECT, 2, 2),
        Grade(ACCEPTABLE, 1, 2),
        Grade(INCORRECT, 0, 1),
        Grade(MISSING, 0, 1),
    ]
    section = answer_report(grades, [True, False])
    assert section["correct"]["value"] == 0.25
    assert section["partially_correct"]["value"] == 0.25
    assert section["false_refusal"]["value"] == 0.25
    # Wrong among attempted: one incorrect answer and one answered unanswerable case, of 4.
    assert section["hallucination"]["value"] == 0.5
    assert section["vital_fact_recall"]["value"] == 0.5
    # (1 + 0.5 - 1 + 0 + 1 - 1) / 6
    assert section["crag_score"] == 0.083
    jsonschema.Draft202012Validator(_answers_schema()).validate(section)
    empty = answer_report([], [])
    assert empty["correct"] == {"value": None, "ci95": None}
    assert empty["crag_score"] is None
    jsonschema.Draft202012Validator(_answers_schema()).validate(empty)
