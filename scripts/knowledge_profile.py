"""Where an answer's time and tokens go (RAG-14.01): p50/p95 per stage, tokens per answer.

    uv run python scripts/knowledge_profile.py SPANS.jsonl [--json]

`SPANS.jsonl` is a live eval run's spans, as `dump` writes them (the hard-question eval writes
it to `APP_KNOWLEDGE_EVAL_SPANS`). A record keeps a span's ids, name, duration and only the
attributes in `KEPT`, so the file and the report hold no query, passage, answer or title.

Stages: each search stage (`search.embed`, `search.fts`, `search.dense`, `search.fuse`,
`search.passages`, `search.rerank`) and the whole search (`search`), each model turn
(`model_turn`), each tool call (`tool`), the citation check (`citations`) and the whole answer
(`answer`). An answer is one `invoke_agent` span and everything in its trace; a failed answer
(its `invoke_agent` span has `error.type`, such as a provider's rate limit) is left out and
counted in `failed_answers`, so the profile is of answers that finished.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan

from neuron_agent.observability import semconv

KEPT = (
    semconv.ERROR_TYPE,  # a stable code, never a message
    semconv.GEN_AI_OPERATION_NAME,
    semconv.GEN_AI_USAGE_INPUT_TOKENS,
    semconv.GEN_AI_USAGE_OUTPUT_TOKENS,
    semconv.NEURON_KNOWLEDGE_SEARCH_STAGE,
)
_SEARCH = semconv.KNOWLEDGE_SEARCH_SPAN


def record(span: ReadableSpan) -> dict[str, Any]:
    """A span as one JSON line: ids, name, milliseconds and the `KEPT` attributes only."""
    assert span.start_time is not None and span.end_time is not None  # nosec B101
    attributes = span.attributes or {}
    return {
        "trace": f"{span.context.trace_id:032x}",
        "name": span.name,
        "ms": round((span.end_time - span.start_time) / 1e6, 3),
        "attributes": {k: attributes[k] for k in KEPT if k in attributes},
    }


def dump(spans: Iterable[ReadableSpan], path: Path) -> None:
    with path.open("w", encoding="utf-8") as out:
        for span in spans:
            out.write(json.dumps(record(span), sort_keys=True) + "\n")


def stage(rec: Mapping[str, Any]) -> str | None:
    """The stage a span measures, or None for a span the profile does not count."""
    name, operation = rec["name"], rec["attributes"].get(semconv.GEN_AI_OPERATION_NAME)
    if name == _SEARCH:
        return "search"
    if name.startswith(f"{_SEARCH}."):
        return "search." + name.removeprefix(f"{_SEARCH}.")
    if name == semconv.CITATIONS_VALIDATE_SPAN:
        return "citations"
    return {
        semconv.OPERATION_INVOKE_AGENT: "answer",
        semconv.OPERATION_CHAT: "model_turn",
        semconv.OPERATION_EXECUTE_TOOL: "tool",
    }.get(operation)


def percentile(values: Sequence[float], p: float) -> float:
    """The nearest-rank percentile (`p` from 0 to 100) of a non-empty list."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def _summary(values: Sequence[float], digits: int) -> dict[str, float | int]:
    return {
        "count": len(values),
        "p50": round(percentile(values, 50), digits),
        "p95": round(percentile(values, 95), digits),
        "mean": round(sum(values) / len(values), digits),
    }


def profile(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Milliseconds per stage, and per answer: model turns and tokens in and out."""
    records = list(records)
    failed = {
        rec["trace"]
        for rec in records
        if stage(rec) == "answer" and semconv.ERROR_TYPE in rec["attributes"]
    }
    durations: dict[str, list[float]] = defaultdict(list)
    answers: set[str] = set()
    turns: dict[str, int] = defaultdict(int)
    tokens: dict[str, dict[str, int]] = defaultdict(lambda: {"input": 0, "output": 0})
    for rec in records:
        if (name := stage(rec)) is None or rec["trace"] in failed:
            continue
        durations[name].append(float(rec["ms"]))
        if name == "answer":
            answers.add(rec["trace"])
        elif name == "model_turn":
            turns[rec["trace"]] += 1
            attributes = rec["attributes"]
            tokens[rec["trace"]]["input"] += int(
                attributes.get(semconv.GEN_AI_USAGE_INPUT_TOKENS, 0)
            )
            tokens[rec["trace"]]["output"] += int(
                attributes.get(semconv.GEN_AI_USAGE_OUTPUT_TOKENS, 0)
            )
    per_answer = sorted(answers)
    return {
        "answers": len(per_answer),
        "failed_answers": len(failed),
        "stages_ms": {name: _summary(values, 1) for name, values in sorted(durations.items())},
        "per_answer": {
            "model_turns": _summary([turns[t] for t in per_answer], 1) if per_answer else None,
            "input_tokens": _summary([tokens[t]["input"] for t in per_answer], 0)
            if per_answer
            else None,
            "output_tokens": _summary([tokens[t]["output"] for t in per_answer], 0)
            if per_answer
            else None,
        },
    }


def table(report: Mapping[str, Any]) -> str:
    lines = [
        f"{report['answers']} answers ({report['failed_answers']} failed, left out)",
        "",
        "| Stage | Spans | p50 ms | p95 ms | Mean ms |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, s in report["stages_ms"].items():
        lines.append(f"| {name} | {s['count']} | {s['p50']} | {s['p95']} | {s['mean']} |")
    lines += ["", "| Per answer | p50 | p95 | Mean |", "| --- | ---: | ---: | ---: |"]
    for name, s in report["per_answer"].items():
        if s is not None:
            lines.append(f"| {name} | {s['p50']} | {s['p95']} | {s['mean']} |")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("spans", type=Path)
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)
    with args.spans.open(encoding="utf-8") as source:
        report = profile(json.loads(line) for line in source if line.strip())
    print(json.dumps(report, indent=2) if args.json else table(report))


if __name__ == "__main__":
    main()
