from __future__ import annotations

import asyncio
from typing import Any

import psycopg
import pytest
import structlog.testing
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from neuron_agent.api import main as api_main
from neuron_agent.api.main import app
from neuron_agent.config.settings import Settings
from neuron_agent.graphs import main_graph
from neuron_agent.persistence import checkpointer as checkpointer_module
from neuron_agent.persistence.checkpointer import instrument_checkpointer
from neuron_agent.schemas.agent import AgentAnswer, AgentRequest
from neuron_agent.services.agent_service import AgentService

pytestmark = pytest.mark.anyio

_PRIVATE_PROMPT = "my-private-prompt"


def _logs_named(logs: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [log for log in logs if log["event"] == name]


async def _stream(service: AgentService, **request: Any) -> list[Any]:
    run = await service.prepare(AgentRequest(**request), streaming=True)
    return [event async for event in service.stream(run)]


async def test_completed_stream_logs_lifecycle_with_correlation_and_ttft(
    stream_replies: Any,
) -> None:
    stream_replies(AIMessage(content="streamed reply text"))
    service = AgentService(Settings(env="test"))
    with structlog.testing.capture_logs() as logs:
        events = await _stream(service, message=_PRIVATE_PROMPT)

    started = _logs_named(logs, "stream_started")
    completed = _logs_named(logs, "stream_completed")
    assert len(started) == len(completed) == 1
    ids = events[0].data
    for log in (started[0], completed[0]):
        assert log["request_id"] == ids["request_id"]
        assert log["thread_id"] == ids["thread_id"]
        assert log["run_id"] == ids["run_id"]
    summary = completed[0]
    assert summary["termination"] == "completed"
    assert summary["error_code"] is None
    assert summary["tokens_streamed"] == sum(e.event == "token" for e in events) > 0
    assert summary["events_streamed"] == len(events)
    assert 0 <= summary["ttft_ms"] <= summary["duration_ms"]
    # Neither the prompt nor any streamed text is logged.
    assert _PRIVATE_PROMPT not in repr(logs)
    assert "streamed reply" not in repr(logs)


class _FailingAgent:
    def __init__(self, error: BaseException | None = None, delay: float = 0) -> None:
        self.error = error
        self.delay = delay
        self.started = asyncio.Event()

    async def ainvoke(self, inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
        self.started.set()
        await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return {"structured_response": AgentAnswer(answer="ok", used_tools=[], confidence=1.0)}


@pytest.mark.parametrize(
    ("agent", "settings", "termination", "error_code"),
    [
        (_FailingAgent(RuntimeError("boom")), {}, "error", "internal_server_error"),
        (_FailingAgent(delay=5), {"run_timeout_seconds": 1}, "timeout", "run_timeout"),
    ],
    ids=["error", "timeout"],
)
async def test_failed_streams_log_termination_reason(
    monkeypatch: pytest.MonkeyPatch,
    agent: _FailingAgent,
    settings: dict[str, Any],
    termination: str,
    error_code: str,
) -> None:
    monkeypatch.setattr(main_graph, "build_agent", lambda s: agent)
    service = AgentService(Settings(env="test", **settings))
    with structlog.testing.capture_logs() as logs:
        await _stream(service, message="hi")
    (summary,) = _logs_named(logs, "stream_completed")
    assert summary["termination"] == termination
    assert summary["error_code"] == error_code
    assert summary["log_level"] == "warning"


async def test_shutdown_and_disconnect_log_termination_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _FailingAgent(delay=5)
    monkeypatch.setattr(main_graph, "build_agent", lambda s: agent)
    service = AgentService(Settings(env="test"))

    stop = asyncio.Event()
    run = await service.prepare(AgentRequest(message="hi"), streaming=True)
    with structlog.testing.capture_logs() as logs:
        async for event in service.stream(run, stop=stop):
            if event.event == "run_started":
                await agent.started.wait()
                stop.set()
    (summary,) = _logs_named(logs, "stream_completed")
    assert summary["termination"] == "shutdown"
    assert summary["error_code"] == "service_shutting_down"

    agent.started.clear()
    run = await service.prepare(AgentRequest(message="hi"), streaming=True)
    stream = service.stream(run)
    with structlog.testing.capture_logs() as logs:
        await anext(stream)
        await stream.aclose()  # the client went away before `done`
    (cancelled,) = _logs_named(logs, "stream_cancelled")
    assert cancelled["termination"] == "client_disconnect"
    assert cancelled["run_id"] == run.run_id


def test_rejected_stream_logs_termination(monkeypatch: pytest.MonkeyPatch, echo_agent: Any) -> None:
    service = AgentService(Settings(env="test", openai_api_key=None))
    monkeypatch.setattr(api_main, "service", service)
    client = TestClient(app)
    thread_id = client.post("/v1/agent/invoke", json={"message": "hi"}).json()["thread_id"]
    service._active_threads.add(thread_id)
    with structlog.testing.capture_logs() as logs:
        response = client.post("/v1/agent/stream", json={"message": "hi", "thread_id": thread_id})
    assert response.status_code == 409
    (rejected,) = _logs_named(logs, "stream_rejected")
    assert rejected["termination"] == "thread_busy"


@pytest.mark.usefixtures("echo_agent")
async def test_agent_execution_logs_turn_and_history_size() -> None:
    service = AgentService(Settings(env="test"))
    first = await service.invoke(AgentRequest(message="one"))
    with structlog.testing.capture_logs() as logs:
        await service.invoke(AgentRequest(message="two", thread_id=first.thread_id))
    (started,) = _logs_named(logs, "agent_execution_started")
    assert started["turn"] == 2
    assert started["history_messages"] == 2


async def test_checkpoint_failures_are_logged_and_reraised() -> None:
    saver = InMemorySaver()

    async def broken(*_: Any, **__: Any) -> None:
        raise psycopg.OperationalError("password=hunter2 connection refused")

    saver.aget_tuple = broken  # type: ignore[method-assign]
    instrument_checkpointer(saver, "postgres")
    with structlog.testing.capture_logs() as logs, pytest.raises(psycopg.OperationalError):
        await saver.aget_tuple({"configurable": {"thread_id": "t"}})
    (failed,) = _logs_named(logs, "checkpoint_operation_failed")
    assert failed["operation"] == "aget_tuple"
    assert failed["backend"] == "postgres"
    assert failed["error_type"] == "OperationalError"
    assert "hunter2" not in repr(logs)


async def test_slow_checkpoint_operations_are_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(checkpointer_module, "SLOW_CHECKPOINT_MS", 0.0)
    saver = instrument_checkpointer(InMemorySaver(), "memory")
    assert isinstance(saver, InMemorySaver)  # still the original class
    with structlog.testing.capture_logs() as logs:
        await saver.aget_tuple({"configurable": {"thread_id": "t"}})
    (slow,) = _logs_named(logs, "checkpoint_operation_slow")
    assert slow["operation"] == "aget_tuple"
    assert slow["duration_ms"] >= 0
