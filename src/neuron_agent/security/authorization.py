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


def require_permission(permission: str, permissions: frozenset[str]) -> None:
    """Raise the stable authorization error unless the permission is explicitly granted."""
    if permission not in permissions:
        raise AuthorizationError("permission denied")
