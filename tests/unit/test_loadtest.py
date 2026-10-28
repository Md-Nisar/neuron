"""Load-test helpers: the SSE parser, the SLO check and the step summary (ADR 0012). No network."""

from __future__ import annotations

from types import SimpleNamespace

from loadtest.slo import StepSummary, breaches, summarise_step
from loadtest.sse import Event, parse_events, summarise

_COMPLETED = """\
event: run_started
data: {"request_id": "r", "thread_id": "t-1", "run_id": "u"}

: ping

event: token
data: {"text": "a "}

event: token
data: {"text": "b"}

event: final
data: {"status": "completed", "thread_id": "t-1", "answer": "a b"}

event: done
data: {}

"""

_APPROVAL = """\
event: approval_required
data: {"status": "approval_required", "thread_id": "t-2", "approval": {"approval_id": "ap-1"}}

event: done
data: {}

"""

_ERROR = """\
event: token
data: {"text": "x"}

event: error
data: {"code": "run_timeout", "retryable": false}

event: done
data: {}

"""


def _run(stream: str, started: float = 0.0, finished: float = 6.0) -> object:
    ticks = iter([1.5, 2.0, 5.0, 5.5, 6.0, 6.0])
    return summarise(
        parse_events(stream.splitlines(keepends=True), lambda: next(ticks)), started, finished
    )


def test_parser_skips_comments_and_yields_every_event_in_order() -> None:
    events = list(parse_events(_COMPLETED.splitlines(), lambda: 0.0))
    assert [e.name for e in events] == ["run_started", "token", "token", "final", "done"]
    assert events[1].data == {"text": "a "}


def test_a_completed_run_reports_ttft_tokens_and_thread() -> None:
    result = _run(_COMPLETED)
    assert (result.outcome, result.error_code, result.tokens) == ("completed", None, 2)  # type: ignore[attr-defined]
    assert result.ttft_seconds == 2.0  # type: ignore[attr-defined]
    assert result.thread_id == "t-1"  # type: ignore[attr-defined]


def test_a_paused_run_carries_the_approval_id() -> None:
    result = _run(_APPROVAL)
    assert (result.outcome, result.approval_id, result.ttft_seconds) == (  # type: ignore[attr-defined]
        "approval_required",
        "ap-1",
        None,
    )


def test_an_error_event_names_its_code() -> None:
    result = _run(_ERROR)
    assert (result.outcome, result.error_code) == ("error", "run_timeout")  # type: ignore[attr-defined]


def test_a_stream_that_just_ends_is_incomplete() -> None:
    assert _run("event: token\ndata: {}\n\n").outcome == "incomplete"  # type: ignore[attr-defined]


def test_malformed_data_is_an_empty_event_not_a_crash() -> None:
    (event,) = parse_events(["event: token\n", "data: {not json\n", "\n"], lambda: 0.0)
    assert event == Event("token", {}, 0.0)


def test_a_step_inside_every_slo_has_no_breach() -> None:
    assert breaches(StepSummary(5, 600, 3000, 0, 1000.0, 7000.0)) == []


def test_each_slo_is_checked_at_its_edge() -> None:
    assert breaches(StepSummary(5, 600, 100, 0, 15_001.0, 1.0)) == ["ttft"]
    assert breaches(StepSummary(5, 600, 100, 0, 1.0, 30_001.0)) == ["run_duration"]
    assert breaches(StepSummary(5, 600, 200, 1, 1.0, 1.0)) == []  # exactly 0.5% is within
    assert breaches(StepSummary(5, 600, 199, 1, 1.0, 1.0)) == ["availability"]
    assert breaches(StepSummary(5, 600, 201, 1, 1.0, 1.0)) == []


def test_step_summary_counts_runs_and_ignores_rejections() -> None:
    def entry(requests: int, failures: int, p: float) -> SimpleNamespace:
        return SimpleNamespace(
            num_requests=requests, num_failures=failures, get_response_time_percentile=lambda _: p
        )

    stats = SimpleNamespace(
        entries={
            ("run:mix", "SSE"): entry(90, 2, 6500.0),
            ("ttft:mix", "SSE"): entry(90, 0, 900.0),
            ("rejected:mix", "SSE"): entry(10, 10, 5.0),
        }
    )
    step = summarise_step(stats, 10, 60.0)
    assert (step.runs, step.failures, step.ttft_p90_ms, step.run_p95_ms) == (90, 2, 900.0, 6500.0)
    assert step.runs_per_second == 1.5
