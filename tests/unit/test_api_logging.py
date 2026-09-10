from __future__ import annotations

import pytest
import structlog

from neuron_agent.api import main as api_main
from neuron_agent.errors.base import ValidationAppError
from neuron_agent.schemas.agent import AgentRequest, AgentResponse

pytestmark = pytest.mark.anyio


async def test_invoke_agent_logs_duration_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fast_invoke(self: object, request: object) -> AgentResponse:
        return AgentResponse(
            request_id="request-1", thread_id="thread-1", answer="ok", used_tools=[], confidence=1.0
        )

    monkeypatch.setattr(api_main.AgentService, "invoke", fast_invoke)

    with structlog.testing.capture_logs() as captured:
        await api_main.invoke_agent(AgentRequest(message="hi"))

    completed = next(entry for entry in captured if entry["event"] == "agent_request_completed")
    assert isinstance(completed["duration_ms"], float)


async def test_invoke_agent_logs_error_type_on_app_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def raise_error(self: object, request: object) -> None:
        raise ValidationAppError("bad input")

    monkeypatch.setattr(api_main.AgentService, "invoke", raise_error)

    with structlog.testing.capture_logs() as captured:
        with pytest.raises(api_main.HTTPException):
            await api_main.invoke_agent(AgentRequest(message="hi"))

    failed = next(entry for entry in captured if entry["event"] == "agent_request_failed")
    assert failed["error_type"] == "ValidationAppError"
    assert isinstance(failed["duration_ms"], float)


async def test_invoke_agent_logs_error_type_on_unexpected_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def raise_error(self: object, request: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(api_main.AgentService, "invoke", raise_error)

    with structlog.testing.capture_logs() as captured:
        with pytest.raises(api_main.HTTPException):
            await api_main.invoke_agent(AgentRequest(message="hi"))

    failed = next(entry for entry in captured if entry["event"] == "agent_request_unexpected_error")
    assert failed["error_type"] == "RuntimeError"
    assert isinstance(failed["duration_ms"], float)
