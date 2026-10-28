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


def _step(users: int, runs: int, breaches: list[str] | None = None) -> dict[str, object]:
    return {
        "users": users,
        "seconds": 100.0,
        "runs": runs,
        "failures": 0,
        "ttft_p90_ms": 1200.0,
        "run_p95_ms": 6500.0,
        "breaches": breaches or [],
        "errors": {"run:mix: http_503": 4} if breaches else {},
    }


def test_baseline_takes_the_best_step_inside_the_slos_and_the_next_failure() -> None:
    from loadtest.baseline import scenario_result

    result = scenario_result(
        [_step(10, 500), _step(20, 900), _step(30, 950, ["availability"]), _step(40, 600, ["ttft"])]
    )
    assert result["sustained_runs_per_second"] == 9.0
    assert result["knee_users"] == 20
    assert result["first_breach"] == {
        "users": 30,
        "breaches": ["availability"],
        "errors": {"run:mix: http_503": 4},
    }


def test_baseline_with_no_breach_reports_no_knee_reached() -> None:
    from loadtest.baseline import scenario_result

    result = scenario_result([_step(10, 500), _step(20, 900)])
    assert result["slo_broken"] is False
    assert result["first_breach"] is None


def _document(rate: float, host: str = "h", profile: str = "p") -> dict[str, object]:
    return {
        "host": host,
        "fake_model_profile": profile,
        "scenarios": {"mix": {"sustained_runs_per_second": rate}},
    }


def test_compare_reports_a_drop_of_more_than_ten_percent_only() -> None:
    from loadtest.baseline import compare

    assert compare(_document(10.0), _document(9.1)) == []
    assert compare(_document(10.0), _document(11.0)) == []
    (line,) = compare(_document(10.0), _document(8.9))
    assert line.startswith("mix: 10.0 -> 8.9")


def test_compare_refuses_a_different_host_or_profile() -> None:
    import pytest
    from loadtest.baseline import compare

    with pytest.raises(ValueError, match="host differs"):
        compare(_document(10.0), _document(10.0, host="other"))
    with pytest.raises(ValueError, match="fake_model_profile differs"):
        compare(_document(10.0), _document(10.0, profile="other"))
