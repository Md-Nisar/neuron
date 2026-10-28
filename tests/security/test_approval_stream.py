"""Approvals over the SSE stream (#243, ADR 0009 decision 6)."""

from __future__ import annotations

import itertools
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage
from tests.conftest import JwtApi, StreamingFakeModel, _content_chunks, bearer
from tests.security.test_approval_api import _OWNER, _ran, note_taker
from tests.security.test_multi_user_isolation import _parse_sse

from neuron_agent.models import factory
from neuron_agent.tools.registry import ToolRegistry, ToolSpec, builtin_registry

_NOT_FOUND = {"detail": "approval_not_found"}


class _TextThenToolModel(StreamingFakeModel):
    """Streams a reply's text, then its tool calls, as providers do."""

    def _stream(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        reply = next(self.messages)
        run_manager = kwargs.get("run_manager") or (args[1] if len(args) > 1 else None)
        if reply.content:
            yield from _content_chunks(AIMessage(content=reply.content), run_manager)
        rest = self.messages
        self.messages = itertools.chain([AIMessage(content="", tool_calls=reply.tool_calls)], rest)
        try:
            yield from super()._stream(messages, *args, **kwargs)
        finally:
            self.messages = rest


def _call(text: str = "buy milk", preface: str = "") -> AIMessage:
    call = {"name": "note_taker", "args": {"text": text}, "id": f"call-{uuid.uuid4().hex[:6]}"}
    return AIMessage(content=preface, tool_calls=[call])


@pytest.fixture(autouse=True)
def _reset() -> None:
    _ran.clear()


@pytest.fixture
def api(
    jwt_api_factory: Callable[..., JwtApi], monkeypatch: pytest.MonkeyPatch
) -> Callable[..., JwtApi]:
    import asyncio

    def build(*replies: AIMessage) -> JwtApi:
        monkeypatch.setattr(
            factory, "create_chat_model", lambda _: _TextThenToolModel(messages=iter(replies))
        )
        built = jwt_api_factory()
        built.service.use_registry(
            ToolRegistry(
                [*builtin_registry(), ToolSpec(note_taker, "tools:note_taker", "mutating")]
            )
        )
        asyncio.run(built.service.startup())
        return built

    return build


def _stream(api: JwtApi, path: str, token: str, body: dict[str, Any]) -> tuple[int, str]:
    with api.client.stream("POST", path, json=body, headers=bearer(token)) as response:
        return response.status_code, "".join(response.iter_text())


def _names(events: list[tuple[str, dict[str, Any]]]) -> list[str]:
    return [name for name, _ in events]


def test_a_stream_that_reaches_a_gated_call_ends_with_approval_required(
    api: Callable[..., JwtApi], make_token: Callable[..., str]
) -> None:
    app = api(_call("buy milk", preface="Let me save that note for you."), AIMessage(content="x"))
    token = make_token("alice", scopes=_OWNER)

    status, body = _stream(app, "/v1/agent/stream", token, {"message": "remember milk"})
    events = _parse_sse(body)

    assert status == 200
    names = _names(events)
    assert names[0] == "run_started" and names[-2:] == ["approval_required", "done"]
    assert "final" not in names and "error" not in names
    # The model's own words were released before the pause, nothing was held back.
    spoken = "".join(data["text"] for name, data in events if name == "token")
    assert spoken == "Let me save that note for you."
    [(_, pause)] = [e for e in events if e[0] == "approval_required"]
    assert pause["status"] == "approval_required"
    assert pause["approval"]["actions"] == [{"name": "note_taker", "args": {"text": "buy milk"}}]
    assert pause["thread_id"] == next(d["thread_id"] for n, d in events if n == "run_started")
    # `tool_call` events never carry arguments.
    assert all(set(d) == {"name"} for n, d in events if n == "tool_call")
    assert _ran == []


def test_resuming_streams_the_continuation(
    api: Callable[..., JwtApi], make_token: Callable[..., str]
) -> None:
    app = api(_call(), AIMessage(content="All saved."))
    token = make_token("alice", scopes=_OWNER)
    _, body = _stream(app, "/v1/agent/stream", token, {"message": "remember milk"})
    [(_, pause)] = [e for e in _parse_sse(body) if e[0] == "approval_required"]
    path = f"/v1/threads/{pause['thread_id']}/approvals/{pause['approval']['approval_id']}/stream"

    status, resumed = _stream(app, path, token, {"decision": "approve"})
    events = _parse_sse(resumed)

    assert status == 200
    assert _names(events)[0] == "run_started" and _names(events)[-2:] == ["final", "done"]
    started = next(d for n, d in events if n == "run_started")
    assert started["request_id"] != pause["request_id"]
    assert next(d for n, d in events if n == "final")["answer"] == "All saved."
    assert _ran == ["buy milk"]
    # Single use, here too, and before any byte is sent.
    again, text = _stream(app, path, token, {"decision": "approve"})
    assert (again, text) == (404, '{"detail":"approval_not_found"}')


def test_a_rejected_stream_never_runs_the_tool(
    api: Callable[..., JwtApi], make_token: Callable[..., str]
) -> None:
    app = api(_call(), AIMessage(content="Not saved."))
    token = make_token("alice", scopes=_OWNER)
    _, body = _stream(app, "/v1/agent/stream", token, {"message": "remember milk"})
    [(_, pause)] = [e for e in _parse_sse(body) if e[0] == "approval_required"]
    path = f"/v1/threads/{pause['thread_id']}/approvals/{pause['approval']['approval_id']}/stream"

    _, resumed = _stream(app, path, token, {"decision": "reject"})

    assert next(d for n, d in _parse_sse(resumed) if n == "final")["used_tools"] == []
    assert _ran == []


def test_another_user_gets_a_plain_404_before_any_stream_byte(
    api: Callable[..., JwtApi], make_token: Callable[..., str]
) -> None:
    app = api(_call(), AIMessage(content="x"))
    alice = make_token("alice", scopes=_OWNER)
    mallory = make_token("mallory", scopes=_OWNER)
    _, body = _stream(app, "/v1/agent/stream", alice, {"message": "remember milk"})
    [(_, pause)] = [e for e in _parse_sse(body) if e[0] == "approval_required"]
    thread, approval = pause["thread_id"], pause["approval"]["approval_id"]

    stolen = app.client.post(
        f"/v1/threads/{thread}/approvals/{approval}/stream",
        json={"decision": "approve"},
        headers=bearer(mallory),
    )

    assert (stolen.status_code, stolen.json()) == (404, _NOT_FOUND)
    assert _ran == []


def test_a_client_that_leaves_mid_stream_releases_the_thread(
    api: Callable[..., JwtApi], make_token: Callable[..., str]
) -> None:
    app = api(_call(), AIMessage(content="All saved."), AIMessage(content="later"))
    token = make_token("alice", scopes=_OWNER)
    _, body = _stream(app, "/v1/agent/stream", token, {"message": "remember milk"})
    [(_, pause)] = [e for e in _parse_sse(body) if e[0] == "approval_required"]
    thread, approval = pause["thread_id"], pause["approval"]["approval_id"]
    path = f"/v1/threads/{thread}/approvals/{approval}/stream"

    with app.client.stream(
        "POST", path, json={"decision": "approve"}, headers=bearer(token)
    ) as response:
        next(response.iter_lines())  # read one line, then hang up

    # Whether or not the run got to the tool, the lease is gone: the decision is either still
    # open (and can be made) or already used, but the thread is never stuck busy.
    retry = app.client.post(
        f"/v1/threads/{thread}/approvals/{approval}",
        json={"decision": "approve"},
        headers=bearer(token),
    )
    assert retry.status_code in {200, 404}, retry.text
    assert len(_ran) <= 1
