from __future__ import annotations

import os
from pathlib import Path

import pytest

from neuron_agent.evaluation import EvalResult, load_eval_cases, run_eval_suite

pytestmark = [pytest.mark.eval, pytest.mark.anyio]

_FIXTURE_PATH = Path("tests/fixtures/eval_cases.json")


@pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY is not configured")
async def test_agent_passes_every_eval_case() -> None:
    results = await run_eval_suite(_FIXTURE_PATH)

    assert len(results) == len(load_eval_cases(_FIXTURE_PATH))
    failures = [result for result in results if not result.passed]
    assert not failures, _format_failures(failures)


def _format_failures(failures: list[EvalResult]) -> str:
    return "\n".join(f"{f.case_id} ({f.category}): {f.reasons}" for f in failures)
