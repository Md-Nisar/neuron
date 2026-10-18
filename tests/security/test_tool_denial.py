"""A denied tool call is a tool error the model can act on, not a failed run (#99)."""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import structlog.testing
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from pydantic import Field
from tests.conftest import JwtApi, StreamingFakeModel, bearer

from neuron_agent.graphs import main_graph
from neuron_agent.models import factory
from neuron_agent.observability import metrics

_ANSWER = "I can't use that tool, so here is my answer without it."
_DENIED_TEXT = "Error: this tool call was denied. Answer without the tool."
_ARGUMENT = "7*191"
_CASES = [
    # (tool the model calls, scopes the caller holds, policy-block rule)
    ("calculator", "agent:invoke", "insufficient_scope"),
    ("shell_exec", "agent:invoke tools:calculator", "unknown_tool"),
]


class _RecordingModel(StreamingFakeModel):
    """Records every message list the model was called with."""

    seen: list[list[BaseMessage]] = Field(default_factory=list)

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> ChatResult:
        self.seen.append(list(messages))
        return super()._generate(messages, *args, **kwargs)

    def _stream(
        self, messages: list[BaseMessage], *args: Any, **kwargs: Any
    ) -> Iterator[ChatGenerationChunk]:
        self.seen.append(list(messages))
        return super()._stream(messages, *args, **kwargs)


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], _RecordingModel]:
    def use(tool: str) -> _RecordingModel:
        call = {"name": tool, "args": {"expression": _ARGUMENT}, "id": "call-1"}
        replies = iter([AIMessage(content="", tool_calls=[call]), AIMessage(content=_ANSWER)])
        recording = _RecordingModel(messages=replies)
        monkeypatch.setattr(factory, "create_chat_model", lambda settings: recording)
        return recording

    return use


@pytest.fixture
def policy_blocks(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    blocked: list[str] = []
    monkeypatch.setattr(metrics, "record_policy_block", blocked.append)
    return blocked


def _assert_denied_and_recovered(
    recording: _RecordingModel, logs: list[dict[str, Any]], blocked: list[str], tool: str, rule: str
) -> None:
    # The tool never ran: the isolation middleware inside the check logs every executed call.
    assert not [log for log in logs if log["event"].startswith("tool_call_")]
    [denied] = [log for log in logs if log["event"] == "authorization_denied"]
    assert (denied["resource_id"], denied["reason"]) == (tool, rule)
    assert blocked == [rule]
    # The model got the fixed text, and nothing it or the user chose, then answered.
    [tool_message] = [m for m in recording.seen[-1] if isinstance(m, ToolMessage)]
    assert tool_message.content == _DENIED_TEXT
    assert tool_message.status == "error"
    assert tool_message.tool_call_id == "call-1"
    assert next(recording.messages, None) is None


@pytest.mark.parametrize(("tool", "scopes", "rule"), _CASES)
def test_denied_tool_call_on_invoke_lets_the_run_complete(
    model: Callable[[str], _RecordingModel],
    policy_blocks: list[str],
    jwt_api_factory: Callable[..., JwtApi],
    make_token: Callable[..., str],
    tool: str,
    scopes: str,
    rule: str,
) -> None:
    recording = model(tool)
    api = jwt_api_factory()
    headers = bearer(make_token("alice", scopes=scopes))

    with structlog.testing.capture_logs() as logs:
        response = api.client.post("/v1/agent/invoke", json={"message": "go"}, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["answer"] == _ANSWER
    assert response.json()["used_tools"] == []
    _assert_denied_and_recovered(recording, logs, policy_blocks, tool, rule)


@pytest.mark.parametrize(("tool", "scopes", "rule"), _CASES)
def test_denied_tool_call_on_stream_lets_the_run_complete(
    model: Callable[[str], _RecordingModel],
    policy_blocks: list[str],
    jwt_api_factory: Callable[..., JwtApi],
    make_token: Callable[..., str],
    tool: str,
    scopes: str,
    rule: str,
) -> None:
    recording = model(tool)
    api = jwt_api_factory()
    headers = bearer(make_token("alice", scopes=scopes))

    with (
        structlog.testing.capture_logs() as logs,
        api.client.stream(
            "POST", "/v1/agent/stream", json={"message": "go"}, headers=headers
        ) as stream,
    ):
        body = "".join(stream.iter_text())

    assert "event: final" in body
    assert "event: error" not in body
    assert '"used_tools": []' in body
    _assert_denied_and_recovered(recording, logs, policy_blocks, tool, rule)


@pytest.mark.anyio
async def test_denied_tool_call_on_the_agent_server_path_lets_the_run_complete(
    model: Callable[[str], _RecordingModel], policy_blocks: list[str]
) -> None:
    from langchain_core.messages import HumanMessage

    from neuron_agent.config.settings import Settings

    recording = model("calculator")
    graph = main_graph.build_graph(Settings(env="test"))
    configurable = {"langgraph_auth_user_id": "a" * 64, "langgraph_auth_permissions": []}

    with structlog.testing.capture_logs() as logs:
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="go")]}, config={"configurable": configurable}
        )

    assert result["answer"].answer == _ANSWER
    assert result["answer"].used_tools == []
    _assert_denied_and_recovered(recording, logs, policy_blocks, "calculator", "insufficient_scope")


def test_a_model_that_keeps_calling_a_denied_tool_hits_the_step_limit(
    monkeypatch: pytest.MonkeyPatch,
    policy_blocks: list[str],
    jwt_api_factory: Callable[..., JwtApi],
    make_token: Callable[..., str],
) -> None:
    calls = (
        AIMessage(
            content="",
            tool_calls=[{"name": "calculator", "args": {"expression": "1+1"}, "id": f"call-{n}"}],
        )
        for n in itertools.count()
    )
    recording = _RecordingModel(messages=calls)
    monkeypatch.setattr(factory, "create_chat_model", lambda settings: recording)
    api = jwt_api_factory(max_agent_iterations=3)
    headers = bearer(make_token("alice", scopes="agent:invoke"))

    with structlog.testing.capture_logs() as logs:
        response = api.client.post("/v1/agent/invoke", json={"message": "go"}, headers=headers)

    assert response.status_code == 422
    assert response.json() == {"detail": "agent_step_limit_exceeded"}
    assert not [log for log in logs if log["event"].startswith("tool_call_")]
    denied = [log for log in logs if log["event"] == "authorization_denied"]
    # The model asked for the tool on each of its 3 calls, and each was denied without running.
    assert len(denied) == 3
    assert policy_blocks == ["insufficient_scope"] * len(denied)
