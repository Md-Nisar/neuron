"""A tool's input-validation failure is a tool error the model can act on (#101)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import structlog.testing
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

from neuron_agent.api import main as api_main
from neuron_agent.api.main import app
from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import ToolExecutionError, ValidationAppError
from neuron_agent.models.factory import tool_failure_isolation_middleware
from neuron_agent.services.agent_service import AgentService

pytestmark = pytest.mark.anyio

_BAD_INPUT = "__import__('os').system('ls')"
_REFUSAL = "I cannot run that command."


class _Request:
    tool_call = {"name": "calculator", "args": {"expression": _BAD_INPUT}, "id": "call-1"}


def test_invalid_tool_input_does_not_abort_the_run(
    stream_replies: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    call = {"name": "calculator", "args": {"expression": _BAD_INPUT}, "id": "call-1"}
    model = stream_replies(AIMessage(content="", tool_calls=[call]), AIMessage(content=_REFUSAL))
    monkeypatch.setattr(api_main, "service", AgentService(Settings(env="test")))

    with structlog.testing.capture_logs() as logs:
        response = TestClient(app).post("/v1/agent/invoke", json={"message": "run it"})

    assert response.status_code == 200
    assert response.json()["answer"] == _REFUSAL
    assert response.json()["used_tools"] == []
    failed = [log for log in logs if log["event"] == "tool_call_failed"]
    assert [(log["tool_name"], log["error_code"]) for log in failed] == [
        ("calculator", "validation_error")
    ]
    assert _BAD_INPUT not in repr(logs)
    assert next(model.messages, None) is None


async def test_validation_failure_becomes_a_safe_error_message() -> None:
    middleware = tool_failure_isolation_middleware()

    async def handler(request: object) -> ToolMessage:
        raise ValidationAppError(f"invalid arithmetic expression: {_BAD_INPUT}")

    result = await middleware.awrap_tool_call(_Request(), handler)

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert result.tool_call_id == "call-1"
    assert result.name == "calculator"
    assert _BAD_INPUT not in str(result.content)


async def test_other_failures_still_raise() -> None:
    middleware = tool_failure_isolation_middleware()

    async def broken(request: object) -> ToolMessage:
        raise RuntimeError("boom")

    with pytest.raises(ToolExecutionError):
        await middleware.awrap_tool_call(_Request(), broken)


def test_tool_span_records_the_validation_error_code(
    stream_replies: Callable[..., Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    from opentelemetry.trace import StatusCode

    from neuron_agent.observability import semconv, telemetry

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "tracer", lambda: provider.get_tracer(__name__))
    call = {"name": "calculator", "args": {"expression": _BAD_INPUT}, "id": "call-1"}
    stream_replies(AIMessage(content="", tool_calls=[call]), AIMessage(content=_REFUSAL))
    monkeypatch.setattr(api_main, "service", AgentService(Settings(env="test")))

    response = TestClient(app).post("/v1/agent/invoke", json={"message": "run it"})

    assert response.status_code == 200
    [tool] = [s for s in exporter.get_finished_spans() if s.name == "execute_tool calculator"]
    assert tool.status.status_code is StatusCode.ERROR
    assert (tool.attributes or {})[semconv.ERROR_TYPE] == "validation_error"
    assert (tool.attributes or {})[semconv.NEURON_OUTCOME] == "error"
