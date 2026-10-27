# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Pinning of MCP tool definitions (ADR 0009, decision 5).

A tool's description and input schema are text the model reads, so a server that changes them
after review can steer the agent (a "rug pull"). The operator pins each exposed tool to a
SHA-256 of its name, description and input schema; a tool that no longer matches is not
registered. Annotations such as `readOnlyHint` are not part of the pin and never authorize.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

PIN_PREFIX = "sha256:"
ProblemKind = Literal["changed", "unlisted", "missing"]


@dataclass(frozen=True)
class FetchedTool:
    """A tool definition as a server reported it."""

    name: str
    description: str | None
    input_schema: Mapping[str, Any]


@dataclass(frozen=True)
class PinProblem:
    """A tool that will not be registered, and why. Carries a name, never server text."""

    tool: str
    kind: ProblemKind


@dataclass(frozen=True)
class PinResult:
    accepted: tuple[str, ...]
    problems: tuple[PinProblem, ...]


def tool_pin(tool: FetchedTool) -> str:
    """The pin for a definition: `sha256:` and the hex digest of its canonical JSON."""
    canonical = json.dumps(
        {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.input_schema,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return PIN_PREFIX + hashlib.sha256(canonical.encode("ascii")).hexdigest()


def check_pins(pins: Mapping[str, str], fetched: Iterable[FetchedTool]) -> PinResult:
    """Compare a server's tool list with the operator's pins (tool name to pin).

    Only a listed tool whose definition matches its pin is accepted. A listed tool whose
    definition differs is `changed`, a reported tool that is not listed is `unlisted`, and a
    listed tool the server no longer reports is `missing`. Each tool is judged alone.
    """
    accepted: list[str] = []
    problems: list[PinProblem] = []
    seen: set[str] = set()
    for tool in fetched:
        if tool.name in seen:
            # Two tools with one name cannot both be what was pinned.
            problems.append(PinProblem(tool.name, "changed"))
            accepted = [name for name in accepted if name != tool.name]
            continue
        seen.add(tool.name)
        if tool.name not in pins:
            problems.append(PinProblem(tool.name, "unlisted"))
        elif tool_pin(tool) != pins[tool.name]:
            problems.append(PinProblem(tool.name, "changed"))
        else:
            accepted.append(tool.name)
    problems.extend(PinProblem(name, "missing") for name in pins if name not in seen)
    flagged = {p.tool for p in problems}
    return PinResult(
        accepted=tuple(name for name in accepted if name not in flagged),
        problems=tuple(problems),
    )
