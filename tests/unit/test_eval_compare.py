"""`neuron-eval compare` gates (ADR 0007 section 6) and the eval request throttle."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from tests.conftest import StreamingFakeModel

from neuron_agent import evaluation
from neuron_agent.config.settings import Settings
from neuron_agent.eval_compare import (
    EXIT_INCONCLUSIVE,
    EXIT_INVALID_INPUT,
    EXIT_PASS,
    EXIT_REGRESSION,
    compare_main,
)
from neuron_agent.evaluation import (
    EvalResult,
    RequestThrottle,
    TrialResult,
    _suite_report,
    throttled_model_calls,
)
from neuron_agent.schemas.agent import AgentRequest
from neuron_agent.security.authorization import TokenUsageAccumulator
from neuron_agent.services.agent_service import AgentService

pytestmark = pytest.mark.anyio

ZERO_TOKENS = asdict(TokenUsageAccumulator().totals())


def _trial(outcome: str) -> TrialResult:
    code = "rate_limit_error" if outcome == "infrastructure_error" else None
    return TrialResult(outcome, [] if outcome == "pass" else ["x"], 1.0, ZERO_TOKENS, code)


def _case(case_id: str, *outcomes: str, category: str = "direct_factual") -> EvalResult:
    trials = [_trial(o) for o in outcomes]
    return EvalResult(case_id, category, all(o == "pass" for o in outcomes), [], trials)


def _report(**suites: list[EvalResult]) -> dict[str, Any]:
    bodies = {name: _suite_report(results, "1.0.0") for name, results in suites.items()}
    return {
        "report_version": 1,
        "model": "nvidia:test",
        "git_sha": "unknown",
        "dataset_versions": dict.fromkeys(bodies, "1.0.0"),
        "trials": 3,
        "infrastructure_errors": sum(b["infrastructure_errors"] for b in bodies.values()),
        "suites": bodies,
    }


def _run(
    tmp_path: Path,
    baseline: dict[str, Any] | None,
    candidate: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, dict[str, Any]]:
    base_path, cand_path = tmp_path / "base.json", tmp_path / "cand.json"
    if baseline is not None:
        base_path.write_text(json.dumps(baseline), encoding="utf-8")
    cand_path.write_text(json.dumps(candidate), encoding="utf-8")
    code = compare_main([str(base_path), str(cand_path)])
    out = capsys.readouterr().out
    return code, json.loads(out) if out else {}


P3 = ("pass",) * 3
F3 = ("fail",) * 3


def test_case_that_flips_from_all_pass_to_all_fail_is_gated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _report(single_turn=[_case("a", *P3), _case("b", *P3)])
    cand = _report(single_turn=[_case("a", *F3), _case("b", *P3)])
    code, out = _run(tmp_path, base, cand, capsys)
    assert code == EXIT_REGRESSION
    assert [(f["case_id"], f["rule"]) for f in out["gate_failures"]] == [("a", "regression")]
    # Informational rates, intervals and deltas are reported alongside.
    suite = out["suites"]["single_turn"]
    assert suite["candidate"]["pass_rate"] == 0.5
    assert suite["delta"]["pass_rate"] == -0.5
    assert suite["candidate"]["wilson_95"]["low"] < 0.5 < suite["candidate"]["wilson_95"]["high"]
    assert suite["categories"]["direct_factual"]["delta"]["pass_rate"] == -0.5


def test_one_trial_wobble_is_not_gated(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = _report(multi_turn=[_case("a", *P3)])
    cand = _report(multi_turn=[_case("a", "pass", "fail", "fail")])
    code, out = _run(tmp_path, base, cand, capsys)
    assert code == EXIT_PASS
    assert out["status"] == "pass"
    assert out["gate_failures"] == []


def test_failing_case_that_was_not_perfect_in_baseline_is_not_gated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _report(single_turn=[_case("a", "pass", "pass", "fail")])
    cand = _report(single_turn=[_case("a", *F3)])
    assert _run(tmp_path, base, cand, capsys)[0] == EXIT_PASS


def test_any_security_trial_failure_is_gated_even_without_a_baseline_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    category = "cross_user_reference"
    base = _report(security=[_case("s", *P3, category=category)])
    cand = _report(security=[_case("s", "pass", "fail", "pass", category=category)])
    code, out = _run(tmp_path, base, cand, capsys)
    assert code == EXIT_REGRESSION
    assert out["gate_failures"][0]["rule"] == "security"


def test_infrastructure_only_failure_is_inconclusive_not_gated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    infra = ("infrastructure_error",) * 3
    base = _report(single_turn=[_case("a", *P3)], security=[_case("s", *P3)])
    cand = _report(single_turn=[_case("a", *infra)], security=[_case("s", "pass", *infra[:2])])
    code, out = _run(tmp_path, base, cand, capsys)
    assert code == EXIT_INCONCLUSIVE
    assert out["status"] == "inconclusive"
    assert out["gate_failures"] == []
    assert {e["case_id"] for e in out["infrastructure_errors"]} == {"a", "s"}
    assert out["infrastructure_errors"][0]["error_codes"] == ["rate_limit_error"]


def test_real_failure_outranks_infrastructure_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _report(single_turn=[_case("a", *P3), _case("b", *P3)])
    cand = _report(single_turn=[_case("a", *F3), _case("b", "infrastructure_error")])
    assert _run(tmp_path, base, cand, capsys)[0] == EXIT_REGRESSION


def test_cases_missing_on_either_side_are_reported_not_gated(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = _report(single_turn=[_case("old", *P3)])
    cand = _report(single_turn=[_case("new", *F3)])
    code, out = _run(tmp_path, base, cand, capsys)
    assert code == EXIT_PASS
    assert out["cases_only_in_baseline"] == ["single_turn/old"]
    assert out["cases_only_in_candidate"] == ["single_turn/new"]


def test_missing_baseline_applies_only_the_security_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = _run(tmp_path, None, _report(single_turn=[_case("a", *F3)]), capsys)
    assert code == EXIT_PASS
    assert out["baseline_missing"] is True
    assert out["gate_failures"] == []

    cand = _report(security=[_case("s", "pass", "pass", "fail", category="cross_user_reference")])
    code, out = _run(tmp_path, None, cand, capsys)
    assert code == EXIT_REGRESSION
    assert [f["rule"] for f in out["gate_failures"]] == ["security"]


def test_invalid_reports_are_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = _report(single_turn=[_case("a", *P3)])
    bad = {**good, "report_version": 2}
    code, _ = _run(tmp_path, good, bad, capsys)  # type: ignore[arg-type]
    assert code == EXIT_INVALID_INPUT


async def test_throttle_waits_for_the_window_to_free_a_slot() -> None:
    now = 0.0
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    throttle = RequestThrottle(2, 60.0, clock=lambda: now, sleep=sleep)
    for _ in range(2):
        await throttle.acquire()
    assert sleeps == []
    now = 10.0
    await throttle.acquire()  # third call: waits until the first leaves the window at t=60
    assert sleeps == [50.0]
    assert throttle.acquired == 3


async def test_throttle_counts_every_model_call_of_a_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from neuron_agent.models import factory

    call = {"name": "calculator", "args": {"expression": "2+2"}, "id": "c1"}
    model = StreamingFakeModel(
        messages=iter([AIMessage(content="", tool_calls=[call]), AIMessage(content="4")])
    )
    monkeypatch.setattr(factory, "create_chat_model", lambda settings: model)
    throttle = RequestThrottle(10)
    original = factory.provider_retry_middleware
    with throttled_model_calls(throttle):
        service = AgentService(Settings(env="test", checkpointer="memory"))
        await service.invoke(AgentRequest(message="what is 2+2?"))
    # A tool call then a final answer is two model calls for one case.
    assert throttle.acquired == 2
    assert factory.provider_retry_middleware is original
    assert evaluation.DEFAULT_MAX_REQUESTS_PER_MINUTE < 40


def test_nightly_workflow_is_least_privilege_and_bounded() -> None:
    import yaml

    workflow = yaml.safe_load(Path(".github/workflows/nightly-eval.yml").read_text("utf-8"))
    triggers = workflow[True]  # YAML 1.1 reads the key `on` as a boolean
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert len(triggers["schedule"]) == 1  # one scheduled run a night (EVALUATION.md)
    assert workflow["permissions"] == {"contents": "read"}
    job = workflow["jobs"]["live-eval"]
    assert 60 < job["timeout-minutes"] <= 90
    assert workflow["concurrency"]["cancel-in-progress"] is False
    # The secret is only ever mapped through `env:`, never interpolated into a script.
    for step in job["steps"]:
        assert "secrets." not in step.get("run", "")
