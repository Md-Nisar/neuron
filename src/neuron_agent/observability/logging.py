"""Structured logging configuration."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(*, level: str, service: str, version: str, environment: str) -> None:
    """Configure JSON logs with stable service metadata."""
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_service_metadata(service=service, version=version, environment=environment),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
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


def _add_service_metadata(*, service: str, version: str, environment: str) -> Any:
    def processor(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        event_dict.setdefault("service", service)
        event_dict.setdefault("version", version)
        event_dict.setdefault("environment", environment)
        return event_dict

    return processor
