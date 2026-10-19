"""A reply with no text and no tool call is retried a bounded number of times (#125)."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
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

# What a reasoning model returns after spending its whole output budget thinking.
_TRUNCATED = AIMessage(content="", response_metadata={"finish_reason": "length"})


def _answer(text: str) -> AIMessage:
    call = {
        "name": "AgentAnswer",
        "args": {"answer": text, "used_tools": [], "confidence": 0.9},
        "id": "answer-1",
    }
    return AIMessage(content="", tool_calls=[call])


def _post(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(api_main, "service", AgentService(Settings(env="test")))
    return TestClient(app).post("/v1/agent/invoke", json={"message": "hello"})


def test_a_truncated_reply_is_retried_and_the_run_answers(
    stream_replies: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    model = stream_replies(_TRUNCATED, _answer("Paris."))

    with structlog.testing.capture_logs() as logs:
        response = _post(monkeypatch)

    assert response.status_code == 200
    assert response.json()["answer"] == "Paris."
    assert [log["retry_attempt"] for log in logs if log["event"] == "model_empty_reply_retry"] == [
        1
    ]
    assert next(model.messages, None) is None


def test_retries_are_bounded_and_the_run_then_fails_as_before(
    stream_replies: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    model = stream_replies(_TRUNCATED, _TRUNCATED, _TRUNCATED, _answer("never reached"))

    with structlog.testing.capture_logs() as logs:
        response = _post(monkeypatch)

    assert response.status_code == 502
    failed = next(log for log in logs if log["event"] == "agent_execution_failed")
    assert failed["error_code"] == "structured_output_error"
    # Three model calls (the first and two retries); the fourth reply was never requested.
    assert next(model.messages).tool_calls[0]["args"]["answer"] == "never reached"


async def test_only_a_reply_without_text_or_tool_calls_is_retried() -> None:
    from neuron_agent.models.factory import empty_reply_retry_middleware

    middleware = empty_reply_retry_middleware()
    cases = {
        "text": AIMessage(content="plain text"),
        "tool call": AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "1"}]),
        "truncated tool call": AIMessage(
            content="",
            invalid_tool_calls=[
                {
                    "name": "t",
                    "args": '{"a": ',
                    "id": "1",
                    "error": "bad",
                    "type": "invalid_tool_call",
                }
            ],
        ),
    }
    for name, reply in cases.items():
        calls = 0

        async def handler(request: object, reply: AIMessage = reply) -> Any:
            nonlocal calls
            calls += 1
            return SimpleNamespace(result=[reply])

        await middleware.awrap_model_call(object(), handler)
        assert calls == 1, name


async def test_an_empty_reply_that_fails_to_parse_is_retried_too() -> None:
    """Under ProviderStrategy an empty reply raises inside the model call instead."""
    from langchain.agents.structured_output import StructuredOutputValidationError

    from neuron_agent.models.factory import empty_reply_retry_middleware

    middleware = empty_reply_retry_middleware()
    empty = AIMessage(content=[{"type": "reasoning", "reasoning": "thinking"}])
    outcomes: list[Any] = [
        StructuredOutputValidationError("AgentAnswer", ValueError("empty"), empty),
        SimpleNamespace(result=[_answer("Paris.")]),
    ]

    async def handler(request: object) -> Any:
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    response = await middleware.awrap_model_call(object(), handler)
    assert response.result[0].tool_calls[0]["args"]["answer"] == "Paris."
    assert outcomes == []


async def test_a_parse_error_on_a_reply_with_content_is_not_retried() -> None:
    from langchain.agents.structured_output import StructuredOutputValidationError

    from neuron_agent.models.factory import empty_reply_retry_middleware

    calls = 0
    bad = AIMessage(content="not json")

    async def handler(request: object) -> Any:
        nonlocal calls
        calls += 1
        raise StructuredOutputValidationError("AgentAnswer", ValueError("bad"), bad)

    with pytest.raises(StructuredOutputValidationError):
        await empty_reply_retry_middleware().awrap_model_call(object(), handler)
    assert calls == 1


async def test_parse_errors_on_empty_replies_stop_after_the_retry_limit() -> None:
    from langchain.agents.structured_output import StructuredOutputValidationError

    from neuron_agent.models.factory import empty_reply_retry_middleware

    calls = 0
    empty = AIMessage(content="")

    async def handler(request: object) -> Any:
        nonlocal calls
        calls += 1
        raise StructuredOutputValidationError("AgentAnswer", ValueError("empty"), empty)

    with pytest.raises(StructuredOutputValidationError):
        await empty_reply_retry_middleware().awrap_model_call(object(), handler)
    assert calls == 3  # the first call and two retries
