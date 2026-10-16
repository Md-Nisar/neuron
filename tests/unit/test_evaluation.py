from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # nosec B404 - runs this project's own CLI under test
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import structlog

from neuron_agent.config.settings import Settings
from neuron_agent.errors import base as errors_base
from neuron_agent.errors.base import AppError, ProviderTimeoutError
from neuron_agent.evaluation import (
    INFRASTRUCTURE_ERROR_CODES,
    EvalResult,
    TrialResult,
    _git_sha,
    _metrics,
    _suite_report,
    evaluate_case,
    main,
    percentile,
    run_eval_suite,
    run_security_suite,
    wilson_interval,
)
from neuron_agent.graphs import main_graph
from neuron_agent.schemas.agent import AgentAnswer, AgentRequest, AgentResponse
from neuron_agent.services.agent_service import AgentService

_BASE_CASE: dict[str, object] = {
    "id": "case-001",
    "category": "calculator_tool_selection",
    "expected_tools": ["calculator"],
    "expected_keywords": ["57"],
}


def test_evaluate_case_passes_when_response_matches_expectations() -> None:
    result = evaluate_case(
        _BASE_CASE, answer="The answer is 57.", used_tools=["calculator"], confidence=0.9
    )
    assert result.passed
    assert result.reasons == []


def test_evaluate_case_fails_on_tool_mismatch() -> None:
    result = evaluate_case(_BASE_CASE, answer="The answer is 57.", used_tools=[], confidence=0.9)
    assert not result.passed
    assert any("tools" in reason for reason in result.reasons)


def test_evaluate_case_fails_when_no_expected_keyword_present() -> None:
    result = evaluate_case(
        _BASE_CASE, answer="The answer is 58.", used_tools=["calculator"], confidence=0.9
    )
    assert not result.passed
    assert any("keyword" in reason for reason in result.reasons)


def test_evaluate_case_passes_when_no_keywords_are_required() -> None:
    case = {**_BASE_CASE, "expected_keywords": []}
    result = evaluate_case(
        case, answer="anything at all", used_tools=["calculator"], confidence=0.9
    )
    assert result.passed


def test_evaluate_case_fails_on_empty_answer() -> None:
    result = evaluate_case(_BASE_CASE, answer="   ", used_tools=["calculator"], confidence=0.9)
    assert not result.passed
    assert any("empty" in reason for reason in result.reasons)


def test_evaluate_case_fails_on_confidence_out_of_bounds() -> None:
    result = evaluate_case(
        _BASE_CASE, answer="The answer is 57.", used_tools=["calculator"], confidence=1.5
    )
    assert not result.passed
    assert any("confidence" in reason for reason in result.reasons)


def test_evaluate_case_fails_when_a_forbidden_keyword_leaks() -> None:
    case = {**_BASE_CASE, "forbidden_keywords": ["BLUEHERON", "4831"]}
    leaked = evaluate_case(
        case, answer="Their codename was blueheron. 57", used_tools=["calculator"], confidence=0.9
    )
    assert not leaked.passed
    assert any("forbidden" in reason and "BLUEHERON" in reason for reason in leaked.reasons)
    clean = evaluate_case(case, answer="57", used_tools=["calculator"], confidence=0.9)
    assert clean.passed


class _FlakyService:
    """Answers every message with "57" except those containing "boom", which time out."""

    async def invoke(
        self, request: AgentRequest, *, principal: Any = None, usage: Any = None
    ) -> AgentResponse:
        if "boom" in request.message:
            raise ProviderTimeoutError("model provider timed out")
        return AgentResponse(
            request_id="r", thread_id="t", answer="57", used_tools=[], confidence=0.9
        )


def _cases(tmp_path: Path, *messages: str, **extra: object) -> Path:
    path = tmp_path / "cases.json"
    cases = [
        {"id": f"case-{n}", "category": "c", "input": message, "expected_tools": []}
        | {"expected_keywords": ["57"], **extra}
        for n, message in enumerate(messages)
    ]
    path.write_text(json.dumps({"version": "9.9.9", "cases": cases}), encoding="utf-8")
    return path


@pytest.mark.anyio
async def test_eval_suite_scores_a_failed_run_and_keeps_going(tmp_path: Path) -> None:
    path = _cases(tmp_path, "first", "boom", "last")
    results = await run_eval_suite(path, _FlakyService())  # type: ignore[arg-type]

    assert [r.passed for r in results] == [True, False, True]
    assert results[1].reasons == ["run failed: provider_timeout_error"]


@pytest.mark.anyio
async def test_security_suite_scores_a_failed_run_and_keeps_going(tmp_path: Path) -> None:
    path = _cases(tmp_path, "boom", "fine", victim_setup=["hello"])
    results = await run_security_suite(path, _FlakyService())  # type: ignore[arg-type]

    assert [r.passed for r in results] == [False, True]


