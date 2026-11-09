# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Retrieval and citation metrics for the knowledge eval (RAG-08.01).

Deterministic and model-free: they score passages and citations against a case's
`expected_sources` in the RAG-00.03 dataset (`tests/fixtures/knowledge_cases.json`). A source
names a document and either the pages or the sections that hold the answer.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

RECALL_K = 5


@dataclass(frozen=True)
class Located:
    """Where a passage or a citation is: the dataset's document id, its pages and headings."""

    document: str
    page_start: int | None = None
    page_end: int | None = None
    headings: tuple[str, ...] = ()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower().strip()


def is_correct(sources: Sequence[Mapping[str, Any]], located: Located) -> bool:
    """Whether `located` is in an expected source: one of its pages, or under one of its
    sections (a heading containing the section's text, ignoring case and spacing)."""
    for source in sources:
        if source["document"] != located.document:
            continue
        pages = set(source.get("pages", ()))
        if pages and located.page_start is not None:
            end = located.page_end if located.page_end is not None else located.page_start
            if pages & set(range(located.page_start, end + 1)):
                return True
        sections = [_norm(s) for s in source.get("sections", ())]
        if any(s in _norm(h) for s in sections for h in located.headings):
            return True
    return False


def first_hit_rank(sources: Sequence[Mapping[str, Any]], passages: Sequence[Located]) -> int | None:
    """The 1-based rank of the first passage in an expected source, or None if none is."""
    return next((i for i, p in enumerate(passages, 1) if is_correct(sources, p)), None)


def recall_at_k(ranks: Sequence[int | None], k: int = RECALL_K) -> float | None:
    """The share of cases whose first hit is in the top `k`; None without cases."""
    return sum(r is not None and r <= k for r in ranks) / len(ranks) if ranks else None


def mean_reciprocal_rank(ranks: Sequence[int | None]) -> float | None:
    """The mean of 1/rank of each case's first hit, 0 for a miss; None without cases."""
    return sum(1 / r for r in ranks if r) / len(ranks) if ranks else None


def citation_precision(
    answers: Sequence[tuple[Sequence[Mapping[str, Any]], Sequence[Located]]],
) -> float | None:
    """The share of all citations, over answerable cases' answers, that are in an expected
    source. `answers` pairs each case's sources with its answer's citations; None if nothing
    was cited."""
    verdicts = [is_correct(sources, c) for sources, cited in answers for c in cited]
    return sum(verdicts) / len(verdicts) if verdicts else None


def cited_correctly(
    answers: Sequence[tuple[Sequence[Mapping[str, Any]], Sequence[Located]]],
) -> float | None:
    """The share of answerable cases whose answer cites at least one expected source (the
    v1.1.0 gate asks for 90%); None without cases."""
    if not answers:
        return None
    return sum(any(is_correct(s, c) for c in cited) for s, cited in answers) / len(answers)


def abstention_accuracy(abstained: Sequence[bool]) -> float | None:
    """The share of unanswerable cases whose answer abstained; None without cases. The caller
    decides what abstaining is (for a run: `grounded` false and nothing cited)."""
    return sum(abstained) / len(abstained) if abstained else None


def retrieval_report(
    dataset_version: str,
    ranks: Sequence[int | None],
    answers: Sequence[tuple[Sequence[Mapping[str, Any]], Sequence[Located]]] = (),
    abstained: Sequence[bool] = (),
) -> dict[str, Any]:
    """The eval report's `retrieval` section (`eval_report.schema.json`). `ranks` holds each
    answerable case's first-hit rank from search; `answers` and `abstained` come from a model
    run and stay empty (their rates null) without one."""

    def rounded(value: float | None) -> float | None:
        return None if value is None else round(value, 3)

    return {
        "dataset_version": dataset_version,
        "answerable_cases": len(ranks),
        "unanswerable_cases": len(abstained),
        "recall_at_5": rounded(recall_at_k(ranks)),
        "mrr": rounded(mean_reciprocal_rank(ranks)),
        "citation_precision": rounded(citation_precision(answers)),
        "cited_correctly": rounded(cited_correctly(answers)),
        "abstention_accuracy": rounded(abstention_accuracy(abstained)),
    }


def below_baseline(
    metrics: Mapping[str, float | None],
    baseline: Mapping[str, float | None],
    tolerance: float,
) -> list[str]:
    """The metrics that fell more than `tolerance` below the baseline, as messages. A metric
    missing on either side is not compared."""
    return [
        f"{name} {value:.3f} is below the baseline {floor:.3f} - {tolerance:.3f}"
        for name, floor in baseline.items()
        if floor is not None
        and (value := metrics.get(name)) is not None
        and value < floor - tolerance
    ]
