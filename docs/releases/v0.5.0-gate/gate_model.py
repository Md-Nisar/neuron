"""The v0.5.0 telemetry gate's scripted chat model: one calculator call, then an answer.

`install()` replaces only `factory.create_chat_model`; everything else is production code.
With `GATE_LIVE=1` it does nothing, so the configured provider is used.

The tool expression and the answer marker come from the harness (`GATE_TOOL_EXPRESSION`,
`GATE_ANSWER_MARKER`) so it can scan telemetry for them afterwards.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool

from neuron_agent.models import factory

USAGE = {"input_tokens": 321, "output_tokens": 45, "total_tokens": 366}
METADATA = {"model_name": "gate-scripted-model"}


class GateToolModel(BaseChatModel):
    """Calls `calculator` when the last message is not a tool result; otherwise answers."""

    expression: str
    answer_marker: str

    @property
    def _llm_type(self) -> str:
        return "gate-scripted"

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        return self

    def _reply(self, messages: list[BaseMessage]) -> AIMessage:
        last = messages[-1] if messages else None
        if isinstance(last, ToolMessage):
            content = f"The product is {last.content}. {self.answer_marker}"
            return AIMessage(content=content, usage_metadata=USAGE, response_metadata=METADATA)
        call = {
            "name": "calculator",
            "args": {"expression": self.expression},
            "id": f"call_{uuid.uuid4().hex[:12]}",
            "type": "tool_call",
        }
        return AIMessage(
            content="", tool_calls=[call], usage_metadata=USAGE, response_metadata=METADATA
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._reply(messages))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        reply = self._reply(messages)
        message_id = f"run-{uuid.uuid4()}"
        chunks: list[AIMessageChunk] = []
        if reply.tool_calls:
            call = reply.tool_calls[0]
            chunks.append(
                AIMessageChunk(
                    content="",
                    id=message_id,
                    tool_call_chunks=[
                        {
                            "name": call["name"],
                            "args": json.dumps(call["args"]),
                            "id": call["id"],
                            "index": 0,
                            "type": "tool_call_chunk",
                        }
                    ],
                )
            )
        else:
            for word in str(reply.content).split(" "):
                chunks.append(AIMessageChunk(content=word + " ", id=message_id))
        chunks.append(
            AIMessageChunk(
                content="", id=message_id, usage_metadata=USAGE, response_metadata=METADATA
            )
        )
        for chunk in chunks:
            generation = ChatGenerationChunk(message=chunk)
            if run_manager:
                run_manager.on_llm_new_token(str(chunk.content), chunk=generation)
            yield generation


def install() -> None:
    """Replace the chat model unless this is a live run."""
    if os.environ.get("GATE_LIVE") == "1":
        return
    model = GateToolModel(
        expression=os.environ["GATE_TOOL_EXPRESSION"],
        answer_marker=os.environ["GATE_ANSWER_MARKER"],
    )
    factory.create_chat_model = lambda settings: model
