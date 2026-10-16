"""LangSmith governance (ADR 0007, decision 5).

`APP_ENABLE_LANGSMITH` is the only switch for LangSmith tracing, and outside development
prompts and answers stay out of traces unless `APP_LANGSMITH_CONTENT_APPROVED=true`.

This is the one place that writes environment variables. LangChain and LangSmith decide
whether to trace by reading `LANGSMITH_*`/`LANGCHAIN_*` variables themselves, and no
in-process switch covers all of them: `LANGCHAIN_TRACING` (the removed v1 tracer) makes
LangChain raise when tracing is off, and `get_env_var` caches lookups. So the app's
decision is written back over every alias and the caches are cleared. Application settings
are still read only in `config/settings.py`; the only variables read here are the shell's
own LangSmith switches, to report that they were overridden.
"""

from __future__ import annotations

import os
from typing import Any, cast

import structlog
from langsmith import run_trees
from langsmith import utils as ls_utils

from neuron_agent.config.settings import Settings

logger = structlog.get_logger(__name__)

# Aliases LangSmith/LangChain accept for the tracing switch; all are set together because
# the first one found wins and a stale one would otherwise contradict the app switch.
_TRACING_VARS = (
    "LANGSMITH_TRACING",
    "LANGSMITH_TRACING_V2",
    "LANGCHAIN_TRACING_V2",
    "LANGCHAIN_TRACING",
)
_HIDE_VARS = (
    "LANGSMITH_HIDE_INPUTS",
    "LANGSMITH_HIDE_OUTPUTS",
    "LANGCHAIN_HIDE_INPUTS",
    "LANGCHAIN_HIDE_OUTPUTS",
)
_TRUTHY = {"true", "1", "yes", "on"}


def configure_langsmith(settings: Settings) -> None:
    """Apply the app's LangSmith decision to the process; safe to call more than once.

    Called by the FastAPI app and by the graph module (which Agent Server loads alone).
    Agent Server's own platform tracing is not controlled here.
    """
    overridden = [
        name
        for name in _TRACING_VARS
        if not settings.enable_langsmith and os.environ.get(name, "").strip().lower() in _TRUTHY
    ]
    value = "true" if settings.enable_langsmith else "false"
    for name in _TRACING_VARS:
        # The v1 switch is never turned on: with it set, LangChain raises whenever v2
        # tracing is off for a run (for example under `tracing_context(enabled=False)`).
        os.environ[name] = "false" if name == "LANGCHAIN_TRACING" else value

    hide_content = settings.env != "development" and not settings.langsmith_content_approved
    if settings.env != "development":
        # Outside development the app decides; a shell value must not show content.
        for name in _HIDE_VARS:
            os.environ[name] = "true" if hide_content else "false"

    # Drop cached lookups and any client built before this ran, so both see the new values.
    cast(Any, ls_utils.get_env_var).cache_clear()
    run_trees.configure(client=None)

    if overridden:
        logger.warning("langsmith_tracing_overridden", variables=overridden)
    if settings.enable_langsmith:
        logger.info(
            "langsmith_tracing_enabled",
            environment=settings.env,
            content_hidden=hide_content,
        )
