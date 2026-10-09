from __future__ import annotations

import structlog
import structlog.testing

from neuron_agent.observability.audit import audit
from neuron_agent.observability.logging import bind_correlation_context


def test_bind_correlation_context_propagates_request_thread_and_run_ids() -> None:
    structlog.contextvars.clear_contextvars()
    try:
        bind_correlation_context(request_id="request-1", thread_id="thread-1", run_id="run-1")
        with structlog.testing.capture_logs(
            processors=[structlog.contextvars.merge_contextvars]
        ) as logs:
            structlog.get_logger().info("tool_call_succeeded", tool_name="calculator")
    finally:
        structlog.contextvars.clear_contextvars()

    assert logs[0]["request_id"] == "request-1"
    assert logs[0]["thread_id"] == "thread-1"
    assert logs[0]["run_id"] == "run-1"
    assert logs[0]["tool_name"] == "calculator"


def test_bind_correlation_context_skips_unset_identifiers() -> None:
    structlog.contextvars.clear_contextvars()
    try:
        bind_correlation_context(request_id=None, thread_id="thread-1", run_id=None)
        with structlog.testing.capture_logs(
            processors=[structlog.contextvars.merge_contextvars]
        ) as logs:
            structlog.get_logger().info("evt")
    finally:
        structlog.contextvars.clear_contextvars()

    assert "request_id" not in logs[0]
    assert "run_id" not in logs[0]
    assert logs[0]["thread_id"] == "thread-1"


def test_audit_emits_fixed_schema_through_dedicated_logger() -> None:
    with structlog.testing.capture_logs() as logs:
        audit(
            "authorization_denied",
            outcome="denied",
            actor="0123456789ab",
            issuer_id="primary",
            action="threads:read",
            resource_type="thread",
            resource_id="00000000-0000-0000-0000-000000000001",
            reason="insufficient_scope",
        )

    assert len(logs) == 1
    assert logs[0]["event"] == "authorization_denied"
    assert logs[0]["audit"] is True
    assert logs[0]["outcome"] == "denied"
    assert logs[0]["actor"] == "0123456789ab"
    assert logs[0]["issuer_id"] == "primary"
    assert logs[0]["action"] == "threads:read"
    assert logs[0]["resource_type"] == "thread"
    assert logs[0]["resource_id"] == "00000000-0000-0000-0000-000000000001"
    assert logs[0]["reason"] == "insufficient_scope"
    assert "timestamp" in logs[0]
    assert "sub" not in logs[0]