# ---- eval harness v2 (#94) ----

_SCHEMA = Path("tests/fixtures/eval_report.schema.json")


def _validate(report: object) -> None:
    jsonschema.Draft202012Validator(json.loads(_SCHEMA.read_text(encoding="utf-8"))).validate(
        report
    )


def test_wilson_interval_known_values_and_edges() -> None:
    low, high = wilson_interval(8, 10)  # type: ignore[misc]
    assert (round(low, 4), round(high, 4)) == (0.4902, 0.9433)
    low, high = wilson_interval(0, 10)  # type: ignore[misc]
    assert (low, round(high, 4)) == (0.0, 0.2775)
    low, high = wilson_interval(10, 10)  # type: ignore[misc]
    assert (round(low, 4), high) == (0.7225, 1.0)
    assert wilson_interval(0, 0) is None


def test_percentile_interpolates_and_handles_no_values() -> None:
    assert percentile([], 50) is None
    assert percentile([7.0], 95) == 7.0
    assert percentile([4.0, 1.0, 3.0, 2.0], 50) == 2.5
    assert percentile([1.0, 2.0, 3.0, 4.0, 5.0], 95) == pytest.approx(4.8)


def test_expected_number_is_graded_within_a_tolerance() -> None:
    case = {
        **_BASE_CASE,
        "expected_keywords": [],
        "expected_number": {"value": 57, "tolerance": 0.5},
    }

    def passed(answer: str) -> bool:
        return evaluate_case(case, answer=answer, used_tools=["calculator"], confidence=0.9).passed

    assert passed("19 * 3 = 57")
    assert passed("About 57.4, rounded")
    assert passed("That is 1,000 or 57")
    assert not passed("The answer is 58.")
    assert not passed("The answer is 157.")


def test_flags_pass_without_keywords_and_keywords_are_the_fallback() -> None:
    case = {
        **_BASE_CASE,
        "expected_tools": [],
        "expected_flags": ["refused", "clarification_needed"],
        "expected_keywords": ["cannot"],
    }
    assert evaluate_case(case, answer="No.", used_tools=[], confidence=0.5, refused=True).passed
    assert evaluate_case(
        case, answer="Which one?", used_tools=[], confidence=0.5, clarification_needed=True
    ).passed
    assert evaluate_case(case, answer="I cannot.", used_tools=[], confidence=0.5).passed
    result = evaluate_case(case, answer="Sure!", used_tools=[], confidence=0.5)
    assert not result.passed
    assert "flags" in result.reasons[0]


def test_unknown_flags_and_trajectory_modes_are_rejected() -> None:
    with pytest.raises(ValueError, match="expected_flags"):
        evaluate_case(
            {**_BASE_CASE, "expected_flags": ["shouted"]}, answer="x", used_tools=[], confidence=0
        )
    with pytest.raises(ValueError, match="trajectory"):
        evaluate_case(
            {**_BASE_CASE, "trajectory": "exact"}, answer="x", used_tools=[], confidence=0
        )


def test_trajectory_unordered_by_default_and_subset_on_request() -> None:
    both = {**_BASE_CASE, "expected_tools": ["calculator", "utc_now"], "expected_keywords": []}

    def passed(case: dict[str, object], used: list[str]) -> bool:
        return evaluate_case(case, answer="x", used_tools=used, confidence=0.5).passed

    assert passed(both, ["utc_now", "calculator"])  # order does not matter
    assert not passed(both, ["calculator"])  # unordered still needs every expected tool
    subset = {**both, "trajectory": "subset"}
    assert passed(subset, ["calculator"])  # fewer tools than expected is fine
    assert passed(subset, [])
    result = evaluate_case(
        {**subset, "expected_tools": ["utc_now"]},
        answer="x",
        used_tools=["calculator"],
        confidence=0.5,
    )
    assert not result.passed
    assert "outside" in result.reasons[0]


def test_a_tool_the_caller_lacks_permission_for_fails_every_case() -> None:
    result = evaluate_case(
        _BASE_CASE,
        answer="57",
        used_tools=["calculator"],
        confidence=0.9,
        permissions=frozenset({"agent:invoke"}),
    )
    assert not result.passed
    assert result.reasons == ["tool calculator ran without permission tools:calculator"]


