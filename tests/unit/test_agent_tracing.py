"""Agent spans (ADR 0007 decision 1, #90): span tree, attributes and privacy."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import httpx
import openai
import pytest
import structlog.testing
from fastapi.testclient import TestClient
from langchain.agents.middleware import ModelRetryMiddleware
from langchain_core.messages import AIMessage, HumanMessage
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode
from tests.conftest import JwtApi, StreamingFakeModel, bearer

from neuron_agent.api import main as api_main
from neuron_agent.api.main import app
from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import AgentExecutionError
from neuron_agent.graphs.main_graph import build_graph
from neuron_agent.models import factory
from neuron_agent.observability import semconv, telemetry
from neuron_agent.services.agent_service import AgentService

_PROMPT = "private-prompt-text"
_ANSWER = "private-answer-text"
_EXPRESSION = "987654321*3"
_TOOL_RESULT = "2962962963"
_SUB = "raw-subject-7f3a"
_INVOKE = f"{semconv.OPERATION_INVOKE_AGENT} {semconv.AGENT_NAME}"
_CHAT = f"{semconv.OPERATION_CHAT} gpt-5.4-mini"
_TOOL = f"{semconv.OPERATION_EXECUTE_TOOL} calculator"


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    """Send HTTP and agent spans to an in-memory exporter for this test."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "tracer", lambda: provider.get_tracer(__name__))
    FastAPIInstrumentor.uninstrument_app(app)
    telemetry.instrument_app(app, tracer_provider=provider)
    # Instrumenting patches how the stack is built; a built stack would keep the old one.
    app.middleware_stack = None
    yield exporter
    FastAPIInstrumentor.uninstrument_app(app)
    telemetry.instrument_app(app)
    app.middleware_stack = None


def _tool_then_answer() -> tuple[AIMessage, AIMessage]:
    call = {"name": "calculator", "args": {"expression": _EXPRESSION}, "id": "call-1"}
    return AIMessage(content="", tool_calls=[call]), AIMessage(content=_ANSWER)


def _named(finished: tuple[ReadableSpan, ...], name: str) -> list[ReadableSpan]:
    return [span for span in finished if span.name == name]


def _parent_id(span: ReadableSpan) -> int | None:
    return span.parent.span_id if span.parent is not None else None


def _span_id(span: ReadableSpan) -> int:
    assert span.context is not None
    return span.context.span_id


