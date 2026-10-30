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
from neuron_agent.security.run_guard import InMemoryRunGuard, RunClaimDenied, RunGuard, RunLease
from neuron_agent.services.agent_service import AgentService
from neuron_agent.services.streaming import StreamEvent

pytestmark = pytest.mark.anyio


class GatedAgent:
    """Blocks inside the run until `gate` is set; records whether it was cancelled."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.gate = asyncio.Event()
        self.cancelled = False
        self.calls = 0

    async def ainvoke(
        self, inputs: dict[str, Any], *, config: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
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
    return not service._run_guard._active_threads and service._run_guard._open_streams == 0


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

    await held.lease.release()
    await (await service.prepare(AgentRequest(message="d"), streaming=True)).lease.release()
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


async def test_run_lease_release_is_idempotent() -> None:
    released: list[int] = []

    async def release() -> None:
        released.append(1)

    lease = RunLease(release)
    await lease.release()
    await lease.release()
    assert released == [1]


async def test_in_memory_run_guard_enforces_each_cap_in_order() -> None:
    guard = InMemoryRunGuard(max_concurrent_streams=1, max_concurrent_runs_per_user=2)
    stream = await guard.claim(thread_id="t1", owner_key="a", streaming=True, guard_thread=True)
    for kwargs, reason in (
        ({"thread_id": "t2", "owner_key": "b", "streaming": True}, "concurrent_streams"),
        ({"thread_id": "t1", "owner_key": "b", "streaming": False}, "thread_busy"),
    ):
        with pytest.raises(RunClaimDenied) as denied:
            await guard.claim(guard_thread=True, **kwargs)  # type: ignore[arg-type]
        assert denied.value.reason == reason
    await guard.claim(thread_id="t2", owner_key="a", streaming=False, guard_thread=True)
    with pytest.raises(RunClaimDenied) as denied:
        await guard.claim(thread_id="t3", owner_key="a", streaming=False, guard_thread=True)
    assert denied.value.reason == "concurrent_runs"
    assert await guard.active_threads_of("a") == {"t1", "t2"}
    assert await guard.is_thread_active("t1") is True
    await stream.release()
    assert await guard.is_thread_active("t1") is False


async def test_cancelled_while_releasing_still_frees_the_lease() -> None:
    freed = asyncio.Event()

    async def slow_release() -> None:
        await asyncio.sleep(0.05)  # stands in for a database round trip
        freed.set()

    lease = RunLease(slow_release)
    releasing = asyncio.ensure_future(lease.release())
    await asyncio.sleep(0)  # let the release start, then cancel it mid-flight
    releasing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await releasing
    await asyncio.wait_for(freed.wait(), timeout=1)  # without asyncio.shield this never fires


class _SlowReleaseGuard:
    """Wraps the in-memory guard so that releasing takes a real await."""

    def __init__(self, inner: InMemoryRunGuard) -> None:
        self._inner = inner

    async def claim(
        self, *, thread_id: str, owner_key: str, streaming: bool, guard_thread: bool
    ) -> RunLease:
        lease = await self._inner.claim(
            thread_id=thread_id, owner_key=owner_key, streaming=streaming, guard_thread=guard_thread
        )

        async def release() -> None:
            await asyncio.sleep(0.05)
            await lease.release()

        return RunLease(release)

    async def is_thread_active(self, thread_id: str) -> bool:
        return await self._inner.is_thread_active(thread_id)

    async def active_threads_of(self, owner_key: str) -> frozenset[str]:
        return await self._inner.active_threads_of(owner_key)


async def test_run_cancelled_while_releasing_frees_its_thread(gated: GatedAgent) -> None:
    inner = InMemoryRunGuard(max_concurrent_streams=10, max_concurrent_runs_per_user=10)
    guard: RunGuard = _SlowReleaseGuard(inner)
    service = AgentService(Settings(env="test"), run_guard=guard)
    gated.gate.set()
    thread_id = (await service.invoke(AgentRequest(message="first"))).thread_id
    gated.gate.clear()
    gated.started.clear()

    run = asyncio.create_task(service.invoke(AgentRequest(message="slow", thread_id=thread_id)))
    await gated.started.wait()
    run.cancel()  # cancels the model call; the release in `finally` then awaits
    await asyncio.sleep(0.01)
    run.cancel()  # a second cancel lands while the lease is releasing
    with pytest.raises(asyncio.CancelledError):
        await run

    await asyncio.sleep(0.2)
    assert await inner.is_thread_active(thread_id) is False


# --- HTTP mapping -----------------------------------------------------------------


def test_invoke_returns_409_for_busy_thread(
    monkeypatch: pytest.MonkeyPatch, echo_agent: Any
) -> None:
    service = AgentService(Settings(env="test"))
    monkeypatch.setattr(api_main, "service", service)
    client = TestClient(app)
    thread_id = client.post("/v1/agent/invoke", json={"message": "hi"}).json()["thread_id"]

    service._run_guard._active_threads.add(thread_id)
    for path in ("/v1/agent/invoke", "/v1/agent/stream"):
        response = client.post(path, json={"message": "hi", "thread_id": thread_id})
        assert response.status_code == 409
        assert response.json() == {"detail": "thread_busy"}


def test_stream_returns_503_when_at_capacity(monkeypatch: pytest.MonkeyPatch) -> None:
    service = AgentService(Settings(env="test", max_concurrent_streams=1))
    monkeypatch.setattr(api_main, "service", service)
    service._run_guard._open_streams = 1
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
    assert service._run_guard._open_streams == 1

    async def receive() -> dict[str, Any]:
        await anyio.sleep_forever()
        return {}  # pragma: no cover

    async def send(message: dict[str, Any]) -> None:
        raise OSError("client went away")

    scope = {"type": "http", "method": "POST", "path": "/v1/agent/stream", "headers": []}
    with pytest.raises(BaseException):  # noqa: B017 - sse-starlette may wrap it in a group
        await response(scope, receive, send)
    assert _idle(service)