@pytest.mark.parametrize("code", sorted(INFRASTRUCTURE_ERROR_CODES))
def test_infrastructure_codes_are_all_real_error_codes(code: str) -> None:
    codes = {
        cls.context.code
        for cls in vars(errors_base).values()
        if isinstance(cls, type) and issubclass(cls, AppError)
    }
    assert code in codes


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (errors_base.ProviderError("x"), "infrastructure_error"),
        (errors_base.ProviderQuotaError("x"), "infrastructure_error"),
        (errors_base.RateLimitError("x"), "infrastructure_error"),
        (errors_base.ProviderTimeoutError("x"), "infrastructure_error"),
        (errors_base.RunTimeoutError("x"), "infrastructure_error"),
        (errors_base.ConfigurationError("x"), "infrastructure_error"),
        (errors_base.StructuredOutputError("x"), "fail"),
        (errors_base.AgentExecutionError("x"), "fail"),
        (errors_base.ToolExecutionError("x"), "fail"),
    ],
)
@pytest.mark.anyio
async def test_run_failures_are_classified(error: AppError, outcome: str, tmp_path: Path) -> None:
    class Failing:
        async def invoke(self, request: AgentRequest, **_: Any) -> AgentResponse:
            raise error

    path = _cases(tmp_path, "hello")
    (result,) = await run_eval_suite(path, Failing(), trials=2)  # type: ignore[arg-type]

    assert [t.outcome for t in result.trials] == [outcome, outcome]
    assert result.trials[0].error_code == error.context.code
    assert not result.passed
    assert result.passes == 0


class _ScriptedService:
    """Answers "57" or "wrong" per message and call count; records tokens into `usage`."""

    def __init__(self, script: dict[str, list[str]]) -> None:
        self.script = script
        self.seen: dict[str, int] = {}

    async def invoke(
        self, request: AgentRequest, *, principal: Any = None, usage: Any = None
    ) -> AgentResponse:
        n = self.seen[request.message] = self.seen.get(request.message, 0) + 1
        step = self.script[request.message][n - 1]
        if usage is not None:
            usage.record(
                {"input_tokens": 10, "output_tokens": 5, "output_token_details": {"reasoning": 2}},
                "m",
            )
        if step == "timeout":
            raise ProviderTimeoutError("slow")
        return AgentResponse(
            request_id="r", thread_id="t", answer=step, used_tools=[], confidence=0.9
        )


@pytest.mark.anyio
async def test_repeated_trials_are_aggregated(tmp_path: Path) -> None:
    path = _cases(tmp_path, "always", "once", "flaky-infra", "never")
    service = _ScriptedService(
        {
            "always": ["57", "57", "57"],
            "once": ["57", "bad", "bad"],
            "flaky-infra": ["57", "timeout", "57"],
            "never": ["bad", "bad", "bad"],
        }
    )
    results = await run_eval_suite(path, service, trials=3)  # type: ignore[arg-type]

    assert [(r.passes, r.quality_failures, r.infrastructure_errors) for r in results] == [
        (3, 0, 0),
        (1, 2, 0),
        (2, 0, 1),
        (0, 3, 0),
    ]
    assert [r.passed for r in results] == [True, False, False, False]
    assert all(len(r.trials) == 3 for r in results)
    # Every trial sent one request, which recorded 15 provider tokens (2 reasoning).
    assert results[0].trials[0].tokens["input_tokens"] == 10
    assert results[0].trials[0].tokens["reasoning_tokens"] == 2
    assert results[2].trials[1].tokens["total_tokens"] == 15  # tokens spent before the failure

    metrics = _metrics(results)
    # 12 trials: 6 passes, 5 quality failures, 1 infrastructure error left out of the rate.
    assert (metrics["passes"], metrics["quality_failures"]) == (6, 5)
    assert metrics["infrastructure_errors"] == 1
    assert metrics["pass_rate"] == pytest.approx(6 / 11)
    assert metrics["wilson_95"] == pytest.approx(
        dict(zip(("low", "high"), wilson_interval(6, 11) or (), strict=True))
    )
    # pass^k: of the 3 conclusive cases only "always" passed every trial.
    assert metrics["pass_hat_k"] == pytest.approx(1 / 3)
    assert metrics["inconclusive_cases"] == 1

    suite = _suite_report(results, "9.9.9")
    assert suite["tokens"]["total_tokens"] == 12 * 15  # type: ignore[index]
    assert suite["latency_ms"]["p50"] is not None  # type: ignore[index]
    assert list(suite["categories"]) == ["c"]  # type: ignore[call-overload]


def test_a_suite_of_only_infrastructure_errors_has_no_rates() -> None:
    failed = EvalResult(
        "a",
        "c",
        False,
        ["run failed: provider_error"],
        [TrialResult("infrastructure_error", [], 5.0, {}, "provider_error")],
    )
    metrics = _metrics([failed])
    assert metrics["pass_rate"] is None
    assert metrics["wilson_95"] is None
    assert metrics["pass_hat_k"] is None
    assert metrics["infrastructure_errors"] == 1


