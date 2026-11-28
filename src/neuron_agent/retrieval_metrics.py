# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Retrieval, citation and answer metrics for the knowledge eval (RAG-08.01).

Deterministic and model-free: they score passages and citations against a case's
`expected_sources`, and answers against its `expected_facts`, in the RAG-00.03 dataset
(`tests/fixtures/knowledge_cases.json`). A source
names a document and either the pages or the sections that hold the answer. A section is
written as in the file (`## HNSW`, `1.  Introduction`); a plain-text RFC has no headings the
parser can see, so a sectioned source also matches a passage that holds the case's `evidence`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from neuron_agent.evaluation import wilson_interval

RECALL_K = 5


@dataclass(frozen=True)
class Located:
    """Where a passage or a citation is: the dataset's document id, its pages, headings and
    text (a citation's is its passage's)."""

    document: str
    page_start: int | None = None
    page_end: int | None = None
    headings: tuple[str, ...] = ()
    text: str = ""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower().strip()


def _heading(text: str) -> str:
    return _norm(text.lstrip("#"))


Case = Mapping[str, Any]  # an answerable case of the dataset
Answer = tuple[Case, Sequence[Located]]  # a case and its answer's citations


def is_correct(case: Case, located: Located) -> bool:
    """Whether `located` is in one of `case`'s expected sources: one of its pages, or one of
    its sections, as a heading (ignoring Markdown `#`s, case and spacing) or by holding the
    case's `evidence`."""
    evidence = _norm(case.get("evidence", ""))
    for source in case["expected_sources"]:
        if source["document"] != located.document:
            continue
        pages = set(source.get("pages", ()))
        if pages and located.page_start is not None:
            end = located.page_end if located.page_end is not None else located.page_start
            if pages & set(range(located.page_start, end + 1)):
                return True
        sections = {_heading(s) for s in source.get("sections", ())}
        if sections and (
            sections & {_heading(h) for h in located.headings}
            or (evidence and evidence in _norm(located.text))
        ):
            return True
    return False


def first_hit_rank(case: Case, passages: Sequence[Located]) -> int | None:
    """The 1-based rank of the first passage in an expected source, or None if none is."""
    return next((i for i, p in enumerate(passages, 1) if is_correct(case, p)), None)


def recall_at_k(ranks: Sequence[int | None], k: int = RECALL_K) -> float | None:
    """The share of cases whose first hit is in the top `k`; None without cases."""
    return sum(r is not None and r <= k for r in ranks) / len(ranks) if ranks else None


def mean_reciprocal_rank(ranks: Sequence[int | None]) -> float | None:
    """The mean of 1/rank of each case's first hit, 0 for a miss; None without cases."""
    return sum(1 / r for r in ranks if r) / len(ranks) if ranks else None


def citation_source_precision(answers: Sequence[Answer]) -> float | None:
    """The share of all citations, over answerable cases' answers, that are in an expected
    source; None if nothing was cited. Not the literature's citation precision, which asks
    whether each citation supports its sentence (`evaluation_judge`)."""
    verdicts = [is_correct(case, c) for case, cited in answers for c in cited]
    return sum(verdicts) / len(verdicts) if verdicts else None


def cited_correctly(answers: Sequence[Answer]) -> float | None:
    """The share of answerable cases whose answer cites at least one expected source (the
    v1.1.0 gate asks for 90%); None without cases."""
    if not answers:
        return None
    return sum(any(is_correct(case, c) for c in cited) for case, cited in answers) / len(answers)


def abstention_accuracy(abstained: Sequence[bool]) -> float | None:
    """The share of unanswerable cases whose answer abstained; None without cases. The caller
    decides what abstaining is (for a run: `grounded` false and nothing cited)."""
    return sum(abstained) / len(abstained) if abstained else None


def retrieval_report(
    dataset_version: str,
    ranks: Sequence[int | None],
    answers: Sequence[Answer] = (),
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
        "citation_source_precision": rounded(citation_source_precision(answers)),
        "cited_correctly": rounded(cited_correctly(answers)),
        "abstention_accuracy": rounded(abstention_accuracy(abstained)),
    }


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def _phrase(text: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(_norm(text))}(?![a-z0-9])")


def states(fact: Mapping[str, Any], text: str) -> bool:
    """Whether `text` states `fact`: one of its `any` phrases appears as a whole phrase,
    ignoring case and spacing. A paraphrase outside the list counts as not stated."""
    normalized = _norm(text)
    return any(_phrase(alias).search(normalized) for alias in fact["any"])


PERFECT, ACCEPTABLE, MISSING, INCORRECT = "perfect", "acceptable", "missing", "incorrect"
# CRAG's scores (Yang et al., 2024): a wrong answer costs more than no answer.
CRAG_SCORE = {PERFECT: 1.0, ACCEPTABLE: 0.5, MISSING: 0.0, INCORRECT: -1.0}


@dataclass(frozen=True)
class Grade:
    """An answerable case's answer, graded against its expected facts."""

    label: str  # PERFECT, ACCEPTABLE, MISSING (abstained) or INCORRECT
    vital_stated: int
    vital_total: int


