"""Request body limit without `Content-Length` (#137, ADR 0008 decision 5)."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import structlog.testing
from tests.conftest import JwtApi, bearer

from neuron_agent.api import main as api_main

_LIMIT = 1024
_CHUNK = 100


def _chunks(total: int, size: int = _CHUNK) -> Iterator[bytes]:
    sent = 0
    while sent < total:
        piece = min(size, total - sent)
        sent += piece
        yield b"x" * piece


def _json_in_chunks(message_chars: int) -> Iterator[bytes]:
    body = json.dumps({"message": "a" * message_chars}).encode()
    for start in range(0, len(body), _CHUNK):
        yield body[start : start + _CHUNK]


@pytest.fixture
def api(jwt_api_factory: Callable[..., JwtApi]) -> JwtApi:
    return jwt_api_factory(max_request_body_bytes=_LIMIT)


@pytest.fixture
def token(make_token: Callable[..., str]) -> dict[str, str]:
    return bearer(make_token())


@pytest.mark.parametrize("path", ["/v1/agent/invoke", "/v1/agent/stream"])
def test_chunked_body_over_the_limit_is_rejected_with_the_content_length_contract(
    api: JwtApi, token: dict[str, str], path: str
) -> None:
    with structlog.testing.capture_logs() as logs:
        response = api.client.post(
            path,
            headers={**token, "Content-Type": "application/json"},
            content=_chunks(_LIMIT + 1),
        )

    assert response.status_code == 413
    assert response.json() == {"detail": "payload_too_large"}
    [event] = [log for log in logs if log["event"] == "agent_request_body_too_large"]
    assert "xxxx" not in repr(event)


def test_chunked_body_at_the_limit_is_not_rejected_as_too_large(
    api: JwtApi, token: dict[str, str]
) -> None:
    response = api.client.post(
        "/v1/agent/invoke",
        headers={**token, "Content-Type": "application/json"},
        content=_chunks(_LIMIT),
    )
    assert response.status_code == 422  # reaches validation; the body is not JSON


def test_valid_chunked_json_within_the_limit_is_served(
    api: JwtApi, token: dict[str, str], echo_agent: Any
) -> None:
    response = api.client.post(
        "/v1/agent/invoke",
        headers={**token, "Content-Type": "application/json"},
        content=_json_in_chunks(300),
    )
    assert response.status_code == 200


def test_unauthenticated_oversized_chunked_request_gets_413_not_401(api: JwtApi) -> None:
    response = api.client.post(
        "/v1/agent/invoke",
        headers={"Content-Type": "application/json"},
        content=_chunks(_LIMIT + 1),
    )
    assert response.status_code == 413
    assert response.json() == {"detail": "payload_too_large"}


async def _run_asgi(
    headers: list[tuple[bytes, bytes]], body_chunks: list[bytes]
) -> tuple[int, int]:
    """Drive the app directly; return the status and how many body chunks it consumed."""
    consumed = 0
    pending = list(body_chunks)
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal consumed
        if not pending:
            return {"type": "http.disconnect"}
        consumed += 1
        return {"type": "http.request", "body": pending.pop(0), "more_body": bool(pending)}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/v1/agent/invoke",
        "raw_path": b"/v1/agent/invoke",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"testserver"), *headers],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    await api_main.app(scope, receive, send)  # type: ignore[arg-type]
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"], consumed


@pytest.mark.anyio
async def test_slow_drip_body_is_cut_off_when_it_crosses_the_limit(api: JwtApi) -> None:
    chunks = [b"x" * 100 for _ in range(1000)]
    status, consumed = await _run_asgi([(b"transfer-encoding", b"chunked")], chunks)

    assert status == 413
    # Stops at the chunk that crosses the limit: limit + one chunk, not the whole stream.
    assert consumed == _LIMIT // 100 + 1


@pytest.mark.anyio
async def test_declared_length_that_understates_the_body_is_cut_off(api: JwtApi) -> None:
    chunks = [b"x" * 100 for _ in range(1000)]
    status, consumed = await _run_asgi([(b"content-length", b"10")], chunks)

    assert status == 413
    assert consumed == _LIMIT // 100 + 1


@pytest.mark.anyio
async def test_expect_continue_with_oversized_declared_length_reads_no_body(api: JwtApi) -> None:
    headers = [(b"expect", b"100-continue"), (b"content-length", str(_LIMIT + 1).encode())]
    status, consumed = await _run_asgi(headers, [b"x" * 100])

    assert status == 413
    assert consumed == 0


@pytest.mark.anyio
async def test_many_small_chunks_are_replayed_as_one_message(api: JwtApi) -> None:
    seen: list[dict[str, Any]] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        seen.append(await receive())
        seen.append(await receive())

    pending = [b"ab"] * 50 + [b""]
    served = 0

    async def receive() -> dict[str, Any]:
        nonlocal served
        if served >= len(pending):
            return {"type": "http.disconnect"}
        served += 1
        return {
            "type": "http.request",
            "body": pending[served - 1],
            "more_body": served < len(pending),
        }

    async def send(message: dict[str, Any]) -> None:
        raise AssertionError("the app must be reached")

    middleware = api_main._RequestBodyLimitMiddleware(inner)
    await middleware({"type": "http", "headers": []}, receive, send)

    assert seen[0]["body"] == b"ab" * 50
    assert seen[0]["more_body"] is False
    assert seen[1] == {"type": "http.disconnect"}  # later reads go to the server


@pytest.mark.anyio
@pytest.mark.parametrize("value", [b"+5", b"1_0", b"-1", b"5.0"])
async def test_non_numeric_content_length_is_a_400(api: JwtApi, value: bytes) -> None:
    status, consumed = await _run_asgi([(b"content-length", value)], [b"x"])

    assert status == 400
    assert consumed == 0
