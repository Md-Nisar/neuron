# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Parse the API's server-sent events and summarise one streamed run.

Pure functions over lines of text, so recorded streams can test them without a server.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Event:
    name: str
    data: dict[str, Any]
    at: float  # when the event was parsed, in the caller's clock


def parse_events(lines: Iterable[str], clock: Any) -> Iterator[Event]:
    """Yield an `Event` for every complete `event:`/`data:` block; comments are skipped."""
    name = "message"
    data: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r\n")
        if line == "":
            if data:
                text = "\n".join(data)
                try:
                    payload = json.loads(text)
                except ValueError:
                    payload = {}
                yield Event(name, payload if isinstance(payload, dict) else {}, clock())
            name, data = "message", []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))


@dataclass(frozen=True)
class RunResult:
    """What one streamed run looked like to the client."""

    outcome: str  # completed, approval_required, error, or incomplete
    error_code: str | None
    ttft_seconds: float | None
    duration_seconds: float
    tokens: int
    thread_id: str | None
    approval_id: str | None


def summarise(events: Iterable[Event], started: float, finished: float) -> RunResult:
    """Fold a run's events into a `RunResult` (`finished` is when the stream closed)."""
    outcome, error_code = "incomplete", None
    ttft: float | None = None
    tokens = 0
    thread_id = approval_id = None
    for event in events:
        thread_id = event.data.get("thread_id", thread_id)
        if event.name == "token":
            tokens += 1
            if ttft is None:
                ttft = event.at - started
        elif event.name == "final":
            outcome = "completed"
        elif event.name == "approval_required":
            outcome = "approval_required"
            approval = event.data.get("approval")
            if isinstance(approval, dict):
                approval_id = approval.get("approval_id")
        elif event.name == "error":
            outcome, error_code = "error", str(event.data.get("code", "unknown"))
    return RunResult(outcome, error_code, ttft, finished - started, tokens, thread_id, approval_id)
