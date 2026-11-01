# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Streaming event contract and answer-token extraction (ADR 0005, decision 4)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from langchain_core.messages import AIMessageChunk

STREAM_PROTOCOL_VERSION = "1"

StreamEventType = Literal[
    "run_started", "token", "tool_call", "final", "approval_required", "error", "done"
]

# Tool name `create_agent` uses when structured output falls back to a tool call.
_STRUCTURED_OUTPUT_TOOL = "AgentAnswer"

# Where the `answer` string starts. Inside a JSON string every quote is escaped, so this
# matches only a key. `AgentAnswer` is flat, so no nested object has an `answer` key.
_ANSWER_START = re.compile(r'"answer"\s*:\s*"')
# A trailing high surrogate escape: its low half has not arrived yet.
_HIGH_SURROGATE = re.compile(r"\\u[dD][89abAB][0-9a-fA-F]{2}$")
_DONE = -1


def _string_end(body: str, start: int) -> tuple[int, bool]:
    """Scan a JSON string body from `start`: the end of the complete part, and if it closed."""
    i = start
    while i < len(body):
        char = body[i]
        if char == '"':
            return i, True
        if char == "\\":
            step = 6 if body[i + 1 : i + 2] == "u" else 2
            if i + step > len(body):
                break  # an escape still arriving
            i += step
        else:
            i += 1
    return i, False


@dataclass(frozen=True)
class StreamEvent:
    """One server-sent event: `event` is the SSE event name, `data` its JSON payload."""

    event: StreamEventType
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnswerTokenExtractor:
    """Turn streamed model chunks into user-facing answer deltas.

    The model returns `AgentAnswer` as JSON, so raw tokens look like `{"answer": "Hel`.
    For JSON output, only the `answer` string is decoded, and only from where the last chunk
    stopped, so the work per chunk does not grow with the document; it stops once the string
    closes or turns out malformed. Plain-text output is passed through unchanged. Deltas are
    a best-effort preview: the `final` event carries the validated answer.
    """

    _raw: dict[str, str] = field(default_factory=dict)
    _emitted: dict[str, str] = field(default_factory=dict)
    # Per message: where decoding of the `answer` string resumes, or _DONE.
    _cursor: dict[str, int] = field(default_factory=dict)
    # Only the first chunk of a tool call carries its name; later chunks share its index.
    _tool_names: dict[tuple[str, int | None], str] = field(default_factory=dict)
    _active_anon_id: str | None = None
    _anon_counter: int = 0

    def feed(self, chunk: AIMessageChunk) -> str:
        """Return the new answer text contributed by `chunk` (possibly empty)."""
        if chunk.id:
            key = chunk.id
        else:
            if self._active_anon_id is None or self._cursor.get(self._active_anon_id) == _DONE:
                self._anon_counter += 1
                self._active_anon_id = f"__anon_{self._anon_counter}"
            key = self._active_anon_id
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
        body = raw.lstrip()
        if body.startswith("```"):
            # Some models wrap the JSON in a Markdown fence; hold output until it opens.
            start = body.find("{")
            if start == -1:
                return ""
            body = body[start:]
        elif not body or body in ("`", "``"):
            return ""  # whitespace or a fence still arriving: the next characters decide
        elif not body.startswith("{"):
            delta = raw[len(self._emitted.get(key, "")) :]
            self._emitted[key] = raw
            return delta
        cursor = self._cursor.get(key)
        if cursor is None:
            match = _ANSWER_START.search(body)
            if match is None:
                return ""
            cursor = match.end()
        if cursor == _DONE:
            return ""
        end, closed = _string_end(body, cursor)
        if not closed and _HIGH_SURROGATE.search(body, cursor, end):
            end -= 6
        try:
            delta = str(json.loads(f'"{body[cursor:end]}"', strict=False))
        except ValueError:
            self._cursor[key] = _DONE  # malformed: the final event still carries the answer
            return ""
        self._cursor[key] = _DONE if closed else end
        return delta


def tool_call_names(chunk: AIMessageChunk) -> list[str]:
    """Names of real tool calls starting in `chunk`; never arguments, never structured output."""
    return [
        name
        for tool_chunk in chunk.tool_call_chunks
        if (name := tool_chunk.get("name")) and name != _STRUCTURED_OUTPUT_TOOL
    ]
