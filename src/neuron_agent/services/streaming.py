"""Streaming event contract and answer-token extraction (ADR 0005, decision 4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import AIMessageChunk
from langchain_core.utils.json import parse_partial_json

STREAM_PROTOCOL_VERSION = "1"

StreamEventType = Literal["run_started", "token", "tool_call", "final", "error", "done"]

# Tool name `create_agent` uses when structured output falls back to a tool call.
_STRUCTURED_OUTPUT_TOOL = "AgentAnswer"


@dataclass(frozen=True)
class StreamEvent:
    """One server-sent event: `event` is the SSE event name, `data` its JSON payload."""

    event: StreamEventType
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnswerTokenExtractor:
    """Turn streamed model chunks into user-facing answer deltas.

    The model returns `AgentAnswer` as JSON, so raw tokens look like `{"answer": "Hel`.
    For JSON output, the partial document is re-parsed on every chunk and only the growth of
    the `answer` field is emitted. Plain-text output is passed through unchanged. Deltas are
    a best-effort preview: the `final` event carries the validated answer.
    """

    _raw: dict[str, str] = field(default_factory=dict)
    _emitted: dict[str, str] = field(default_factory=dict)
    # Only the first chunk of a tool call carries its name; later chunks share its index.
    _tool_names: dict[tuple[str, int | None], str] = field(default_factory=dict)

    def feed(self, chunk: AIMessageChunk) -> str:
        """Return the new answer text contributed by `chunk` (possibly empty)."""
        key = chunk.id or ""
        text = chunk.content if isinstance(chunk.content, str) else ""
        for tool_chunk in chunk.tool_call_chunks:
            slot = (key, tool_chunk.get("index"))
            if name := tool_chunk.get("name"):
                self._tool_names[slot] = name
            if self._tool_names.get(slot) == _STRUCTURED_OUTPUT_TOOL:
                text += tool_chunk.get("args") or ""
        if not text:
            return ""
        raw = self._raw.get(key, "") + text
        self._raw[key] = raw
        if not raw.lstrip().startswith("{"):
            self._emitted[key] = raw
            return text
        try:
            parsed = parse_partial_json(raw)
        except ValueError:
            return ""
        answer = parsed.get("answer") if isinstance(parsed, dict) else None
        if not isinstance(answer, str):
            return ""
        emitted = self._emitted.get(key, "")
        if not answer.startswith(emitted):
            return ""
        self._emitted[key] = answer
        return answer[len(emitted) :]


def tool_call_names(chunk: AIMessageChunk) -> list[str]:
    """Names of real tool calls starting in `chunk`; never arguments, never structured output."""
    return [
        name
        for tool_chunk in chunk.tool_call_chunks
        if (name := tool_chunk.get("name")) and name != _STRUCTURED_OUTPUT_TOOL
    ]
