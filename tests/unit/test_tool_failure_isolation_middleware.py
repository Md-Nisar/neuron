from __future__ import annotations

import pytest
import structlog
from langchain_core.messages import ToolMessage

from neuron_agent.errors.base import ToolExecutionError, ValidationAppError
from neuron_agent.models.factory import tool_failure_isolation_middleware

pytestmark = pytest.mark.anyio


class _FakeRequest:
    def __init__(self, name: str) -> None:
        self.tool_call = {"name": name, "args": {}, "id": "call-1"}


async def test_tool_failure_isolation_middleware_allows_success() -> None:
    middleware = tool_failure_isolation_middleware()

    async def ok_handler(request: object) -> ToolMessage:
        return ToolMessage(content="ok", tool_call_id="call-1")

    result = await middleware.awrap_tool_call(_FakeRequest("calculator"), ok_handler)
    assert result.content == "ok"


async def test_tool_failure_isolation_middleware_passes_through_app_errors() -> None:
    middleware = tool_failure_isolation_middleware()

    async def invalid_input_handler(request: object) -> ToolMessage:
        raise ValidationAppError("invalid arithmetic expression")

    with pytest.raises(ValidationAppError):
        await middleware.awrap_tool_call(_FakeRequest("calculator"), invalid_input_handler)


async def test_tool_failure_isolation_middleware_wraps_unexpected_exceptions() -> None:
    middleware = tool_failure_isolation_middleware()

    async def broken_handler(request: object) -> ToolMessage:
        raise RuntimeError("boom")

    with pytest.raises(ToolExecutionError):
        await middleware.awrap_tool_call(_FakeRequest("calculator"), broken_handler)


async def test_tool_failure_isolation_middleware_logs_error_type_for_app_errors() -> None:
    middleware = tool_failure_isolation_middleware()

    async def invalid_input_handler(request: object) -> ToolMessage:
        raise ValidationAppError("invalid arithmetic expression")

    with structlog.testing.capture_logs() as captured:
        with pytest.raises(ValidationAppError):
            await middleware.awrap_tool_call(_FakeRequest("calculator"), invalid_input_handler)

    failure_events = [entry for entry in captured if entry["event"] == "tool_call_failed"]
    assert failure_events == [
        {
            "event": "tool_call_failed",
            "log_level": "warning",
            "tool_name": "calculator",
            "error_code": "validation_error",
            "error_type": "ValidationAppError",
            "duration_ms": failure_events[0]["duration_ms"],
        }
    ]
