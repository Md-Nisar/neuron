"""Knowledge load helpers (RAG-09.06): fixture, ingestion report, baseline. No network."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from loadtest import knowledge
from loadtest.slo import request_percentiles

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge.parsing import TEXT, Limits, PlainTextParser, check_input

pytestmark = pytest.mark.anyio


async def test_the_fixture_is_plain_text_with_the_pages_the_worker_counts() -> None:
    data = knowledge.document(901, 3, pages=5)
    limits = Limits.from_settings(Settings(env="test"))
    assert check_input(data, TEXT, limits) == TEXT
    parsed = await PlainTextParser().parse(data, TEXT, limits)
    assert parsed.page_count == 5
    assert knowledge.document(901, 4, pages=5) != data  # no two documents repeat


def _doc(status: str, created: str, updated: str, pages: int | None = 8) -> dict[str, Any]:
    return {
        "status": status,
        "created_at": f"2026-11-13T10:{created}+00:00",
        "updated_at": f"2026-11-13T10:{updated}+00:00",
        "page_count": pages,
    }


def test_ingestion_counts_ready_pages_over_the_span_of_the_run() -> None:
    docs = [
        _doc("ready", "00:00", "00:10"),
        _doc("ready", "00:30", "01:00"),
        _doc("failed", "00:40", "00:41", None),
        _doc("embedding", "00:50", "00:50", None),
    ]
    report = knowledge.ingestion(docs)
    assert (report["ready"], report["failed"], report["unsettled"]) == (2, 1, 1)
    assert (report["pages"], report["span_seconds"]) == (16, 60.0)
    assert (report["pages_per_minute"], report["documents_per_minute"]) == (16.0, 2.0)
    assert report["document_seconds_p50"] == 30.0


def test_ingestion_without_a_ready_document_reports_no_rate() -> None:
    report = knowledge.ingestion([_doc("failed", "00:00", "00:01", None)])
    assert report["pages_per_minute"] == 0.0
    assert report["document_seconds_p95"] is None


def _entry(requests: int, failures: int, p50: float, p95: float) -> SimpleNamespace:
    return SimpleNamespace(
        num_requests=requests,
        num_failures=failures,
        get_response_time_percentile=lambda share: p50 if share == 0.5 else p95,
    )


def test_request_percentiles_are_recorded_per_name() -> None:
    stats = SimpleNamespace(entries={("search", "HTTP"): _entry(10, 1, 80.0, 150.0)})
    assert request_percentiles(stats) == {
        "search": {"requests": 10, "failures": 1, "p50_ms": 80.0, "p95_ms": 150.0}
    }


def _step(users: int, runs: int, run_p95: float, search_p95: float | None = None) -> str:
    requests = {"search": {"requests": 40, "failures": 0, "p50_ms": 70.0, "p95_ms": search_p95}}
    step = {"users": users, "seconds": 60.0, "runs": runs, "run_p95_ms": run_p95}
    return json.dumps({**step, "requests": requests if search_p95 else {}}) + "\n"


def test_the_baseline_records_search_ingestion_and_the_chat_p95_change(tmp_path: Path) -> None:
    (tmp_path / "knowledge.jsonl").write_text(_step(16, 0, 0.0, 120.0))
    (tmp_path / "mix.jsonl").write_text(_step(30, 300, 2000.0))
    (tmp_path / "chat_search.jsonl").write_text(_step(38, 290, 2500.0, 180.0))
    ingestion = knowledge.ingestion([_doc("ready", "00:00", "01:00")])
    (tmp_path / "knowledge.ingestion.json").write_text(json.dumps(ingestion))

    result = knowledge.baseline(tmp_path, image="neuron:ref", note="", host="test host")
    assert result["host"] == "test host"
    assert (result["search"]["p50_ms"], result["search"]["p95_ms"]) == (70.0, 120.0)
    assert result["ingestion"]["pages_per_minute"] == 8.0
    chat = result["chat_with_search"]
    assert (chat["chat_users"], chat["search_users"]) == (30, 8)
    assert chat["chat_run_p95_change"] == 0.25
    assert chat["search_p95_ms_beside_chat"] == 180.0
