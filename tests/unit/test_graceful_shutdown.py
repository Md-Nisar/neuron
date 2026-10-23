# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Graceful shutdown for invoke (issue #136, ADR 0008 decision 4)."""

from __future__ import annotations

import asyncio
import http.client
import json
import os
import signal
import socket
import subprocess  # noqa: S404 - runs this repository's own entrypoint
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
import structlog.testing
from sse_starlette.sse import AppStatus

from neuron_agent.api import main as api_main
from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import ShuttingDownError
from neuron_agent.graphs import main_graph
from neuron_agent.schemas.agent import AgentAnswer, AgentRequest
from neuron_agent.security.authorization import TokenUsageAccumulator
from neuron_agent.services.agent_service import AgentService

pytestmark = pytest.mark.anyio

DRAIN_SECONDS = 1.0


class DelayedAgent:
    """Answers after `delay` seconds; `started` is set when a run is in the model call."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.started = asyncio.Event()

    async def ainvoke(
        self, inputs: dict[str, Any], *, config: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        self.started.set()
        await asyncio.sleep(self.delay)
        answer = AgentAnswer(answer="finished", used_tools=[], confidence=1.0)
        return {"messages": [], "structured_response": answer}


async def _until(condition: Callable[[], Any], what: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        await asyncio.sleep(0.02)


async def test_ready_turns_503_then_new_runs_are_refused_while_in_flight_run_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = Settings(env="test", shutdown_drain_seconds=DRAIN_SECONDS)
    agent = DelayedAgent(delay=DRAIN_SECONDS + 1.0)
    monkeypatch.setattr(main_graph, "build_agent", lambda settings: agent)
    monkeypatch.setattr(api_main, "service", AgentService(config))
    # sse-starlette's patched `handle_exit` sets this process-wide flag; undo it afterwards.
    monkeypatch.setattr(AppStatus, "should_exit", False)
    server = api_main.build_server(config, port=0, reload=False)
    transport = httpx.ASGITransport(app=api_main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/health/ready")).status_code == 200
        in_flight = asyncio.create_task(client.post("/v1/agent/invoke", json={"message": "slow"}))
        await asyncio.wait_for(agent.started.wait(), 5)

        with structlog.testing.capture_logs() as logs:
            server.handle_exit(signal.SIGTERM, None)
            api_main.service.begin_drain()  # idempotent: no second log line
            await asyncio.sleep(0)

        ready = await client.get("/health/ready")
        assert (ready.status_code, ready.json()) == (503, {"status": "not_ready"})
        draining = [log for log in logs if log["event"] == "service_draining"]
        assert len(draining) == 1
        assert draining[0]["in_flight_runs"] == 1
        # Uvicorn is told to stop only after the drain delay, so it still accepts until then.
        assert server.should_exit is False
        agent.delay = 0.0
        assert (await client.post("/v1/agent/invoke", json={"message": "early"})).status_code == 200

        await _until(lambda: server.should_exit, "Uvicorn to be told to stop")
        refused = await client.post("/v1/agent/invoke", json={"message": "late"})
        assert refused.status_code == 503
        assert refused.json() == {"detail": "service_shutting_down"}
        assert refused.headers["Retry-After"] == "1"
        stream = await client.post("/v1/agent/stream", json={"message": "late"})
        assert (stream.status_code, stream.json()) == (503, {"detail": "service_shutting_down"})

        finished = await asyncio.wait_for(in_flight, 10)
        assert finished.status_code == 200
        assert finished.json()["answer"] == "finished"


async def test_begin_drain_is_idempotent_and_without_a_loop_logs_directly() -> None:
    service = AgentService(Settings(env="test"))
    with structlog.testing.capture_logs() as logs:
        service.begin_drain()
        service.begin_drain()
        await asyncio.sleep(0)
    assert [log["event"] for log in logs] == ["service_draining"]
    assert await service.is_ready() is False


async def test_zero_drain_delay_refuses_new_runs_at_once() -> None:
    service = AgentService(Settings(env="test", shutdown_drain_seconds=0))
    service.begin_drain()
    with pytest.raises(ShuttingDownError):
        await service.prepare(AgentRequest(message="hi"))


async def test_run_cancelled_at_the_graceful_timeout_charges_usage_and_frees_its_leases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage = TokenUsageAccumulator()
    started = asyncio.Event()
    calls = 0
    cancelled = False

    class PartlyDoneAgent:
        async def ainvoke(
            self, inputs: dict[str, Any], *, config: dict[str, Any], context: Any = None
        ) -> dict[str, Any]:
            nonlocal calls, cancelled
            calls += 1
            if calls == 1:  # the run that creates the thread
                answer = AgentAnswer(answer="first", used_tools=[], confidence=1.0)
                return {"messages": [], "structured_response": answer}
            usage.record({"input_tokens": 30, "output_tokens": 12, "total_tokens": 42})
            started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled = True
                raise
            raise AssertionError("unreachable")

    monkeypatch.setattr(main_graph, "build_agent", lambda settings: PartlyDoneAgent())
    service = AgentService(
        Settings(env="test", checkpointer="memory", max_concurrent_runs_per_user=1)
    )
    await service.startup()
    charged: list[int] = []
    real_charge = service._token_budget.charge

    async def charge(key: str, tokens: int) -> None:
        charged.append(tokens)
        await real_charge(key, tokens)

    monkeypatch.setattr(service._token_budget, "charge", charge)
    thread_id = (await service.invoke(AgentRequest(message="first"))).thread_id
    charged.clear()
    guard = service._run_guard

    run = asyncio.create_task(
        service.invoke(AgentRequest(message="long", thread_id=thread_id), usage=usage)
    )
    await asyncio.wait_for(started.wait(), 5)
    assert await guard.is_thread_active(thread_id) is True
    service.begin_drain()

    run.cancel()  # what Uvicorn does to a request still running when its timeout ends
    with pytest.raises(asyncio.CancelledError):
        await run

    assert cancelled is True
    assert charged == [42]
    assert await guard.is_thread_active(thread_id) is False
    assert guard._active_runs_by_owner == {}  # type: ignore[attr-defined]
    assert service._in_flight == 0
    await service.shutdown()


def test_reload_restarts_do_not_wait_for_the_drain_delay() -> None:
    reloading = Settings(env="development", shutdown_drain_seconds=5)
    assert api_main.build_server(reloading)._drain_seconds == 0  # type: ignore[attr-defined]
    serving = Settings(env="test", shutdown_drain_seconds=5)
    assert api_main.build_server(serving)._drain_seconds == 5  # type: ignore[attr-defined]


async def test_sigterm_after_should_exit_is_not_delayed(monkeypatch: pytest.MonkeyPatch) -> None:
    config = Settings(env="test", shutdown_drain_seconds=30)
    monkeypatch.setattr(api_main, "service", AgentService(config))
    monkeypatch.setattr(AppStatus, "should_exit", False)
    server = api_main.build_server(config, reload=False)
    server.should_exit = True
    server.handle_exit(signal.SIGTERM, None)
    assert server._exit_scheduled is False  # type: ignore[attr-defined]


def test_capture_signals_restores_the_default_when_there_was_no_previous_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = signal.signal
    original = signal.getsignal(signal.SIGTERM)

    def forgetful(number: int, handler: Any) -> Any:
        previous = real(number, handler)
        return None if number == signal.SIGTERM and handler == signal.SIG_IGN else previous

    server = api_main.build_server(Settings(env="test"), reload=False)
    try:
        monkeypatch.setattr(signal, "signal", forgetful)
        with server.capture_signals():
            pass
        monkeypatch.setattr(signal, "signal", real)
        assert signal.getsignal(signal.SIGTERM) == signal.SIG_DFL
    finally:
        real(signal.SIGTERM, original)


# --- subprocess: the real entrypoint and a real SIGTERM ---------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(port: int, method: str, path: str, body: dict[str, str] | None = None) -> Any:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        payload = json.dumps(body) if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        connection.request(method, path, payload, headers)
        response = connection.getresponse()
        return response.status, response.read().decode()
    finally:
        connection.close()


def _status(port: int, path: str) -> int | None:
    try:
        return int(_request(port, "GET", path)[0])
    except OSError:
        return None


def _poll(condition: Callable[[], Any], what: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, f"timed out waiting for {what}"
        time.sleep(0.02)


def test_sigterm_ends_streams_finishes_invokes_and_exits_zero(tmp_path: Path) -> None:
    port = _free_port()
    markers = tmp_path / "markers"
    markers.mkdir()
    env = {
        **os.environ,
        "APP_ENV": "test",
        "APP_HOST": "127.0.0.1",
        "APP_PORT": str(port),
        "APP_RUN_TIMEOUT_SECONDS": "30",
        "APP_SHUTDOWN_DRAIN_SECONDS": "1.5",
        "NEURON_TEST_MARKER_DIR": str(markers),
        "NEURON_TEST_RUN_SECONDS": "3",
    }
    env.pop("PORT", None)
    server = subprocess.Popen(  # noqa: S603
        [sys.executable, str(Path(__file__).with_name("_shutdown_server.py"))],
        cwd=tmp_path,  # no developer `.env` is read from here
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    results: dict[str, Any] = {}

    def call(name: str, path: str, message: str) -> None:
        try:
            results[name] = _request(port, "POST", path, {"message": message})
        except Exception as exc:  # noqa: BLE001
            results[name] = exc

    try:

        def up() -> bool:
            assert server.poll() is None, "neuron-api exited during start-up"
            try:
                return bool(_request(port, "GET", "/health/ready")[0] == 200)
            except OSError:
                return False

        _poll(up, "the server to be ready", 30)
        clients = [
            threading.Thread(target=call, args=("stream", "/v1/agent/stream", "stream please")),
            threading.Thread(target=call, args=("invoke", "/v1/agent/invoke", "invoke please")),
        ]
        for client in clients:
            client.start()
        _poll(lambda: len(list(markers.iterdir())) == 2, "both runs to be in flight", 15)

        server.send_signal(signal.SIGTERM)
        _poll(lambda: _status(port, "/health/ready") == 503, "readiness to turn 503", 5)
        for client in clients:
            client.join(timeout=20)
            assert not client.is_alive()
        assert server.wait(timeout=20) == 0
    finally:
        if server.poll() is None:
            server.kill()
            server.wait(timeout=10)

    status, body = results["invoke"]
    assert (status, json.loads(body)["answer"]) == (200, "finished")
    status, body = results["stream"]
    assert status == 200
    assert '"code": "service_shutting_down"' in body
    assert body.index("service_shutting_down") < body.index("event: done")


def test_readiness_turns_503_on_sigterm_under_python_dash_m(tmp_path: Path) -> None:
    """`python -m` runs this module as `__main__`; Uvicorn serves the imported copy."""
    port = _free_port()
    env = {
        **os.environ,
        "APP_ENV": "test",
        "APP_HOST": "127.0.0.1",
        "APP_PORT": str(port),
        "APP_SHUTDOWN_DRAIN_SECONDS": "5",
    }
    env.pop("PORT", None)
    server = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "neuron_agent.api.main"],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _poll(lambda: _status(port, "/health/ready") == 200, "the server to be ready", 30)
        server.send_signal(signal.SIGTERM)
        _poll(lambda: _status(port, "/health/ready") == 503, "readiness to turn 503", 4)
        assert server.wait(timeout=20) == 0
    finally:
        if server.poll() is None:
            server.kill()
            server.wait(timeout=10)
