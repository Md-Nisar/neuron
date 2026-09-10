from __future__ import annotations

import structlog

from neuron_agent.observability.logging import bind_correlation_context


def test_bind_correlation_context_binds_run_id() -> None:
    structlog.contextvars.clear_contextvars()
    bind_correlation_context(request_id="request-1", thread_id="thread-1", run_id="run-1")
    assert structlog.contextvars.get_contextvars()["run_id"] == "run-1"


def test_bind_correlation_context_omits_run_id_when_not_given() -> None:
    structlog.contextvars.clear_contextvars()
    bind_correlation_context(request_id="request-1", thread_id="thread-1")
    assert "run_id" not in structlog.contextvars.get_contextvars()