def _attributes(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


def test_invoke_traces_run_model_and_tool_calls_under_the_request(
    spans: InMemorySpanExporter,
    stream_replies: Callable[..., Any],
    jwt_api_factory: Callable[..., JwtApi],
    make_token: Callable[..., str],
) -> None:
    stream_replies(*_tool_then_answer())
    api = jwt_api_factory()

    response = api.client.post(
        "/v1/agent/invoke", json={"message": _PROMPT}, headers=bearer(make_token(_SUB))
    )

    assert response.status_code == 200
    assert response.json()["used_tools"] == ["calculator"]
    finished = spans.get_finished_spans()
    [server] = [span for span in finished if span.kind is SpanKind.SERVER]
    [run] = _named(finished, _INVOKE)
    chats = _named(finished, _CHAT)
    [tool] = _named(finished, _TOOL)
    assert len(chats) == 2
    assert {span.context.trace_id for span in finished if span.context} == {
        server.context.trace_id if server.context else None
    }
    assert _parent_id(run) == _span_id(server)
    assert {_parent_id(span) for span in [*chats, tool]} == {_span_id(run)}

    run_attributes = _attributes(run)
    assert run_attributes[semconv.GEN_AI_CONVERSATION_ID] == response.json()["thread_id"]
    assert run_attributes[semconv.NEURON_RUN_ID]
    assert len(run_attributes[semconv.NEURON_OWNER_KEY_PREFIX]) == 12
    assert run_attributes[semconv.NEURON_TURN] == 1
    assert run.status.status_code is StatusCode.UNSET
    for chat in chats:
        assert chat.kind is SpanKind.CLIENT
        assert _attributes(chat) | {
            semconv.GEN_AI_OPERATION_NAME: "chat",
            semconv.GEN_AI_PROVIDER_NAME: "openai",
            semconv.GEN_AI_REQUEST_MODEL: "gpt-5.4-mini",
            semconv.NEURON_RETRY_COUNT: 0,
        } == _attributes(chat)
    assert _attributes(tool)[semconv.GEN_AI_TOOL_NAME] == "calculator"
    assert _attributes(tool)[semconv.NEURON_OUTCOME] == "success"


def test_denied_tool_call_is_span_status_not_content(
    spans: InMemorySpanExporter,
    stream_replies: Callable[..., Any],
    jwt_api_factory: Callable[..., JwtApi],
    make_token: Callable[..., str],
) -> None:
    stream_replies(*_tool_then_answer())
    api = jwt_api_factory()
    token = make_token(_SUB, scopes="agent:invoke")

    response = api.client.post("/v1/agent/invoke", json={"message": _PROMPT}, headers=bearer(token))

    assert response.status_code == 403
    finished = spans.get_finished_spans()
    [tool] = _named(finished, _TOOL)
    [run] = _named(finished, _INVOKE)
    assert _attributes(tool)[semconv.NEURON_OUTCOME] == "denied"
    for span in (tool, run):
        assert span.status.status_code is StatusCode.ERROR
        assert span.status.description is None
        assert _attributes(span)[semconv.ERROR_TYPE] == "authorization_error"
        assert not span.events


def test_no_span_carries_content_or_identity(
    spans: InMemorySpanExporter,
    stream_replies: Callable[..., Any],
    jwt_api_factory: Callable[..., JwtApi],
    make_token: Callable[..., str],
) -> None:
    """Prompt, answer, tool arguments and result, the token and `sub` never reach a span."""
    stream_replies(*_tool_then_answer(), *_tool_then_answer(), *_tool_then_answer())
    api = jwt_api_factory()
    allowed = make_token(_SUB)
    denied = make_token(_SUB, scopes="agent:invoke")

    api.client.post("/v1/agent/invoke", json={"message": _PROMPT}, headers=bearer(allowed))
    api.client.post("/v1/agent/invoke", json={"message": _PROMPT}, headers=bearer(denied))
    with api.client.stream(
        "POST", "/v1/agent/stream", json={"message": _PROMPT}, headers=bearer(allowed)
    ) as stream:
        body = "".join(stream.iter_text())

    assert _ANSWER in body
    finished = spans.get_finished_spans()
    assert {span.name for span in finished} >= {_INVOKE, _CHAT, _TOOL, semconv.STREAM_SPAN}
    recorded = repr(
        [
            (
                span.name,
                span.attributes,
                span.status.description,
                [(event.name, event.attributes) for event in span.events],
                [link.attributes for link in span.links],
            )
            for span in finished
        ]
    )
    for secret in (_PROMPT, _ANSWER, _EXPRESSION, _TOOL_RESULT, _SUB, allowed, denied):
        assert secret not in recorded


def test_stream_span_records_ttft_events_and_termination(
    spans: InMemorySpanExporter,
    stream_replies: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream_replies(AIMessage(content=_ANSWER))
    monkeypatch.setattr(api_main, "service", AgentService(Settings(env="test")))

    with TestClient(app).stream("POST", "/v1/agent/stream", json={"message": "hi"}) as stream:
        events = [line for line in stream.iter_lines() if line.startswith("event:")]

    finished = spans.get_finished_spans()
    [server] = [span for span in finished if span.kind is SpanKind.SERVER]
    [stream_span] = _named(finished, semconv.STREAM_SPAN)
    [run] = _named(finished, _INVOKE)
    assert _parent_id(stream_span) == _span_id(server)
    assert _parent_id(run) == _span_id(stream_span)
    attributes = _attributes(stream_span)
    assert attributes[semconv.NEURON_STREAM_TERMINATION] == "completed"
    assert attributes[semconv.NEURON_STREAM_EVENTS] == len(events)
    assert attributes[semconv.NEURON_STREAM_TTFT_MS] >= 0
    assert stream_span.status.status_code is StatusCode.UNSET


@pytest.mark.anyio
async def test_agent_server_run_records_ids_owner_prefix_and_token_usage(
    spans: InMemorySpanExporter, stream_replies: Callable[..., Any]
) -> None:
    """On Agent Server, IDs and owner come from the run's config, never the client's input."""
    usage = {
        "input_tokens": 120,
        "output_tokens": 30,
        "total_tokens": 150,
        "input_token_details": {"cache_read": 100},
        "output_token_details": {"reasoning": 12},
    }
    stream_replies(
        AIMessage(
            content="ok", usage_metadata=usage, response_metadata={"model_name": "gpt-5.4-mini-x"}
        )
    )
    graph = build_graph(Settings(env="test"))
    owner = "0123456789abcdef" * 4

    # Agent Server input is the client's: state fields must not reach the span.
    await graph.ainvoke(
        {
            "messages": [HumanMessage(content="hi")],
            "owner_key": "spoofed-owner-key",
            "thread_id": "spoofed-thread",
            "run_id": "00000000-0000-4000-8000-000000000000",
        },
        config={
            "configurable": {
                "thread_id": "thread-1",
                "run_id": "run-1",
                "langgraph_auth_user_id": owner,
            }
        },
    )

    finished = spans.get_finished_spans()
    [run] = _named(finished, _INVOKE)
    [chat] = _named(finished, _CHAT)
    assert _attributes(run) == {
        semconv.GEN_AI_OPERATION_NAME: "invoke_agent",
        semconv.GEN_AI_AGENT_NAME: "neuron",
        semconv.GEN_AI_CONVERSATION_ID: "thread-1",
        semconv.NEURON_RUN_ID: "run-1",
        semconv.NEURON_OWNER_KEY_PREFIX: owner[:12],
        semconv.NEURON_TURN: 1,
    }
    chat_attributes = _attributes(chat)
    assert chat_attributes[semconv.GEN_AI_RESPONSE_MODEL] == "gpt-5.4-mini-x"
    assert chat_attributes[semconv.GEN_AI_USAGE_INPUT_TOKENS] == 120
    assert chat_attributes[semconv.GEN_AI_USAGE_OUTPUT_TOKENS] == 30
    assert chat_attributes[semconv.GEN_AI_USAGE_CACHE_READ_INPUT_TOKENS] == 100
    assert chat_attributes[semconv.GEN_AI_USAGE_REASONING_OUTPUT_TOKENS] == 12


class _FailingModel(StreamingFakeModel):
    """Raises an unclassified error whose message is private content."""

    calls: int = 0

    def _generate(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        raise RuntimeError(_PROMPT)


@pytest.mark.anyio
async def test_failed_model_call_marks_chat_and_run_spans_with_the_error_code(
    spans: InMemorySpanExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = _FailingModel(messages=iter([]))
    monkeypatch.setattr(factory, "create_chat_model", lambda settings: model)
    graph = build_graph(Settings(env="test"))

    with pytest.raises(AgentExecutionError):
        await graph.ainvoke({"messages": [HumanMessage(content="hi")]})

    finished = spans.get_finished_spans()
    [chat] = _named(finished, _CHAT)
    [run] = _named(finished, _INVOKE)
    assert model.calls == 1
    assert _attributes(chat)[semconv.NEURON_RETRY_COUNT] == 0
    for span in (chat, run):
        assert span.status.status_code is StatusCode.ERROR
        assert span.status.description is None
        assert _attributes(span)[semconv.ERROR_TYPE] == AgentExecutionError.context.code
        assert not span.events


class _FlakyModel(StreamingFakeModel):
    """Fails its first call with a retryable connection error, then answers."""

    calls: int = 0

    def _generate(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        if self.calls == 1:
            raise openai.APIConnectionError(request=httpx.Request("POST", "https://x.test"))
        return super()._generate(*args, **kwargs)


@pytest.mark.anyio
async def test_chat_span_covers_retries_and_counts_them(
    spans: InMemorySpanExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = _FlakyModel(messages=iter([AIMessage(content="ok")]))
    monkeypatch.setattr(factory, "create_chat_model", lambda settings: model)
    monkeypatch.setattr(
        factory,
        "provider_retry_middleware",
        lambda settings: ModelRetryMiddleware(
            max_retries=2, retry_on=factory._is_retryable_provider_error, initial_delay=0
        ),
    )
    graph = build_graph(Settings(env="test"))

    with structlog.testing.capture_logs() as logs:
        await graph.ainvoke({"messages": [HumanMessage(content="hi")]})

    [chat] = _named(spans.get_finished_spans(), _CHAT)
    [completed] = [log for log in logs if log["event"] == "agent_execution_completed"]
    assert completed["retry_count"] == 1
    assert model.calls == 2
    assert _attributes(chat)[semconv.NEURON_RETRY_COUNT] == 1
    assert chat.status.status_code is StatusCode.UNSET
