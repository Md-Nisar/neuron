from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Iterator, Sequence
from typing import Any

import pytest
import structlog.testing
from fastapi.testclient import TestClient
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.messages.tool import tool_call_chunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from neuron_agent.api import main as api_main
from neuron_agent.api.main import app
from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import RateLimitError
from neuron_agent.graphs import main_graph
from neuron_agent.models import factory
from neuron_agent.schemas.agent import AgentRequest
from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter
from neuron_agent.services.agent_service import AgentService
from neuron_agent.services.streaming import AnswerTokenExtractor, StreamEvent, tool_call_names

pytestmark = pytest.mark.anyio

_ANSWER_JSON = '{"answer": "Hello there world", "used_tools": [], "confidence": 0.9}'


class StreamingFakeModel(GenericFakeChatModel):
    """Streams scripted replies chunk by chunk; tool binding is a no-op.

    Unlike the base class, tool calls are streamed too: as `tool_call_chunks` whose JSON
    arguments arrive in small fragments, the way OpenAI streams them.
    """

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        reply = next(self.messages)
        if not isinstance(reply, AIMessage) or not reply.tool_calls:
            yield from _content_chunks(reply, run_manager)
            return
        message_id = f"run-{uuid.uuid4()}"
        for index, call in enumerate(reply.tool_calls):
            args = json.dumps(call["args"])
            pieces = [args[i : i + 4] for i in range(0, len(args), 4)]
            for n, piece in enumerate(pieces):
                tool_chunk = tool_call_chunk(
                    name=call["name"] if n == 0 else None,
                    args=piece,
                    id=call["id"] if n == 0 else None,
                    index=index,
                )
                chunk = ChatGenerationChunk(
                    message=AIMessageChunk(content="", id=message_id, tool_call_chunks=[tool_chunk])
                )
                if run_manager:
                    run_manager.on_llm_new_token("", chunk=chunk)
                yield chunk

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        return self


def _content_chunks(
    reply: BaseMessage, run_manager: CallbackManagerForLLMRun | None
) -> Iterator[ChatGenerationChunk]:
    message_id = f"run-{uuid.uuid4()}"
    for token in re.split(r"(\s)", str(reply.content)):
        chunk = ChatGenerationChunk(message=AIMessageChunk(content=token, id=message_id))
        if run_manager:
            run_manager.on_llm_new_token(token, chunk=chunk)
        yield chunk


def _use_model(monkeypatch: pytest.MonkeyPatch, *replies: AIMessage) -> None:
    model = StreamingFakeModel(messages=iter(replies))
    monkeypatch.setattr(factory, "create_chat_model", lambda settings: model)


async def _collect(service: AgentService, request: AgentRequest) -> list[StreamEvent]:
    run = await service.prepare(request)
    return [event async for event in service.stream(run)]


def _names(events: list[StreamEvent]) -> list[str]:
    return [event.event for event in events]


def _text(events: list[StreamEvent]) -> str:
    return "".join(event.data["text"] for event in events if event.event == "token")


# --- token extraction -------------------------------------------------------------


def _chunks(text: str, size: int = 3, message_id: str = "m1") -> Iterator[AIMessageChunk]:
    for i in range(0, len(text), size):
        yield AIMessageChunk(content=text[i : i + size], id=message_id)


def test_extractor_emits_only_the_growth_of_the_json_answer_field() -> None:
    extractor = AnswerTokenExtractor()
    deltas = [extractor.feed(chunk) for chunk in _chunks(_ANSWER_JSON)]
    assert "".join(deltas) == "Hello there world"
    assert all("{" not in delta and "confidence" not in delta for delta in deltas)


def test_extractor_passes_plain_text_through() -> None:
    extractor = AnswerTokenExtractor()
    assert "".join(extractor.feed(c) for c in _chunks("plain answer")) == "plain answer"


def test_extractor_reads_structured_output_tool_arguments_only() -> None:
    extractor = AnswerTokenExtractor()
    calculator = AIMessageChunk(
        content="",
        id="m1",
        tool_call_chunks=[{"name": "calculator", "args": '{"expr', "id": "c1", "index": 0}],
    )
    calculator_more = AIMessageChunk(
        content="",
        id="m1",
        tool_call_chunks=[{"name": None, "args": 'ession": "2+2"}', "id": None, "index": 0}],
    )
    answer = AIMessageChunk(
        content="",
        id="m2",
        tool_call_chunks=[
            {"name": "AgentAnswer", "args": '{"answer": "4"', "id": "c2", "index": 0}
        ],
    )
    assert extractor.feed(calculator) == ""
    assert extractor.feed(calculator_more) == ""
    assert extractor.feed(answer) == "4"


def test_tool_call_names_exclude_structured_output_and_continuations() -> None:
    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {"name": "calculator", "args": "", "id": "c1", "index": 0},
            {"name": "AgentAnswer", "args": "", "id": "c2", "index": 1},
            {"name": None, "args": "{}", "id": None, "index": 0},
        ],
    )
    assert tool_call_names(chunk) == ["calculator"]


# --- service event sequence -------------------------------------------------------


