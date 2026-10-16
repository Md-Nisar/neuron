"""Permission mapping and per-run authorization context."""

from __future__ import annotations

from dataclasses import dataclass, field
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


UNKNOWN_MODEL = "unknown"


def _count(source: object, key: str) -> int:
    value = source.get(key) if isinstance(source, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


@dataclass
class TokenCounts:
    """Provider-reported tokens by kind. Input includes cache-read, output includes reasoning."""

    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    reasoning_tokens: int = 0


@dataclass
class TokenUsageAccumulator:
    """Per-run provider-token usage collected from model response metadata.

    Budgets charge `total_tokens`; the per-kind split, by model id, is for the usage log.
    A kind the provider doesn't report stays 0, and a total-only provider still budgets.
    """

    total_tokens: int = 0
    by_model: dict[str, TokenCounts] = field(default_factory=dict)

    def record(self, usage: object, model: str | None = None) -> None:
        if not isinstance(usage, dict):
            return
        input_tokens = _count(usage, "input_tokens")
        output_tokens = _count(usage, "output_tokens")
        total = _count(usage, "total_tokens") or input_tokens + output_tokens
        counts = TokenCounts(
            total_tokens=total,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=_count(usage.get("input_token_details"), "cache_read"),
            reasoning_tokens=_count(usage.get("output_token_details"), "reasoning"),
        )
        if not any(vars(counts).values()):
            return
        self.total_tokens += total
        per_model = self.by_model.setdefault(model or UNKNOWN_MODEL, TokenCounts())
        for name, value in vars(counts).items():
            setattr(per_model, name, getattr(per_model, name) + value)

    def totals(self) -> TokenCounts:
        """The counts summed over all models."""
        summed = TokenCounts()
        for counts in self.by_model.values():
            for name, value in vars(counts).items():
                setattr(summed, name, getattr(summed, name) + value)
        return summed


def require_permission(permission: str, permissions: frozenset[str]) -> None:
    """Raise the stable authorization error unless the permission is explicitly granted."""
    if permission not in permissions:
        raise AuthorizationError("permission denied")
