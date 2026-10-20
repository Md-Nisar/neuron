"""The post-deploy smoke test (`scripts/smoke_test.py`, #152).

The script talks real HTTP to the real API app (fake agent, in-process JWKS) served by
uvicorn on a loopback port, so status handling, timeouts and output are the ones a
deployment would see.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
import uvicorn
from scripts import smoke_test
from tests.conftest import HistoryEchoAgent, JwtApi

from neuron_agent.api import main as api_main

ENV_NAME = smoke_test.TOKEN_ENV


@pytest.fixture
def live_url(jwt_api_factory: Callable[..., JwtApi], echo_agent: HistoryEchoAgent) -> Iterator[Any]:
    """Serve the API on a loopback port; yield a `start(**settings)` that returns its URL."""
    servers: list[tuple[uvicorn.Server, threading.Thread]] = []

    def start(**overrides: Any) -> str:
        jwt_api_factory(checkpointer="none", **overrides)
        server = uvicorn.Server(
            uvicorn.Config(api_main.app, host="127.0.0.1", port=0, log_level="critical")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started
        servers.append((server, thread))
        return f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"

    yield start
    for server, thread in servers:
        server.should_exit = True
        thread.join(timeout=10)


def _stub(status: int, body: bytes) -> tuple[str, ThreadingHTTPServer]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}", server


def _smoke(url: str, token: str, **env: str) -> int:
    return smoke_test.main([url], {ENV_NAME: token, **env})


def test_success_exits_zero_and_leaves_no_thread(
    live_url: Callable[..., str], make_token: Callable[..., str], capfd: pytest.CaptureFixture[str]
) -> None:
    url = live_url()
    token = make_token("smoke", scopes="agent:invoke")
    assert _smoke(url, token) == 0
    out, err = capfd.readouterr()
    assert "passed" in out
    assert token not in out + err
    assert url not in out + err


def test_persisted_thread_is_deleted(
    live_url: Callable[..., str], make_token: Callable[..., str], jwt_api_factory: Any
) -> None:
    url = live_url()
    jwt_api_factory(checkpointer="memory")  # the running app now persists threads
    smoke = make_token("smoke", scopes="agent:invoke threads:delete")
    assert _smoke(url, smoke) == 0
    reader = make_token("smoke", scopes="threads:read")
    listing = smoke_test._request("list", "GET", url, "/v1/me/threads", 10, token=reader)
    assert listing["total"] == 0


def test_principal_without_delete_scope_warns(
    live_url: Callable[..., str],
    make_token: Callable[..., str],
    jwt_api_factory: Any,
    capfd: pytest.CaptureFixture[str],
) -> None:
    url = live_url()
    jwt_api_factory(checkpointer="memory")
    assert _smoke(url, make_token("smoke", scopes="agent:invoke")) == 0
    assert "no permission to delete" in capfd.readouterr().err


def test_not_ready_instance_fails(
    live_url: Callable[..., str],
    make_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    url = live_url()

    async def not_ready() -> bool:
        return False

    monkeypatch.setattr(api_main.service, "is_ready", not_ready)
    assert _smoke(url, make_token("smoke", scopes="agent:invoke")) == 1
    assert "ready: HTTP 503" in capfd.readouterr().err


def test_unauthenticated_token_fails_with_401(
    live_url: Callable[..., str], make_token: Callable[..., str], capfd: pytest.CaptureFixture[str]
) -> None:
    url = live_url()
    token = make_token("smoke", scopes="agent:invoke", aud="someone-else")
    assert _smoke(url, token) == 1
    out, err = capfd.readouterr()
    assert "invoke: HTTP 401" in err
    assert token not in out + err


def test_missing_scope_fails_with_403(
    live_url: Callable[..., str], make_token: Callable[..., str], capfd: pytest.CaptureFixture[str]
) -> None:
    url = live_url()
    token = make_token("smoke", scopes="threads:read")
    assert _smoke(url, token) == 1
    out, err = capfd.readouterr()
    assert "invoke: HTTP 403" in err
    assert token not in out + err


def test_server_error_fails_with_5xx(
    live_url: Callable[..., str],
    make_token: Callable[..., str],
    echo_agent: HistoryEchoAgent,
    capfd: pytest.CaptureFixture[str],
) -> None:
    url = live_url()
    echo_agent.fail_next = True
    token = make_token("smoke", scopes="agent:invoke")
    assert _smoke(url, token) == 1
    out, err = capfd.readouterr()
    assert "invoke: HTTP 500" in err
    assert token not in out + err


def test_timeout_fails(capfd: pytest.CaptureFixture[str]) -> None:
    with closing(socket.socket()) as silent:  # accepts connections, never answers
        silent.bind(("127.0.0.1", 0))
        silent.listen(1)
        url = f"http://127.0.0.1:{silent.getsockname()[1]}"
        started = time.monotonic()
        assert _smoke(url, "secret-token-value", SMOKE_TEST_TIMEOUT_SECONDS="0.5") == 1
        assert time.monotonic() - started < 5
    out, err = capfd.readouterr()
    assert "timed out" in err
    assert "secret-token-value" not in out + err


def test_connection_refused_fails_without_the_url(capfd: pytest.CaptureFixture[str]) -> None:
    with closing(socket.socket()) as unused:
        unused.bind(("127.0.0.1", 0))
        url = f"http://127.0.0.1:{unused.getsockname()[1]}"
    assert _smoke(url, "secret-token-value") == 1
    out, err = capfd.readouterr()
    assert "request failed" in err
    assert url not in out + err


@pytest.mark.parametrize("body", [b'{"status": "starting"}', b"not json", b"[]"])
def test_wrong_ready_body_fails(body: bytes, capfd: pytest.CaptureFixture[str]) -> None:
    url, server = _stub(200, body)
    try:
        assert _smoke(url, "secret-token-value") == 1
    finally:
        server.shutdown()
    out, err = capfd.readouterr()
    assert "FAILED" in err
    assert "secret-token-value" not in out + err


def test_wrong_invoke_body_fails(
    live_url: Callable[..., str],
    make_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = live_url()
    real = smoke_test._request

    def fake(step: str, *args: Any, **kwargs: Any) -> Any:
        return {"answer": "  "} if step == "invoke" else real(step, *args, **kwargs)

    monkeypatch.setattr(smoke_test, "_request", fake)
    assert _smoke(url, make_token("smoke", scopes="agent:invoke")) == 1


def test_redirect_is_not_followed(capfd: pytest.CaptureFixture[str]) -> None:
    url, server = _stub(302, b"")
    try:
        assert _smoke(url, "secret-token-value") == 1
    finally:
        server.shutdown()
    assert "HTTP 302" in capfd.readouterr().err


def test_misuse_exits_two(capfd: pytest.CaptureFixture[str]) -> None:
    assert smoke_test.main(["http://127.0.0.1:1"], {}) == 2
    assert (
        smoke_test.main(["https://x.test"], {ENV_NAME: "t", "SMOKE_TEST_TIMEOUT_SECONDS": "0"}) == 2
    )
    assert smoke_test.main(["ftp://x.test"], {ENV_NAME: "t"}) == 2
    assert smoke_test.main(["http://api.example.com"], {ENV_NAME: "t"}) == 2
    err = capfd.readouterr().err
    assert ENV_NAME in err
