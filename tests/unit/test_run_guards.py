from __future__ import annotations

import asyncio
from typing import Any

import anyio
import pytest
import structlog.testing
from fastapi.testclient import TestClient

from neuron_agent.api import main as api_main
from neuron_agent.api.main import app
from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import CapacityError, RunTimeoutError, ThreadBusyError
from neuron_agent.graphs import main_graph
from neuron_agent.schemas.agent import AgentAnswer, AgentRequest
from neuron_agent.services.agent_service import AgentService, RunLease
from neuron_agent.services.streaming import StreamEvent

pytestmark = pytest.mark.anyio


class GatedAgent:
    """Blocks inside the run until `gate` is set; records whether it was cancelled."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.gate = asyncio.Event()
        self.cancelled = False
        self.calls = 0

    async def ainvoke(self, inputs: dict[str, Any], *, config: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        self.started.set()
        try:
            await self.gate.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        answer = f"answer {self.calls}"
        return {
            "messages": [],
            "structured_response": AgentAnswer(answer=answer, used_tools=[], confidence=1.0),
        }


@pytest.fixture
def gated(monkeypatch: pytest.MonkeyPatch) -> GatedAgent:
    agent = GatedAgent()
    monkeypatch.setattr(main_graph, "build_agent", lambda settings: agent)
    return agent


def _service(**overrides: Any) -> AgentService:
    return AgentService(Settings(env="test", **overrides))


async def _new_thread(service: AgentService, agent: GatedAgent) -> str:
    agent.gate.set()
    thread_id = (await service.invoke(AgentRequest(message="first"))).thread_id
    agent.gate.clear()
    agent.started.clear()
    return thread_id


async def _messages(service: AgentService, thread_id: str) -> list[str]:
    state = await service.graph.aget_state({"configurable": {"thread_id": thread_id}})
    return [str(m.content) for m in state.values["messages"]]


def _idle(service: AgentService) -> bool:
    return not service._active_threads and service._open_streams == 0


async def test_closing_the_stream_cancels_the_run_and_keeps_history(gated: GatedAgent) -> None:
    service = _service()
    thread_id = await _new_thread(service, gated)
    run = await service.prepare(AgentRequest(message="lost", thread_id=thread_id), streaming=True)
    stream = service.stream(run)

    assert (await anext(stream)).event == "run_started"
    pending = asyncio.ensure_future(anext(stream))
    await gated.started.wait()
    with structlog.testing.capture_logs() as logs:
        pending.cancel()  # the client disconnected while we waited for the next event
        with pytest.raises(asyncio.CancelledError):
            await pending
        await stream.aclose()

    assert gated.cancelled is True
    assert any(log["event"] == "stream_cancelled" for log in logs)
    assert _idle(service)
    assert await _messages(service, thread_id) == ["first", "answer 1"]

    gated.gate.set()
    retried = await service.invoke(AgentRequest(message="again", thread_id=thread_id))
    assert await _messages(service, thread_id) == ["first", "answer 1", "again", retried.answer]


async def test_stream_timeout_emits_one_error_and_releases_resources(gated: GatedAgent) -> None:
    service = _service(run_timeout_seconds=1)
    run = await service.prepare(AgentRequest(message="slow"), streaming=True)
    events = [event async for event in service.stream(run)]

    assert [event.event for event in events] == ["run_started", "error", "done"]
    assert events[1].data == {"code": "run_timeout", "retryable": True}
    assert gated.cancelled is True
    assert _idle(service)


async def test_invoke_timeout_raises_run_timeout(gated: GatedAgent) -> None:
    service = _service(run_timeout_seconds=1)
    with pytest.raises(RunTimeoutError):
        await service.invoke(AgentRequest(message="slow"))
    assert gated.cancelled is True
    assert _idle(service)


async def test_concurrent_run_on_busy_thread_is_rejected(gated: GatedAgent) -> None:
    service = _service()
    thread_id = await _new_thread(service, gated)
    first = asyncio.create_task(service.invoke(AgentRequest(message="slow", thread_id=thread_id)))
    await gated.started.wait()

    with pytest.raises(ThreadBusyError):
        await service.invoke(AgentRequest(message="second", thread_id=thread_id))
    with pytest.raises(ThreadBusyError):
        await service.prepare(AgentRequest(message="second", thread_id=thread_id), streaming=True)

    gated.gate.set()
    assert (await first).answer == "answer 2"  # the first run is unaffected
    assert _idle(service)
    await service.invoke(AgentRequest(message="third", thread_id=thread_id))


async def test_busy_guard_does_not_apply_without_persistence(gated: GatedAgent) -> None:
    service = _service(checkpointer="none")
    shared = "6f9619ff-8b86-d011-b42d-00c04fc964ff"
    first = asyncio.create_task(service.invoke(AgentRequest(message="a", thread_id=shared)))
    await gated.started.wait()
    second = asyncio.create_task(service.invoke(AgentRequest(message="b", thread_id=shared)))
    gated.gate.set()
    await asyncio.gather(first, second)


async def test_concurrent_stream_cap_is_enforced(gated: GatedAgent) -> None:
    service = _service(max_concurrent_streams=1)
    held = await service.prepare(AgentRequest(message="a"), streaming=True)
    with pytest.raises(CapacityError):
        await service.prepare(AgentRequest(message="b"), streaming=True)

    # Non-streaming requests don't count against the stream cap.
    gated.gate.set()
    await service.invoke(AgentRequest(message="c"))

    held.lease.release()
    (await service.prepare(AgentRequest(message="d"), streaming=True)).lease.release()
    assert _idle(service)


async def test_stop_signal_ends_stream_with_shutdown_error(gated: GatedAgent) -> None:
    service = _service()
    stop = asyncio.Event()
    run = await service.prepare(AgentRequest(message="slow"), streaming=True)
    events: list[StreamEvent] = []
    async for event in service.stream(run, stop=stop):
        events.append(event)
        if event.event == "run_started":
            await gated.started.wait()
            stop.set()

    assert [event.event for event in events] == ["run_started", "error", "done"]
    assert events[1].data == {"code": "service_shutting_down", "retryable": True}
    assert gated.cancelled is True
    assert _idle(service)


def test_run_lease_release_is_idempotent() -> None:
    released: list[int] = []
    lease = RunLease(lambda: released.append(1))
    lease.release()
    lease.release()
    assert released == [1]


# --- HTTP mapping -----------------------------------------------------------------


def test_invoke_returns_409_for_busy_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    service = AgentService(Settings(env="test"))
    monkeypatch.setattr(api_main, "service", service)
    client = TestClient(app)
    thread_id = client.post("/v1/agent/invoke", json={"message": "hi"}).json()["thread_id"]

    service._active_threads.add(thread_id)
    for path in ("/v1/agent/invoke", "/v1/agent/stream"):
        response = client.post(path, json={"message": "hi", "thread_id": thread_id})
        assert response.status_code == 409
        assert response.json() == {"detail": "thread_busy"}


def test_stream_returns_503_when_at_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    service = AgentService(Settings(env="test", max_concurrent_streams=1))
    monkeypatch.setattr(api_main, "service", service)
    service._open_streams = 1
    response = TestClient(app).post("/v1/agent/stream", json={"message": "hi"})
    assert response.status_code == 503
    assert response.json() == {"detail": "too_many_streams"}


def test_stream_endpoint_releases_its_lease(monkeypatch: pytest.MonkeyPatch) -> None:
    service = AgentService(Settings(env="test"))
    monkeypatch.setattr(api_main, "service", service)
    response = TestClient(app).post("/v1/agent/stream", json={"message": "hi"})
    assert response.status_code == 200
    assert _idle(service)


async def test_disconnect_via_anyio_cancel_scope_stops_the_run(gated: GatedAgent) -> None:
    # Regression: sse-starlette cancels the stream through an anyio cancel scope, which
    # re-delivers cancellation on every await. That used to re-cancel the producer task
    # repeatedly, so LangGraph abandoned the running node and the model kept generating.
    service = _service()
    tasks_before = asyncio.all_tasks()
    run = await service.prepare(AgentRequest(message="hi"), streaming=True)
    stream = service.stream(run)

    async def consume() -> None:
        async for _ in stream:
            pass

    async with anyio.create_task_group() as group:
        group.start_soon(consume)
        await gated.started.wait()
        group.cancel_scope.cancel()

    await asyncio.sleep(0)  # let any orphaned node task run, if one survived
    assert gated.cancelled is True
    assert _idle(service)
    assert asyncio.all_tasks() - tasks_before == set()


async def test_run_budget_holds_when_client_stops_reading(gated: GatedAgent) -> None:
    # Regression: the deadline used to be checked only while the generator awaited the
    # next event, so a client that stopped reading kept the run (and its lease) alive.
    service = _service(run_timeout_seconds=1)
    run = await service.prepare(AgentRequest(message="slow"), streaming=True)
    stream = service.stream(run)
    assert (await anext(stream)).event == "run_started"  # then the client stops reading

    await asyncio.sleep(1.5)
    assert gated.cancelled is True  # the producer enforced the budget on its own
    rest = [event async for event in stream]
    assert [event.event for event in rest] == ["error", "done"]
    assert rest[0].data["code"] == "run_timeout"
    assert _idle(service)


async def test_lease_released_when_response_fails_before_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression: sse-starlette skips its `background` hook when sending fails, which
    # leaked the lease (thread stuck busy, stream slot lost).
    service = AgentService(Settings(env="test"))
    monkeypatch.setattr(api_main, "service", service)
    response = await api_main.stream_agent(AgentRequest(message="hi"))
    assert service._open_streams == 1

    async def receive() -> dict[str, Any]:
        await anyio.sleep_forever()
        return {}  # pragma: no cover

    async def send(message: dict[str, Any]) -> None:
        raise OSError("client went away")

    scope = {"type": "http", "method": "POST", "path": "/v1/agent/stream", "headers": []}
    with pytest.raises(BaseException):  # noqa: B017 - sse-starlette may wrap it in a group
        await response(scope, receive, send)
    assert _idle(service)
