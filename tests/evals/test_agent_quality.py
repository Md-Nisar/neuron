from __future__ import annotations

from pathlib import Path

import pytest

from neuron_agent.evaluation import (
    MULTI_TURN_CASES,
    SECURITY_CASES,
    EvalResult,
    load_eval_cases,
    run_eval_suite,
    run_multi_turn_suite,
    run_security_suite,
)

# Live model calls: `integration` keeps these out of the default run; `make eval` selects them.
pytestmark = [pytest.mark.eval, pytest.mark.integration, pytest.mark.anyio]

_FIXTURE_PATH = Path("tests/fixtures/eval_cases.json")


async def test_agent_passes_every_eval_case(live_provider: str) -> None:
    results = await run_eval_suite(_FIXTURE_PATH)

    assert len(results) == len(load_eval_cases(_FIXTURE_PATH))
    failures = [result for result in results if not result.passed]
    assert not failures, _format_failures(failures)


async def test_agent_passes_every_multi_turn_eval_case(live_provider: str) -> None:
    results = await run_multi_turn_suite(MULTI_TURN_CASES)

    assert len(results) == len(load_eval_cases(MULTI_TURN_CASES))
    failures = [result for result in results if not result.passed]
    assert not failures, _format_failures(failures)


async def test_agent_passes_every_security_eval_case(live_provider: str) -> None:
    results = await run_security_suite(SECURITY_CASES)

    assert len(results) == len(load_eval_cases(SECURITY_CASES))
    failures = [result for result in results if not result.passed]
    assert not failures, _format_failures(failures)


def _format_failures(failures: list[EvalResult]) -> str:
    return "\n".join(f"{f.case_id} ({f.category}): {f.reasons}" for f in failures)
