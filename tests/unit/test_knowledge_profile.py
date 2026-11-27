"""The latency and token profile (RAG-14.01): stages, percentiles, tokens, and no text."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from scripts.knowledge_profile import dump, main, percentile, profile

from neuron_agent.observability import semconv

_SECRET = "profile-marker-question-8812"  # noqa: S105 - a marker, not a secret


def _rec(trace: str, name: str, ms: float, **attributes: Any) -> dict[str, Any]:
    return {"trace": trace, "name": name, "ms": ms, "attributes": attributes}


def _answer(trace: str, total: float, turns: list[tuple[int, int]]) -> list[dict[str, Any]]:
    op = semconv.GEN_AI_OPERATION_NAME
    records = [_rec(trace, "invoke_agent neuron", total, **{op: semconv.OPERATION_INVOKE_AGENT})]
    for tokens_in, tokens_out in turns:
        records.append(
            _rec(
                trace,
                "chat m",
                100.0,
                **{
                    op: semconv.OPERATION_CHAT,
                    semconv.GEN_AI_USAGE_INPUT_TOKENS: tokens_in,
                    semconv.GEN_AI_USAGE_OUTPUT_TOKENS: tokens_out,
                },
            )
        )
    records += [
        _rec(trace, semconv.KNOWLEDGE_SEARCH_SPAN, 30.0),
        _rec(trace, f"{semconv.KNOWLEDGE_SEARCH_SPAN}.embed", 20.0),
        _rec(trace, semconv.CITATIONS_VALIDATE_SPAN, 0.1),
        _rec(trace, "neuron.stream", 5.0),  # not a stage
    ]
    return records


def test_percentile_is_nearest_rank() -> None:
    values = [float(v) for v in range(1, 101)]
    assert (percentile(values, 50), percentile(values, 95), percentile([7.0], 95)) == (
        50.0,
        95.0,
        7.0,
    )


def test_the_profile_gives_each_stage_and_tokens_per_answer() -> None:
    report = profile(_answer("a", 900.0, [(100, 10), (200, 20)]) + _answer("b", 500.0, [(50, 5)]))

    assert report["answers"] == 2
    assert set(report["stages_ms"]) == {
        "answer",
        "model_turn",
        "search",
        "search.embed",
        "citations",
    }
    assert report["stages_ms"]["answer"] == {"count": 2, "p50": 500.0, "p95": 900.0, "mean": 700.0}
    assert report["stages_ms"]["model_turn"]["count"] == 3
    per_answer = report["per_answer"]
    assert (per_answer["input_tokens"]["p50"], per_answer["input_tokens"]["p95"]) == (50, 300)
    assert per_answer["output_tokens"]["mean"] == 18
    assert per_answer["model_turns"]["p95"] == 2


def test_a_dump_keeps_only_ids_timings_and_counts(tmp_path: Path) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer(__name__)
    with tracer.start_as_current_span(
        "chat m",
        attributes={
            semconv.GEN_AI_OPERATION_NAME: semconv.OPERATION_CHAT,
            semconv.GEN_AI_USAGE_INPUT_TOKENS: 3,
            "neuron.unlisted": _SECRET,
        },
    ):
        pass
    path = tmp_path / "spans.jsonl"

    dump(exporter.get_finished_spans(), path)

    text = path.read_text(encoding="utf-8")
    assert _SECRET not in text
    [rec] = [json.loads(line) for line in text.splitlines()]
    assert set(rec) == {"trace", "name", "ms", "attributes"}
    assert rec["attributes"] == {
        semconv.GEN_AI_OPERATION_NAME: semconv.OPERATION_CHAT,
        semconv.GEN_AI_USAGE_INPUT_TOKENS: 3,
    }


def test_the_command_prints_a_table_or_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "spans.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in _answer("a", 900.0, [(1, 2)])) + "\n")

    main([str(path)])
    assert "| search.embed | 1 | 20.0 | 20.0 | 20.0 |" in capsys.readouterr().out
    main([str(path), "--json"])
    assert json.loads(capsys.readouterr().out)["answers"] == 1
