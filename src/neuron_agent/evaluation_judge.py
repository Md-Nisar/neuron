# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""A model judge for claim-level faithfulness and citation support in the knowledge eval.

The judge splits an answer into claims and checks each against the passages the answer cited
and the passages retrieval returned (ALCE, RAGAS). From its verdicts:

- faithfulness: the share of claims some cited or retrieved passage supports;
- citation recall: the share of claims a cited passage supports;
- citation precision: the share of cited passages that support at least one claim.

A judge is a measuring instrument: its scores are not a release gate until they agree with
human labels (`cohen_kappa`, at least 0.6). Answers and passages are untrusted text; the judge
has no tools and its prompt frames them as data.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError

from neuron_agent.prompts.loader import load_prompt
from neuron_agent.retrieval_metrics import ci95

# Bumped with every change to `eval/claim_judge.md`; a test pins it to the file's hash.
JUDGE_PROMPT_VERSION = 1
KAPPA_GATE = 0.6


class ClaimVerdict(BaseModel):
    claim: str = Field(min_length=1)
    supported_by: list[str] = Field(default_factory=list)
    in_context: bool


class _Verdicts(BaseModel):
    claims: list[ClaimVerdict]


@dataclass(frozen=True)
class Judgement:
    """The judge's verdicts on one answer; `cited` is the number of passages it cited."""

    claims: tuple[ClaimVerdict, ...]
    cited: int


class JudgeError(Exception):
    """The judge's reply was not the JSON its prompt asks for."""


def _data(text: str) -> str:
    """Untrusted text with `<` escaped, as `tools/framing.py` does, so it cannot close its
    block or pose as a passage or an instruction."""
    return text.replace("<", chr(92) + "u003c")


def _passages(tag: str, prefix: str, texts: Sequence[str]) -> str:
    body = "\n".join(
        f'<passage id="{prefix}{i}">{_data(text)}</passage>' for i, text in enumerate(texts, 1)
    )
    return f"<{tag}>\n{body}\n</{tag}>"


def _parse(reply: str, cited: int) -> tuple[ClaimVerdict, ...]:
    text = re.sub(r"(?:^```(?:json)?\s*)|(?:\s*```$)", "", reply.strip())
    try:
        verdicts = _Verdicts.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise JudgeError(type(exc).__name__) from exc
    valid = {f"C{i}" for i in range(1, cited + 1)}
    # An id the answer did not cite cannot support a claim.
    return tuple(
        v.model_copy(update={"supported_by": sorted(set(v.supported_by) & valid)})
        for v in verdicts.claims
    )


async def judge_answer(
    model: Any,
    question: str,
    answer: str,
    cited: Sequence[str],
    context: Sequence[str],
) -> Judgement:
    """Judge `answer` against the texts of its `cited` passages and the retrieved `context`.
    Raises `JudgeError` when the judge's reply cannot be read."""
    prompt = "\n\n".join(
        (
            f"<question>{_data(question)}</question>",
            f"<answer>{_data(answer)}</answer>",
            _passages("cited", "C", cited),
            _passages("context", "R", context),
        )
    )
    reply = await model.ainvoke(
        [SystemMessage(load_prompt("eval/claim_judge.md")), HumanMessage(prompt)]
    )
    content = reply.content if isinstance(reply.content, str) else str(reply.content)
    return Judgement(_parse(content, len(cited)), len(cited))


def faithfulness_report(
    judgements: Sequence[Judgement], judge_model: str, judge_errors: int
) -> dict[str, Any]:
    """The eval report's `faithfulness` section (`eval_report.schema.json`)."""
    claims = [claim for j in judgements for claim in j.claims]
    cited = sum(j.cited for j in judgements)
    supporting = sum(len({c for claim in j.claims for c in claim.supported_by}) for j in judgements)

    def estimate(successes: int, total: int) -> dict[str, Any]:
        value = round(successes / total, 3) if total else None
        return {"value": value, "ci95": ci95(successes, total)}

    return {
        "judge_model": judge_model,
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
        "answers_judged": len(judgements),
        "claims": len(claims),
        "faithfulness": estimate(
            sum(c.in_context or bool(c.supported_by) for c in claims), len(claims)
        ),
        "citation_precision": estimate(supporting, cited),
        "citation_recall": estimate(sum(bool(c.supported_by) for c in claims), len(claims)),
        "judge_errors": judge_errors,
    }


def cohen_kappa(first: Sequence[object], second: Sequence[object]) -> float | None:
    """Cohen's kappa between two raters' labels of the same items (the judge and a person);
    None without items or when chance agreement is total."""
    if len(first) != len(second):
        raise ValueError("both raters must label the same items")
    if not first:
        return None
    n = len(first)
    observed = sum(a == b for a, b in zip(first, second, strict=True)) / n
    labels = set(first) | set(second)
    expected = sum((list(first).count(x) / n) * (list(second).count(x) / n) for x in labels)
    return None if expected == 1 else round((observed - expected) / (1 - expected), 3)
