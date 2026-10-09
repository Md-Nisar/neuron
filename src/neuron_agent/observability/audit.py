"""Privacy-safe security audit events on a separately routable logger."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import structlog

from neuron_agent.observability.logging import correlation_context

Outcome = Literal["allowed", "denied", "error"]

_logger = structlog.get_logger("neuron_agent.audit")


def audit(
    event: str,
    *,
    outcome: Outcome,
    actor: str | None = None,
    issuer_id: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    request_id: str | None = None,
    run_id: str | None = None,
    reason: str | None = None,
    count: int | None = None,
) -> None:
    """Emit exactly the audit schema; callers must pass only allowlisted identifiers/codes."""
    context = correlation_context()
    _logger.bind(
        audit=True,
        outcome=outcome,
        actor=actor,
        issuer_id=issuer_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id or context.get("request_id"),
        run_id=run_id or context.get("run_id"),
        reason=reason,
        count=count,
        timestamp=datetime.now(UTC).isoformat(),
    ).info(event)