def grade_answer(case: Case, text: str, abstained: bool) -> Grade:
    """Grade an answer to an answerable case: missing when it abstained, perfect when it
    states every vital fact, acceptable when it states some, incorrect when it states none."""
    vital = [fact for fact in case["expected_facts"] if fact["vital"]]
    stated = 0 if abstained else sum(states(fact, text) for fact in vital)
    if abstained:
        label = MISSING
    elif stated == len(vital):
        label = PERFECT
    else:
        label = ACCEPTABLE if stated else INCORRECT
    return Grade(label, stated, len(vital))


def ci95(successes: int, total: int) -> list[float] | None:
    """The 95% Wilson interval of a rate, rounded; None without trials. Repeated trials of one
    case are not independent, so on pooled trials the interval is too narrow."""
    interval = wilson_interval(successes, total)
    return None if interval is None else [round(bound, 3) for bound in interval]


def answer_report(
    grades: Sequence[Grade], unanswerable_abstained: Sequence[bool]
) -> dict[str, Any]:
    """The eval report's `answers` section (`eval_report.schema.json`): how answers to
    answerable cases score against their expected facts, the false-refusal and hallucination
    rates, and CRAG's score over answerable and unanswerable cases. Rates carry a 95% Wilson
    interval. Trials may be pooled: pass every trial's grades (the intervals are then too
    narrow, see `ci95`)."""
    total = len(grades)
    count = {label: sum(g.label == label for g in grades) for label in CRAG_SCORE}
    attempted = total - count[MISSING]
    answered_unanswerable = sum(not a for a in unanswerable_abstained)

    def rate(successes: int, n: int) -> dict[str, Any]:
        return {"value": _rounded(successes / n if n else None), "ci95": ci95(successes, n)}

    scores = [CRAG_SCORE[g.label] for g in grades] + [
        1.0 if a else -1.0 for a in unanswerable_abstained
    ]
    return {
        "answerable_answers": total,
        "unanswerable_answers": len(unanswerable_abstained),
        "correct": rate(count[PERFECT], total),
        "partially_correct": rate(count[ACCEPTABLE], total),
        "incorrect": rate(count[INCORRECT], total),
        "false_refusal": rate(count[MISSING], total),
        "hallucination": rate(
            count[INCORRECT] + answered_unanswerable, attempted + answered_unanswerable
        ),
        "vital_fact_recall": rate(
            sum(g.vital_stated for g in grades), sum(g.vital_total for g in grades)
        ),
        "crag_score": _rounded(sum(scores) / len(scores) if scores else None),
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


# The hard-question set (RAG-13.02, `tests/fixtures/knowledge/hard/`): a case needs every one of
# its `required_sources`, each a document and, unless the benchmark names only the article, the
# first sentence of the passage (`evidence`).
Source = Mapping[str, Any]
RETRIEVAL_MISS, RANKING, FOLLOW_UP, SYNTHESIS, FALSE_ABSTENTION = (
    "retrieval_miss",
    "ranking",
    "follow_up_not_resolved",
    "synthesis",
    "false_abstention",
)


def holds(source: Source, located: Located) -> bool:
    """Whether `located` is the source: its document and, if it names one, its passage."""
    evidence = source["evidence"]
    return source["document"] == located.document and (
        evidence is None or _norm(evidence) in _norm(located.text)
    )


def source_ranks(sources: Sequence[Source], passages: Sequence[Located]) -> list[int | None]:
    """Each source's 1-based rank of the first passage that holds it, or None if none does."""
    return [next((i for i, p in enumerate(passages, 1) if holds(s, p)), None) for s in sources]


def complete_rank(ranks: Sequence[int | None]) -> int | None:
    """The rank by which every source was found (the worst rank), or None if one never was.
    `recall_at_k` over these is complete recall@k: every required source in the top k."""
    return None if not ranks or None in ranks else max(r for r in ranks if r is not None)


def first_rank(ranks: Sequence[int | None]) -> int | None:
    """The rank of the first source found, for MRR, or None if none was."""
    return min((r for r in ranks if r is not None), default=None)


def classify_failure(
    *,
    abstained: bool,
    seen: bool,
    complete: int | None,
    k: int,
    standalone_complete: int | None = None,
) -> str:
    """Why an answerable case's answer failed.

    `seen` is whether the agent's own searches returned every source. If they did, the answer
    abstained (a false abstention) or was wrong (synthesis). If not, a search for the question
    decides: `complete` is its complete rank among the candidates (None: a source is not among
    them), `standalone_complete` the same for a follow-up's standalone rewrite. Sources found
    in the top `k` for the rewrite but not for the turn's own words mean the follow-up was not
    resolved; otherwise they were found, but not where the agent looked (ranking), or never
    found (a retrieval miss).
    """
    if seen:
        return FALSE_ABSTENTION if abstained else SYNTHESIS
    in_top = complete is not None and complete <= k
    if not in_top and standalone_complete is not None and standalone_complete <= k:
        return FOLLOW_UP
    return RANKING if complete is not None else RETRIEVAL_MISS
