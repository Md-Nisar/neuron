from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404 - runs this project's own CLI under test
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from langchain_core.messages import HumanMessage

from neuron_agent import evaluation
from neuron_agent.config.settings import Settings
from neuron_agent.evaluation import (
    MULTI_TURN_CASES,
    SINGLE_TURN_CASES,
    load_eval_cases,
    run_eval_suite,
    run_multi_turn_suite,
)
from neuron_agent.services.agent_service import AgentService

pytestmark = [pytest.mark.eval, pytest.mark.anyio]


def _human_turns(call: list[Any]) -> list[str]:
    return [str(m.content) for m in call if isinstance(m, HumanMessage)]


async def test_multi_turn_runner_plays_every_case_on_one_thread(echo_agent: Any) -> None:
    cases = load_eval_cases(MULTI_TURN_CASES)
    results = await run_multi_turn_suite(MULTI_TURN_CASES, AgentService(Settings(env="test")))

    assert [r.case_id for r in results] == [c["id"] for c in cases]
    calls = iter(echo_agent.calls)
    for case in cases:
        turns = [*cast("list[str]", case["setup"]), cast("str", case["input"])]
        final_call = [next(calls) for _ in turns][-1]
        # The final turn's model input carries the whole conversation, in order.
        assert _human_turns(final_call) == turns, case["id"]


async def test_single_turn_runner_uses_a_fresh_thread_per_case(echo_agent: Any) -> None:
    await run_eval_suite(SINGLE_TURN_CASES, AgentService(Settings(env="test")))
    assert all(len(_human_turns(call)) == 1 for call in echo_agent.calls)


async def test_multi_turn_runner_requires_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        evaluation, "get_settings", lambda: Settings(env="test", checkpointer="none")
    )
    with pytest.raises(RuntimeError, match="APP_CHECKPOINTER"):
        await run_multi_turn_suite(MULTI_TURN_CASES)


def test_cli_report_is_clean_json_with_multi_turn_section(tmp_path: Path) -> None:
    # A real process: stdout must hold only the report (logs go to stderr), so that
    # `neuron-eval > report.json` stays diffable JSON. Runs on the fake local model, from a
    # directory without the developer's `.env`, which could otherwise supply a live key.
    shutil.copytree(SINGLE_TURN_CASES.parent, tmp_path / SINGLE_TURN_CASES.parent)
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and arguments
        [sys.executable, "-c", "from neuron_agent.evaluation import main; main()"],
        capture_output=True,
        text=True,
        check=True,
        cwd=tmp_path,
        env={
            **{k: v for k, v in os.environ.items() if not k.endswith("OPENAI_API_KEY")},
            "APP_ENV": "test",
        },
        timeout=120,
    )
    report = json.loads(completed.stdout)
    assert report["total"] == len(load_eval_cases(SINGLE_TURN_CASES))
    assert report["multi_turn"]["total"] == len(load_eval_cases(MULTI_TURN_CASES))
    assert {"model", "passed", "results"} <= set(report)