@pytest.mark.anyio
async def test_security_suite_fails_a_tool_the_attacker_has_no_permission_for(
    tmp_path: Path,
) -> None:
    class UsesCalculator(_FlakyService):
        async def invoke(self, request: AgentRequest, **_: Any) -> AgentResponse:
            return AgentResponse(
                request_id="r",
                thread_id="t",
                answer="57",
                used_tools=["calculator"],
                confidence=0.9,
            )

    path = _cases(tmp_path, "hi", victim_setup=["secret"], expected_tools=["calculator"])
    (result,) = await run_security_suite(path, UsesCalculator())  # type: ignore[arg-type]
    assert result.reasons == ["tool calculator ran without permission tools:calculator"]


def test_git_sha_is_a_commit_or_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    assert re.fullmatch(r"[0-9a-f]{40}|unknown", _git_sha())
    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert _git_sha() == "unknown"


@pytest.fixture
def in_process_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep `main()` from replacing the test session's global structlog configuration."""
    monkeypatch.setattr(structlog, "configure", lambda **_: None)


def _run_cli(capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, Any]:
    main(list(argv))
    return json.loads(capsys.readouterr().out)  # type: ignore[no-any-return]


def test_cli_options_filter_repeat_and_write_the_report(
    in_process_cli: None, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    out = tmp_path / "report.json"
    report = _run_cli(
        capsys,
        "--trials", "2",
        "--suite", "security",
        "--category", "cross_user_thread_access",
        "--output", str(out),
    )  # fmt: skip

    _validate(report)
    assert json.loads(out.read_text(encoding="utf-8")) == report  # stdout stays JSON too
    assert report["trials"] == 2
    assert list(report["suites"]) == ["security"]
    security = report["suites"]["security"]
    assert list(security["categories"]) == ["cross_user_thread_access"]
    assert security["cases"] == 2
    assert all(c["trials"] == 2 and c["passes"] == 2 for c in security["results"])
    assert security["pass_hat_k"] == 1.0
    assert report["dataset_versions"] == {"security": security["dataset_version"]}


def test_cli_reports_each_selected_suite_and_validates(
    in_process_cli: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _run_cli(capsys, "--category", "direct_factual", "--category", "context_carryover")
    _validate(report)
    assert list(report["suites"]) == ["single_turn", "multi_turn"]
    assert report["suites"]["single_turn"]["cases"] == 2
    assert report["suites"]["multi_turn"]["cases"] == 3


def test_cli_rejects_bad_options(in_process_cli: None, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--trials", "0"])
    with pytest.raises(SystemExit):
        main(["--suite", "nope"])
    with pytest.raises(SystemExit, match="no cases match"):
        main(["--suite", "single_turn", "--category", "cross_user_reference"])


def test_python_dash_m_runs_the_cli(tmp_path: Path) -> None:
    shutil.copytree(Path("tests/fixtures"), tmp_path / "tests/fixtures")
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and arguments
        [sys.executable, "-m", "neuron_agent.evaluation", "--suite", "security", "--category",
         "cross_user_thread_access", "--max-requests-per-minute", "0"],
        capture_output=True,
        text=True,
        check=True,
        cwd=tmp_path,
        env={
            **{k: v for k, v in os.environ.items() if not k.endswith("OPENAI_API_KEY")},
            "APP_ENV": "test",
        },
        timeout=120,
    )  # fmt: skip
    report = json.loads(completed.stdout)
    _validate(report)
    assert report["suites"]["security"]["cases"] == 2


def test_report_schema_rejects_malformed_reports(
    in_process_cli: None, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _run_cli(capsys, "--suite", "security", "--category", "cross_user_thread_access")
    for broken in (
        {k: v for k, v in report.items() if k != "report_version"},
        {**report, "report_version": 2},
        {**report, "git_sha": "abc"},
        {**report, "suites": {"other": report["suites"]["security"]}},
    ):
        with pytest.raises(jsonschema.ValidationError):
            _validate(broken)


@pytest.mark.anyio
async def test_service_response_carries_the_answer_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    class FlaggingAgent:
        async def ainvoke(self, inputs: dict[str, Any], **_: Any) -> dict[str, Any]:
            return {
                "messages": inputs["messages"],
                "structured_response": AgentAnswer(
                    answer="Which file?", confidence=0.6, clarification_needed=True
                ),
            }

    monkeypatch.setattr(main_graph, "build_agent", lambda settings: FlaggingAgent())
    service = AgentService(Settings(env="test"))
    await service.startup()
    try:
        response = await service.invoke(AgentRequest(message="Fix it."))
    finally:
        await service.shutdown()
    assert (response.refused, response.clarification_needed) == (False, True)