async def test_stream_emits_run_started_tokens_final_done(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_model(monkeypatch, AIMessage(content="plain streamed answer"))
    service = AgentService(Settings(env="test"))
    events = await _collect(service, AgentRequest(message="hi"))

    names = _names(events)
    assert names[0] == "run_started"
    assert names[-2:] == ["final", "done"]
    assert set(names[1:-2]) == {"token"}
    assert len(names) > 4  # streamed incrementally, not as one block
    final = events[-2].data
    assert _text(events) == final["answer"] == "plain streamed answer"
    assert final["thread_id"] == events[0].data["thread_id"]
    assert final["request_id"] == events[0].data["request_id"]


async def test_stream_structured_output_tool_call_yields_answer_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_call = {"name": "AgentAnswer", "args": json.loads(_ANSWER_JSON), "id": "c1"}
    _use_model(monkeypatch, AIMessage(content="", tool_calls=[tool_call]))
    events = await _collect(AgentService(Settings(env="test")), AgentRequest(message="hi"))

    final = events[-2]
    assert final.event == "final"
    assert final.data["answer"] == "Hello there world"
    assert final.data["confidence"] == 0.9
    assert _text(events) == "Hello there world"
    assert "tool_call" not in _names(events)


async def test_stream_reports_tool_calls_by_name_only(monkeypatch: pytest.MonkeyPatch) -> None:
    calculator = {"name": "calculator", "args": {"expression": "6*7"}, "id": "c1"}
    _use_model(
        monkeypatch,
        AIMessage(content="", tool_calls=[calculator]),
        AIMessage(content="It is 42"),
    )
    events = await _collect(AgentService(Settings(env="test")), AgentRequest(message="6*7?"))

    tool_events = [event for event in events if event.event == "tool_call"]
    assert [event.data for event in tool_events] == [{"name": "calculator"}]
    assert "6*7" not in json.dumps([event.data for event in events if event.event != "final"])
    assert events[-2].data["answer"] == "It is 42"


async def test_stream_failure_after_start_emits_single_error_then_done(echo_agent: Any) -> None:
    echo_agent.fail_next = True
    with structlog.testing.capture_logs():
        events = await _collect(AgentService(Settings(env="test")), AgentRequest(message="hi"))

    assert _names(events) == ["run_started", "error", "done"]
    assert events[1].data == {"code": "internal_server_error", "retryable": True}


async def test_stream_user_visible_error_keeps_its_code(monkeypatch: pytest.MonkeyPatch) -> None:
    class RateLimitedAgent:
        async def ainvoke(self, inputs: dict[str, Any], *, config: dict[str, Any]) -> None:
            raise RateLimitError("slow down")

    monkeypatch.setattr(main_graph, "build_agent", lambda settings: RateLimitedAgent())
    events = await _collect(AgentService(Settings(env="test")), AgentRequest(message="hi"))
    assert events[1] == StreamEvent("error", {"code": "rate_limit_error", "retryable": True})


async def test_stream_unexpected_exception_is_not_leaked(monkeypatch: pytest.MonkeyPatch) -> None:
    service = AgentService(Settings(env="test"))

    async def explode(*_: object, **__: object) -> Any:
        raise RuntimeError("internal detail /etc/secret")
        yield  # pragma: no cover

    monkeypatch.setattr(service.graph, "astream", explode)
    with structlog.testing.capture_logs():
        events = await _collect(service, AgentRequest(message="hi"))
    assert _names(events) == ["run_started", "error", "done"]
    assert "secret" not in json.dumps([event.data for event in events])


async def test_streamed_turn_is_persisted_to_the_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_model(monkeypatch, AIMessage(content="first answer"), AIMessage(content="second"))
    service = AgentService(Settings(env="test"))
    first = await _collect(service, AgentRequest(message="one"))
    thread_id = first[0].data["thread_id"]

    second = await service.invoke(AgentRequest(message="two", thread_id=thread_id))
    state = await service.graph.aget_state({"configurable": {"thread_id": thread_id}})
    assert second.thread_id == thread_id
    assert [m.content for m in state.values["messages"]] == ["one", "first answer", "two", "second"]


# --- HTTP / SSE -------------------------------------------------------------------


def _parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in body.replace("\r\n", "\n").strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


def test_stream_endpoint_returns_event_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_model(monkeypatch, AIMessage(content="sse answer"))
    monkeypatch.setattr(api_main, "service", AgentService(Settings(env="test")))
    client = TestClient(app)
    response = client.post("/v1/agent/stream", json={"message": "hi"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    events = _parse_sse(response.text)
    assert events[0][0] == "run_started"
    assert [name for name, _ in events[-2:]] == ["final", "done"]
    assert "".join(data["text"] for name, data in events if name == "token") == "sse answer"


@pytest.mark.parametrize(
    ("payload", "status", "detail"),
    [
        ({"message": "hi", "thread_id": "not-a-uuid"}, 422, "validation_error"),
        (
            {"message": "hi", "thread_id": "00000000-0000-4000-8000-000000000000"},
            404,
            "thread_not_found",
        ),
        ({"message": "x" * 12_001}, 400, "validation_error"),
    ],
)
def test_stream_endpoint_rejects_before_streaming(
    payload: dict[str, Any], status: int, detail: str
) -> None:
    response = TestClient(app).post("/v1/agent/stream", json=payload)
    assert response.status_code == status
    assert response.json() == {"detail": detail}


def test_stream_endpoint_is_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api_main,
        "rate_limiter",
        InMemoryTokenBucketRateLimiter(capacity=1, requests_per_window=1, window_seconds=60),
    )
    client = TestClient(app)
    assert client.post("/v1/agent/stream", json={"message": "hi"}).status_code == 200
    limited = client.post("/v1/agent/stream", json={"message": "hi"})
    assert limited.status_code == 429
    assert limited.json() == {"detail": "rate_limited"}


def test_stream_endpoint_enforces_body_size_limit() -> None:
    oversized = api_main.settings.max_request_body_bytes + 1
    response = TestClient(app).post(
        "/v1/agent/stream", content=b"x" * oversized, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 413
