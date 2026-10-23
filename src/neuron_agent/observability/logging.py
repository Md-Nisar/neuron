# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Structured logging configuration."""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog
from opentelemetry import trace

_configured = False


def configure_logging(*, level: str, service: str, version: str, environment: str) -> None:
    """Configure JSON logs with stable service metadata, once per process.

    The API and the graph module (loaded alone by Agent Server) both call this; later calls
    are no-ops, so whichever loads first wins.
    """
    global _configured
    if _configured:
        return
    _configured = True
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            add_trace_context,
            structlog.processors.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_service_metadata(service=service, version=version, environment=environment),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def bind_correlation_context(
    *, request_id: str | None, thread_id: str | None, run_id: str | None = None
) -> None:
    """Attach request, thread, and run identifiers to the logging context for the active scope."""
    if request_id is not None:
        structlog.contextvars.bind_contextvars(request_id=request_id)
    if thread_id is not None:
        structlog.contextvars.bind_contextvars(thread_id=thread_id)
    if run_id is not None:
        structlog.contextvars.bind_contextvars(run_id=run_id)


def correlation_context() -> dict[str, Any]:
    """Return only correlation IDs for use by the dedicated audit emitter."""
    return structlog.contextvars.get_contextvars()


def add_trace_context(
    _: Any, __: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Add the current span's `trace_id` and `span_id`, when a valid span context is current."""
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event_dict["trace_id"] = trace.format_trace_id(context.trace_id)
        event_dict["span_id"] = trace.format_span_id(context.span_id)
    return event_dict


def _add_service_metadata(*, service: str, version: str, environment: str) -> Any:
    def processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        event_dict.setdefault("service", service)
        event_dict.setdefault("version", version)
        event_dict.setdefault("environment", environment)
        return event_dict

    return processor


def log_startup_configuration(settings: Any) -> None:
    """Log the effective limits once at start-up; values only, never a secret or DSN."""
    logger = structlog.get_logger("neuron_agent.config")
    logger.info(
        "effective_limits",
        limits_backend=settings.limits_backend,
        rate_limit_enabled=settings.rate_limit_enabled,
        rate_limit_requests_per_window=settings.rate_limit_requests_per_window,
        rate_limit_window_seconds=settings.rate_limit_window_seconds,
        rate_limit_burst=settings.rate_limit_burst,
        max_concurrent_streams=settings.max_concurrent_streams,
        max_concurrent_runs_per_user=settings.max_concurrent_runs_per_user,
        user_token_budget=settings.user_token_budget,
        user_token_budget_window_seconds=settings.user_token_budget_window_seconds,
        request_timeout_seconds=settings.request_timeout_seconds,
        tool_timeout_seconds=settings.tool_timeout_seconds,
        run_timeout_seconds=settings.run_timeout_seconds,
        shutdown_drain_seconds=settings.shutdown_drain_seconds,
    )
    if settings.env in {"staging", "production"} and settings.checkpointer == "none":
        logger.warning(
            "stateless_deployment", detail="APP_CHECKPOINTER=none: threads are not stored"
        )
    if settings.langsmith_content_approved:
        # The record names an approval (not a secret); this line is the trail for content capture.
        logger.warning(
            "langsmith_content_capture_approved",
            approval_record=settings.langsmith_content_approval_record,
        )
