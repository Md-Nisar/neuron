"""Agent evaluation dataset loading, scoring, and the live eval runner."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import cast

from neuron_agent.config.settings import get_settings
from neuron_agent.schemas.agent import AgentRequest
from neuron_agent.services.agent_service import AgentService

EVAL_CATEGORIES = frozenset(
    {
        "direct_factual",
        "calculator_tool_selection",
        "utc_tool_selection",
        "unnecessary_tool_avoidance",
        "structured_output",
        "ambiguous_request",
        "adversarial_tool_abuse",
        "concise_response",
    }
)


def load_eval_cases(path: Path) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", json.loads(path.read_text(encoding="utf-8")))


@dataclass
class EvalResult:
    """Outcome of scoring one eval case against an actual agent response."""

    case_id: str
    category: str
    passed: bool
    reasons: list[str] = field(default_factory=list)


def evaluate_case(
    case: dict[str, object], *, answer: str, used_tools: list[str], confidence: float
) -> EvalResult:
    """Score one eval case's structured output, tool selection, and content."""
    reasons: list[str] = []

    if not answer.strip():
        reasons.append("answer must not be empty")
    if not 0.0 <= confidence <= 1.0:
        reasons.append(f"confidence {confidence} out of bounds [0, 1]")

    expected_tools = cast("list[str]", case["expected_tools"])
    if set(used_tools) != set(expected_tools):
        reasons.append(f"expected tools {expected_tools}, got {used_tools}")

    expected_keywords = cast("list[str]", case["expected_keywords"])
    if expected_keywords and not any(kw.lower() in answer.lower() for kw in expected_keywords):
        reasons.append(f"answer missing all expected keywords {expected_keywords}")

    return EvalResult(
        case_id=cast("str", case["id"]),
        category=cast("str", case["category"]),
        passed=not reasons,
        reasons=reasons,
    )


async def run_eval_suite(path: Path) -> list[EvalResult]:
    """Invoke the live agent for every case and score each response."""
    settings = get_settings()
    service = AgentService(settings)
    results = []
    for case in load_eval_cases(path):
        response = await service.invoke(AgentRequest(message=cast("str", case["input"])))
        results.append(
            evaluate_case(
                case,
                answer=response.answer,
                used_tools=response.used_tools,
                confidence=response.confidence,
            )
        )
    return results


def main() -> None:
    path = Path("tests/fixtures/eval_cases.json")
    results = asyncio.run(run_eval_suite(path))
    report = {
        "model": get_settings().default_model,
        "total": len(results),
        "passed": sum(result.passed for result in results),
        "results": [asdict(result) for result in results],
    }
    print(json.dumps(report, indent=2))
