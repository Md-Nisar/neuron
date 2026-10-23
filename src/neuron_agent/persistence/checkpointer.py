# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Checkpointer construction and lifecycle, selected by `APP_CHECKPOINTER` (ADR 0005)."""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import psycopg
import structlog
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from neuron_agent.config.settings import Settings
from neuron_agent.observability import metrics
from neuron_agent.persistence import migrations

logger = structlog.get_logger(__name__)

# Types stored in graph state that the checkpoint serializer may rebuild on load.
_ALLOWED_MSGPACK_MODULES = [("neuron_agent.schemas.agent", "AgentAnswer")]

# Checkpointer operations that are timed, and the latency above which one is logged.
_INSTRUMENTED_OPERATIONS = ("aget_tuple", "aput", "aput_writes", "adelete_thread")
SLOW_CHECKPOINT_MS = 250.0


def instrument_checkpointer(
    checkpointer: BaseCheckpointSaver[Any], backend: str
) -> BaseCheckpointSaver[Any]:
    """Time the saver's async read/write operations and log slow or failed ones.

    Methods are wrapped on the instance, so the object remains the original saver class
    (LangGraph type checks still hold) and every other method stays untouched. Logs carry
    the operation, backend, duration and error type: never keys, values or the DSN.
    """
    for operation in _INSTRUMENTED_OPERATIONS:
        original = getattr(checkpointer, operation)
        setattr(checkpointer, operation, _timed(original, operation, backend))
    return checkpointer


def _timed(
    func: Callable[..., Awaitable[Any]], operation: str, backend: str
) -> Callable[..., Awaitable[Any]]:
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        started = time.monotonic()
        try:
            result = await func(*args, **kwargs)
        except Exception as exc:
            metrics.record_checkpoint(
                time.monotonic() - started, outcome="error", error_type=type(exc).__name__
            )
            logger.warning(
                "checkpoint_operation_failed",
                operation=operation,
                backend=backend,
                error_type=type(exc).__name__,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            raise
        metrics.record_checkpoint(time.monotonic() - started, outcome="success", error_type=None)
        duration_ms = round((time.monotonic() - started) * 1000, 2)
        if duration_ms >= SLOW_CHECKPOINT_MS:
            logger.warning(
                "checkpoint_operation_slow",
                operation=operation,
                backend=backend,
                duration_ms=duration_ms,
            )
        return result

    return wrapper


@dataclass
class Persistence:
    """The configured checkpointer plus the connection pool it owns, if any.

    The Postgres saver binds to the running event loop, so it is created in `open()`
    (called from the FastAPI lifespan) rather than at import time.

    With `APP_LIMITS_BACKEND=postgres` the pool also serves the guards (ADR 0008 decision 8),
    including when the checkpointer is `memory` or `none`; then `backend` stays that of the
    checkpointer and no Postgres saver is created.
    """

    backend: str
    checkpointer: BaseCheckpointSaver[Any] | None
    pool: AsyncConnectionPool[Any] | None = None
    ping_timeout_seconds: float = 2.0
    serde: JsonPlusSerializer | None = field(default=None, repr=False)
    _opened: bool = field(default=False, init=False, repr=False)

    @property
    def is_open(self) -> bool:
        """Whether the pool is open and the checkpointer usable (true without a database)."""
        return self.pool is None or self._opened

    async def open(self, *, run_setup: bool = False) -> None:
        """Open the connection pool, create the saver, and optionally create the schema."""
        if self.pool is None:
            return
        await self.pool.open(wait=False)
        if self.backend == "postgres":
            self.checkpointer = instrument_checkpointer(
                AsyncPostgresSaver(self.pool, serde=self.serde), self.backend
            )
            if run_setup:
                await setup_schema(self)
        self._opened = True
        logger.info("checkpointer_opened", backend=self.backend)

    async def close(self) -> None:
        """Close the connection pool, if any."""
        if self.pool is None:
            return
        await self.pool.close()
        self._opened = False
        if self.backend == "postgres":
            self.checkpointer = None
        logger.info("checkpointer_closed", backend=self.backend)

    async def is_ready(self) -> bool:
        """Return whether the backing store is reachable (always true without a database)."""
        if self.pool is None:
            return True
        if not self.is_open:
            return False
        try:
            async with asyncio.timeout(self.ping_timeout_seconds):
                async with self.pool.connection() as conn:
                    await conn.execute("SELECT 1")
        except (TimeoutError, psycopg.Error) as exc:
            logger.warning(
                "checkpointer_unreachable", backend=self.backend, error_type=type(exc).__name__
            )
            return False
        return True


def build_persistence(settings: Settings) -> Persistence:
    """Build (but do not open) the checkpointer selected by settings."""
    serde = JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_MSGPACK_MODULES)
    backend = settings.checkpointer
    saver: BaseCheckpointSaver[Any] | None = None
    if backend == "memory":
        saver = instrument_checkpointer(InMemorySaver(serde=serde), "memory")
    elif backend != "postgres":
        backend = "none"
    if backend != "postgres" and settings.limits_backend != "postgres":
        return Persistence(backend=backend, checkpointer=saver)

    # Settings validation guarantees a DSN when either backend is postgres.
    assert settings.postgres_dsn is not None  # nosec B101
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        conninfo=settings.postgres_dsn.get_secret_value(),
        max_size=settings.postgres_pool_max_size,
        timeout=settings.postgres_pool_timeout_seconds,
        kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0},
        # Validate connections on checkout so the pool recovers after a database restart.
        check=AsyncConnectionPool.check_connection,
        open=False,
    )
    return Persistence(
        backend=backend,
        checkpointer=saver,
        pool=pool,
        ping_timeout_seconds=min(2.0, settings.postgres_pool_timeout_seconds),
        serde=serde,
    )


async def setup_schema(persistence: Persistence) -> None:
    """Create or migrate the schema on a direct connection (development start-up only).

    Staging and production run `persistence.cli setup` as a deploy step instead (ADR 0008
    decision 7); settings refuse start-up setup there.
    """
    if isinstance(persistence.checkpointer, AsyncPostgresSaver):
        assert persistence.pool is not None  # nosec B101
        conninfo = persistence.pool.conninfo
        assert isinstance(conninfo, str)  # nosec B101
        failure: str | None = None
        try:
            await migrations.run_setup(conninfo)
        except Exception as exc:
            # Driver messages can echo DSN fragments; keep only the class name. Raised
            # outside the handler so the original is not left in `__context__` either.
            failure = type(exc).__name__
        if failure is not None:
            raise RuntimeError(f"schema setup failed: {failure}")
        logger.info("checkpointer_schema_ready", backend=persistence.backend)
