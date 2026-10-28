"""An invalid `AgentAnswer` is retried at most twice (#236, ADR 0009 decision 3)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import structlog.testing
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from neuron_agent.api import main as api_main
from neuron_agent.api.main import app
from neuron_agent.config.settings import Settings
from neuron_agent.services.agent_service import AgentService

pytestmark = pytest.mark.anyio

_USAGE = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}


def _answer(text: str, confidence: float, call_id: str) -> AIMessage:
    call = {
        "name": "AgentAnswer",
        "args": {"answer": text, "used_tools": [], "confidence": confidence},
        "id": call_id,
    }
    return AIMessage(content="", tool_calls=[call], usage_metadata=_USAGE)  # type: ignore[arg-type]


def _invalid(n: int) -> AIMessage:
    # `confidence` must be within 0 and 1.
    return _answer("bad", 7.0, f"bad-{n}")


def _post(monkeypatch: pytest.MonkeyPatch, **settings: Any) -> Any:
    monkeypatch.setattr(api_main, "service", AgentService(Settings(env="test", **settings)))
    return TestClient(app).post("/v1/agent/invoke", json={"message": "hello"})


def test_a_second_attempt_that_is_valid_answers(
    stream_replies: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    stream_replies(_invalid(1), _answer("Paris.", 0.9, "ok"))

    response = _post(monkeypatch)

    assert response.status_code == 200
    assert response.json()["answer"] == "Paris."


def test_the_run_fails_after_two_retries_not_at_the_iteration_limit(
    stream_replies: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    model = stream_replies(*(_invalid(n) for n in range(8)), _answer("never reached", 1.0, "x"))

    with structlog.testing.capture_logs() as logs:
        response = _post(monkeypatch)

    failed = next(log for log in logs if log["event"] == "agent_execution_failed")
    assert failed["error_code"] == "structured_output_error"
    assert response.status_code == 502
    # The first attempt and two retries were requested; the rest were not.
    assert len(list(model.messages)) == 8 + 1 - 3


def test_every_attempt_is_counted_in_the_runs_token_usage(
    stream_replies: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    stream_replies(*(_invalid(n) for n in range(8)))

    with structlog.testing.capture_logs() as logs:
        _post(monkeypatch)

    [usage] = [log for log in logs if log["event"] == "model_token_usage"]
    assert usage["provider_tokens"] == 3 * _USAGE["total_tokens"]


def test_the_middleware_sits_inside_the_empty_reply_retry_and_outside_tracing() -> None:
    from neuron_agent.models.factory import agent_middleware

    kinds = [type(m).__name__ for m in agent_middleware(Settings(env="test"))]
    assert kinds.index("_EmptyReplyRetryMiddleware") < kinds.index(
        "_StructuredOutputRetryMiddleware"
    )
    assert kinds.index("_StructuredOutputRetryMiddleware") < kinds.index("_TracingMiddleware")


async def test_a_provider_schema_that_fails_to_parse_is_retried_twice_and_charged() -> None:
    from types import SimpleNamespace

    from langchain.agents.structured_output import StructuredOutputValidationError

    from neuron_agent.models.factory import structured_output_retry_middleware
    from neuron_agent.security.authorization import AuthorizationContext, TokenUsageAccumulator

    usage = TokenUsageAccumulator()
    request = SimpleNamespace(
        messages=[],
        runtime=SimpleNamespace(context=AuthorizationContext(frozenset(), usage=usage)),
    )
    bad = AIMessage(content="not json", usage_metadata=_USAGE)  # type: ignore[arg-type]
    calls = 0

    async def handler(_: object) -> Any:
        nonlocal calls
        calls += 1
        raise StructuredOutputValidationError("AgentAnswer", ValueError("bad"), bad)

    with pytest.raises(StructuredOutputValidationError):
        await structured_output_retry_middleware().awrap_model_call(request, handler)

    assert calls == 3
    # The two retried attempts were charged here; the third raised to the caller.
    assert usage.total_tokens == 2 * _USAGE["total_tokens"]


async def test_an_empty_reply_is_left_to_the_empty_reply_retry() -> None:
    from types import SimpleNamespace

    from langchain.agents.structured_output import StructuredOutputValidationError

    from neuron_agent.models.factory import structured_output_retry_middleware

    calls = 0

    async def handler(_: object) -> Any:
        nonlocal calls
        calls += 1
        raise StructuredOutputValidationError("AgentAnswer", ValueError("x"), AIMessage(content=""))

    with pytest.raises(StructuredOutputValidationError):
        await structured_output_retry_middleware().awrap_model_call(
            SimpleNamespace(messages=[]), handler
        )
    assert calls == 1
