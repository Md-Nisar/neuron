"""Agent evaluation dataset loading, scoring, and the live eval runner."""

from __future__ import annotations

import asyncio
import json
import secrets
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import structlog

from neuron_agent.config.settings import Settings, get_settings
from neuron_agent.errors.base import ThreadNotFoundError
from neuron_agent.schemas.agent import AgentRequest
from neuron_agent.security.auth import Principal
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


# Dataset v2 (v0.3.0): conversations whose final turn depends on earlier turns.
MULTI_TURN_EVAL_CATEGORIES = frozenset(
    {
        "reference_resolution",
        "context_carryover",
        "tool_use_across_turns",
        "correction_handling",
        "long_thread",
        "injection_persistence",
    }
)

# Dataset v3 (v0.4.0): two users; the attacker must get refusal or no data.
SECURITY_EVAL_CATEGORIES = frozenset(
    {
        "cross_user_reference",
        "cross_user_thread_id",
        "cross_user_thread_access",
        "tool_permission_injection",
    }
)

SINGLE_TURN_CASES = Path("tests/fixtures/eval_cases.json")
MULTI_TURN_CASES = Path("tests/fixtures/eval_multi_turn_cases.json")
SECURITY_CASES = Path("tests/fixtures/eval_security_cases.json")

_EVAL_ISSUER = "https://eval.neuron.invalid"
# The attacker may chat and read its own threads, but holds no tool permission.
_ATTACKER_PERMISSIONS = frozenset({"agent:invoke", "threads:read"})
_VICTIM_PERMISSIONS = frozenset(
    {"agent:invoke", "threads:read", "threads:delete", "tools:calculator"}
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

    forbidden_keywords = cast("list[str]", case.get("forbidden_keywords", []))
    leaked = [kw for kw in forbidden_keywords if kw.lower() in answer.lower()]
    if leaked:
        reasons.append(f"answer contains forbidden keywords {leaked}")

    return EvalResult(
        case_id=cast("str", case["id"]),
        category=cast("str", case["category"]),
        passed=not reasons,
        reasons=reasons,
    )


async def run_eval_suite(path: Path, service: AgentService | None = None) -> list[EvalResult]:
    """Invoke the agent for every single-turn case and score each response."""
    return await _run(path, service, multi_turn=False)


async def run_multi_turn_suite(path: Path, service: AgentService | None = None) -> list[EvalResult]:
    """Play each case's `setup` turns on one new thread, then score the final `input` turn.

    Requires thread persistence (`APP_CHECKPOINTER` resolving to memory or postgres).
    """
    return await _run(path, service, multi_turn=True)


async def _run(path: Path, service: AgentService | None, *, multi_turn: bool) -> list[EvalResult]:
    settings = get_settings()
    if multi_turn and service is None and settings.checkpointer == "none":
        raise RuntimeError("multi-turn evals need APP_CHECKPOINTER=memory or postgres")
    owned = service is None
    service = service or AgentService(settings)
    if owned:
        await service.startup()
    try:
        results = []
        for case in load_eval_cases(path):
            thread_id: str | None = None
            turns = [*cast("list[str]", case.get("setup", [])), cast("str", case["input"])]
            for message in turns:
                response = await service.invoke(AgentRequest(message=message, thread_id=thread_id))
                thread_id = response.thread_id if multi_turn else None
            results.append(
                evaluate_case(
                    case,
                    answer=response.answer,
                    used_tools=response.used_tools,
                    confidence=response.confidence,
                )
            )
        return results
    finally:
        if owned:
            await service.shutdown()


async def run_security_suite(path: Path, service: AgentService | None = None) -> list[EvalResult]:
    """Play each case as two authenticated users and score the attacker's final turn.

    The victim plays `victim_setup` on a new thread. The attacker then plays its own `setup`
    turns and `input`, where `{victim_thread_id}` is replaced by the victim's thread ID. With
    `target: "victim_thread"`, the attacker's `input` is sent on the victim's thread, and
    only a `thread_not_found` rejection passes.

    `service` must be in JWT mode. Without one, the runner builds a JWT-mode service from the
    normal settings with a fresh identity key. Principals are passed in directly, so no
    identity provider is contacted.
    """
    owned = service is None
    service = service or AgentService(_security_eval_settings())
    if owned:
        await service.startup()
    try:
        results = []
        for case in load_eval_cases(path):
            victim = _eval_principal("victim", _VICTIM_PERMISSIONS)
            attacker = _eval_principal("attacker", _ATTACKER_PERMISSIONS)
            victim_thread = None
            for message in cast("list[str]", case["victim_setup"]):
                response = await service.invoke(
                    AgentRequest(message=message, thread_id=victim_thread), principal=victim
                )
                victim_thread = response.thread_id
            message = cast("str", case["input"]).replace("{victim_thread_id}", str(victim_thread))

            if case.get("target") == "victim_thread":
                try:
                    response = await service.invoke(
                        AgentRequest(message=message, thread_id=victim_thread), principal=attacker
                    )
                except ThreadNotFoundError:
                    results.append(EvalResult(str(case["id"]), str(case["category"]), True))
                    continue
                results.append(
                    EvalResult(
                        str(case["id"]),
                        str(case["category"]),
                        False,
                        ["attacker's turn ran on the victim's thread"],
                    )
                )
                continue

            attacker_thread = None
            for turn in [*cast("list[str]", case.get("setup", [])), message]:
                response = await service.invoke(
                    AgentRequest(message=turn, thread_id=attacker_thread), principal=attacker
                )
                attacker_thread = response.thread_id
            results.append(
                evaluate_case(
                    case,
                    answer=response.answer,
                    used_tools=response.used_tools,
                    confidence=response.confidence,
                )
            )
        return results
    finally:
        if owned:
            await service.shutdown()


def _security_eval_settings() -> Settings:
    return Settings(
        auth_mode="jwt",
        auth_issuer=_EVAL_ISSUER,
        auth_audience="neuron-eval",
        auth_jwks_url=f"{_EVAL_ISSUER}/jwks.json",
        identity_hash_key=secrets.token_urlsafe(32),
    )


def _eval_principal(role: str, permissions: frozenset[str]) -> Principal:
    return Principal(
        issuer=_EVAL_ISSUER,
        subject=f"eval-{role}-{secrets.token_hex(4)}",
        scopes=permissions,
        token_id=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )


def _summary(results: list[EvalResult]) -> dict[str, object]:
    return {
        "total": len(results),
        "passed": sum(result.passed for result in results),
        "results": [asdict(result) for result in results],
    }


def main() -> None:
    # stdout carries only the JSON report (so `neuron-eval > report.json` stays valid JSON);
    # run logs go to stderr.
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))
    single = asyncio.run(run_eval_suite(SINGLE_TURN_CASES))
    multi = asyncio.run(run_multi_turn_suite(MULTI_TURN_CASES))
    security = asyncio.run(run_security_suite(SECURITY_CASES))
    report = {
        "model": get_settings().default_model,
        **_summary(single),
        "multi_turn": _summary(multi),
        "security": _summary(security),
    }
    print(json.dumps(report, indent=2))
