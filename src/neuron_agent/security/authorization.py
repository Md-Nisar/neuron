"""Permission mapping and per-run authorization context."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from neuron_agent.errors.base import AuthorizationError

if TYPE_CHECKING:
    from neuron_agent.security.auth import Principal

DEV_PERMISSIONS = frozenset({"agent:invoke", "threads:read", "threads:delete", "tools:calculator"})


@dataclass(frozen=True)
class AuthorizationContext:
    """Trusted authorization inputs passed as runtime context, never graph state/prompt."""

    permissions: frozenset[str]
    principal: Principal | None = None
    usage: TokenUsageAccumulator | None = None
    actor: str | None = None
    issuer_id: str | None = None


@dataclass
class TokenUsageAccumulator:
    """Per-run provider-token usage collected from model response metadata."""

    total_tokens: int = 0

    def record(self, usage: object) -> None:
        if not isinstance(usage, dict):
            return
        total = usage.get("total_tokens")
        if not isinstance(total, int) or isinstance(total, bool):
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            total = (input_tokens if isinstance(input_tokens, int) else 0) + (
                output_tokens if isinstance(output_tokens, int) else 0
            )
        if total > 0:
            self.total_tokens += total


def require_permission(permission: str, permissions: frozenset[str]) -> None:
    """Raise the stable authorization error unless the permission is explicitly granted."""
    if permission not in permissions:
        raise AuthorizationError("permission denied")
