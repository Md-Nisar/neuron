# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The one list of tools the agent may use (ADR 0009, decision 4).

Every tool has exactly one `ToolSpec`: its scope, risk class and source. The allow-list, the
scope checks, the span and audit names and (once approvals exist) the approval configuration
all read this registry, so a tool without a spec cannot be offered to the model or run.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.tools import BaseTool

from neuron_agent.security.input_policy import HIGH_RISK_TOOL_NAMES
from neuron_agent.tools.calculator import calculator
from neuron_agent.tools.time import utc_now

Risk = Literal["read", "mutating"]
Source = Literal["builtin", "mcp"]

_SCOPE = re.compile(r"tools:[a-z0-9_.-]+")


@dataclass(frozen=True)
class ToolSpec:
    """A tool and the policy that applies to it.

    `scope` is the permission a caller needs; None means every caller who may invoke the agent
    (a public, read-only builtin). `risk` is `mutating` for anything that changes state outside
    the run; those tools need human approval (ADR 0009, decision 6).
    """

    tool: BaseTool
    scope: str | None
    risk: Risk = "read"
    source: Source = "builtin"
    # For a `mutating` tool: return False for a call the tool will refuse by itself, so the user
    # is not asked to approve something that cannot happen. True (or None) asks as usual.
    approval_when: Callable[[Any], bool] | None = None
    # The tool returns untrusted or private data (MCP output, the user's notes). Once a run has
    # read such a result, a call that sends data out (any MCP tool) needs a human.
    taints_run: bool = False

    def __post_init__(self) -> None:
        if self.name in HIGH_RISK_TOOL_NAMES:
            raise ValueError(f"tool name is on the high-impact deny-list: {self.name}")
        if self.scope is not None and not _SCOPE.fullmatch(self.scope):
            raise ValueError(f"tool scope must look like 'tools:<name>': {self.scope}")
        if self.scope is None and (self.source != "builtin" or self.risk != "read"):
            raise ValueError(f"only a read-only builtin tool may be public: {self.name}")

    @property
    def name(self) -> str:
        return self.tool.name


class ToolRegistry:
    """An immutable set of `ToolSpec`s, unique by tool name.

    `can_pause` is False where a run cannot wait for a human (no saved state): there a call
    that would need approval after untrusted data is refused instead.
    """

    def __init__(self, specs: Iterable[ToolSpec], *, can_pause: bool = True) -> None:
        by_name: dict[str, ToolSpec] = {}
        for spec in specs:
            if spec.name in by_name:
                raise ValueError(f"duplicate tool name: {spec.name}")
            by_name[spec.name] = spec
        self._specs = by_name
        self.can_pause = can_pause

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(self._specs.values())

    def spec(self, name: str) -> ToolSpec | None:
        """The spec for `name`, or None: a name the model chose is not a registered tool."""
        return self._specs.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._specs)

    def tools(self) -> list[BaseTool]:
        return [spec.tool for spec in self._specs.values()]

    def mutating(self) -> list[ToolSpec]:
        return [spec for spec in self._specs.values() if spec.risk == "mutating"]

    def gated_after_taint(self) -> list[ToolSpec]:
        """Read tools that need approval once the run has read untrusted or private data."""
        return [s for s in self._specs.values() if s.source == "mcp" and s.risk == "read"]

    def gated(self) -> list[ToolSpec]:
        """Every tool a run may pause on: the `mutating` ones, and the rest that can need it."""
        return [*self.mutating(), *self.gated_after_taint()] if self.can_pause else []

    def tainting(self) -> frozenset[str]:
        """Names of the tools whose results taint a run (see `ToolSpec.taints_run`)."""
        return frozenset(spec.name for spec in self._specs.values() if spec.taints_run)

    def without_mutating(self) -> ToolRegistry:
        """The same registry without the tools that need approval (no run can pause)."""
        return ToolRegistry(
            (spec for spec in self._specs.values() if spec.risk != "mutating"), can_pause=False
        )

    def scope_for(self, name: str) -> str | None:
        spec = self._specs.get(name)
        return spec.scope if spec else None

    def visible_to(self, permissions: frozenset[str]) -> list[str]:
        """Names of the tools a caller holding `permissions` may be offered and may run."""
        return [
            spec.name
            for spec in self._specs.values()
            if spec.scope is None or spec.scope in permissions
        ]


def builtin_registry() -> ToolRegistry:
    """The tools that ship with the service."""
    return ToolRegistry(
        [ToolSpec(utc_now, scope=None), ToolSpec(calculator, scope="tools:calculator")]
    )
