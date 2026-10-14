from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Callable, Iterator, Sequence
from typing import Any

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.messages.tool import tool_call_chunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

# Must run before importing neuron_agent: settings and the exported graph build at import.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_DEFAULT_MODEL", "openai:gpt-5.4-mini")
# Developer shells may export provider credentials. Unit tests must never turn
# those credentials into live LLM calls through default Settings construction.
os.environ.pop("APP_OPENAI_API_KEY", None)
os.environ.pop("OPENAI_API_KEY", None)

from neuron_agent.api import main as api_main  # noqa: E402
from neuron_agent.graphs import main_graph  # noqa: E402
from neuron_agent.models import factory  # noqa: E402
from neuron_agent.schemas.agent import AgentAnswer  # noqa: E402
from neuron_agent.security.rate_limiter import InMemoryTokenBucketRateLimiter  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_rate_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test its own API rate limiter so request counts don't leak across tests."""
    settings = api_main.settings
    monkeypatch.setattr(
        api_main,
        "rate_limiter",
        InMemoryTokenBucketRateLimiter(
            capacity=settings.rate_limit_burst,
            requests_per_window=settings.rate_limit_requests_per_window,
            window_seconds=settings.rate_limit_window_seconds,
        ),
    )


class HistoryEchoAgent:
    """Deterministic agent: answers with every user turn it was given, oldest first.

    It also returns an intermediate tool-call/tool-result pair, the way `create_agent` does,
    so tests can assert that those internal messages are not persisted to the thread.
    """

    def __init__(self) -> None:
        self.calls: list[list[BaseMessage]] = []
        self.fail_next = False

    async def ainvoke(
        self, inputs: dict[str, Any], *, config: dict[str, Any], context: Any = None
    ) -> dict[str, Any]:
        messages = list(inputs["messages"])
        self.calls.append(messages)
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("agent failed")
        answer = " | ".join(str(m.content) for m in messages if isinstance(m, HumanMessage))
        tool_call = {"name": "calculator", "args": {"expression": "1+1"}, "id": "call-1"}
        return {
            "messages": [
                *messages,
                AIMessage(content="", tool_calls=[tool_call]),
                ToolMessage(content="2", tool_call_id="call-1"),
                AIMessage(content=answer),
            ],
            "structured_response": AgentAnswer(answer=answer, used_tools=[], confidence=1.0),
        }


@pytest.fixture
def echo_agent(monkeypatch: pytest.MonkeyPatch) -> HistoryEchoAgent:
    """Make every graph built during the test use a `HistoryEchoAgent`."""
    agent = HistoryEchoAgent()
    monkeypatch.setattr(main_graph, "build_agent", lambda settings: agent)
    return agent


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


@pytest.fixture
def stream_replies(monkeypatch: pytest.MonkeyPatch) -> Callable[..., StreamingFakeModel]:
    """Make the chat model a `StreamingFakeModel` that replies with the given messages."""

    def use(*replies: AIMessage) -> StreamingFakeModel:
        model = StreamingFakeModel(messages=iter(replies))
        monkeypatch.setattr(factory, "create_chat_model", lambda settings: model)
        return model

    return use
