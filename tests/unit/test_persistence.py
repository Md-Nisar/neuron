from __future__ import annotations

import psycopg
import pytest
import structlog.testing
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import PersistenceError
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.schemas.agent import AgentRequest
from neuron_agent.services.agent_service import AgentService

pytestmark = pytest.mark.anyio

_UNREACHABLE_DSN = "postgresql://neuron:s3cret-password@127.0.0.1:1/neuron"


def _postgres_settings() -> Settings:
    return Settings(
        env="test",
        checkpointer="postgres",
        postgres_dsn=SecretStr(_UNREACHABLE_DSN),
        postgres_pool_timeout_seconds=1,
        openai_api_key=None,
    )


async def test_none_backend_has_no_checkpointer() -> None:
    persistence = build_persistence(Settings(env="test", checkpointer="none", openai_api_key=None))
    assert persistence.checkpointer is None
    assert persistence.pool is None
    assert await persistence.is_ready() is True


async def test_memory_backend_uses_in_memory_saver() -> None:
    persistence = build_persistence(
        Settings(env="test", checkpointer="memory", openai_api_key=None)
    )
    assert isinstance(persistence.checkpointer, InMemorySaver)
    await persistence.open()
    assert await persistence.is_ready() is True
    await persistence.close()


def test_postgres_service_can_be_built_outside_an_event_loop() -> None:
    # Regression: AsyncPostgresSaver needs a running loop, and api/main.py builds the
    # service at import time. The saver must only be created in open().
    service = AgentService(_postgres_settings())
    persistence = service._persistence
    assert persistence.checkpointer is None
    assert persistence.pool is not None and persistence.pool.closed is True
    assert persistence.is_open is False


async def test_postgres_service_rejects_requests_before_startup() -> None:
    service = AgentService(_postgres_settings())
    assert await service.is_ready() is False
    with pytest.raises(PersistenceError):
        await service.invoke(AgentRequest(message="hello"))


async def test_postgres_open_creates_saver_and_close_releases_it() -> None:
    persistence = build_persistence(_postgres_settings())
    await persistence.open()
    assert isinstance(persistence.checkpointer, AsyncPostgresSaver)
    await persistence.close()
    assert persistence.checkpointer is None
    assert persistence.pool is not None and persistence.pool.closed is True


async def test_postgres_readiness_fails_without_leaking_dsn() -> None:
    persistence = build_persistence(_postgres_settings())
    await persistence.open()
    try:
        with structlog.testing.capture_logs() as logs:
            assert await persistence.is_ready() is False
    finally:
        await persistence.close()
    assert persistence.pool is not None and persistence.pool.closed is True
    unreachable = next(log for log in logs if log["event"] == "checkpointer_unreachable")
    assert unreachable["backend"] == "postgres"
    assert "s3cret-password" not in repr(logs)


async def test_memory_checkpointer_persists_thread_state() -> None:
    service = AgentService(Settings(env="test", checkpointer="memory", openai_api_key=None))
    response = await service.invoke(AgentRequest(message="hello"))
    state = await service.graph.aget_state({"configurable": {"thread_id": response.thread_id}})
    assert [type(m) for m in state.values["messages"]][0] is HumanMessage
    assert state.values["answer"].answer == response.answer


async def test_service_maps_checkpointer_failure_to_persistence_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AgentService(Settings(env="test", checkpointer="memory", openai_api_key=None))

    async def fail(*_: object, **__: object) -> None:
        raise psycopg.OperationalError("connection refused")

    monkeypatch.setattr(service.graph, "ainvoke", fail)
    with structlog.testing.capture_logs() as logs:
        with pytest.raises(PersistenceError):
            await service.invoke(AgentRequest(message="hello"))
    failed = next(log for log in logs if log["event"] == "checkpointer_operation_failed")
    assert failed["error_type"] == "OperationalError"


def _guards_settings(checkpointer: str = "none") -> Settings:
    return Settings(
        env="test",
        checkpointer=checkpointer,  # type: ignore[arg-type]
        limits_backend="postgres",
        postgres_dsn=SecretStr(_UNREACHABLE_DSN),
        postgres_pool_timeout_seconds=1,
        openai_api_key=None,
    )


async def test_limits_postgres_opens_a_pool_without_a_checkpointer() -> None:
    persistence = build_persistence(_guards_settings())
    assert persistence.pool is not None and persistence.backend == "none"
    assert persistence.is_open is False
    await persistence.open()
    try:
        assert persistence.is_open is True
        assert persistence.pool.closed is False
        assert persistence.checkpointer is None  # no saver: the pool serves the guards only
        assert await persistence.is_ready() is False  # readiness reflects the database
    finally:
        await persistence.close()
    assert persistence.pool.closed is True and persistence.is_open is False


async def test_limits_postgres_readiness_is_true_when_the_database_answers() -> None:
    class _Conn:
        async def execute(self, _: str) -> None:
            return None

    class _Connection:
        async def __aenter__(self) -> _Conn:
            return _Conn()

        async def __aexit__(self, *_: object) -> None:
            return None

    class _Pool:
        def connection(self) -> _Connection:
            return _Connection()

    persistence = build_persistence(_guards_settings())
    persistence.pool = _Pool()  # type: ignore[assignment]
    persistence._opened = True
    assert await persistence.is_ready() is True


def test_memory_limits_with_memory_checkpointer_open_no_pool() -> None:
    persistence = build_persistence(Settings(env="test", checkpointer="memory"))
    assert persistence.pool is None and persistence.is_open is True


def test_limits_postgres_keeps_the_memory_checkpointer() -> None:
    persistence = build_persistence(_guards_settings("memory"))
    assert isinstance(persistence.checkpointer, InMemorySaver)
    assert persistence.pool is not None and persistence.is_open is False


def test_postgres_guards_fail_fast_until_they_exist() -> None:
    with pytest.raises(NotImplementedError, match="APP_LIMITS_BACKEND=postgres"):
        AgentService(_guards_settings())


async def test_startup_setup_failure_never_leaks_the_dsn() -> None:
    dsn = "postgresql://neuron:fake-pw-9f3@[bad/db"
    persistence = build_persistence(
        Settings(env="test", checkpointer="postgres", postgres_dsn=SecretStr(dsn))
    )
    with pytest.raises(RuntimeError) as caught:
        await persistence.open(run_setup=True)
    exc: BaseException | None = caught.value
    while exc is not None:  # the whole chain, not just the top
        assert "fake-pw-9f3" not in str(exc) and "bad/db" not in str(exc)
        exc = exc.__cause__ or exc.__context__
    assert str(caught.value).startswith("schema setup failed: ")
    assert persistence.pool is not None
    await persistence.pool.close()


async def test_open_closes_the_pool_when_the_role_check_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancellation during the production role check must not leave the pool open."""
    import asyncio

    from neuron_agent.persistence import checkpointer as module

    class _Conn:
        async def __aenter__(self) -> _Conn:
            return self

        async def __aexit__(self, *exc: object) -> None:
            return None

    class _Pool:
        closed = False

        async def open(self, *, wait: bool) -> None:
            return None

        def connection(self) -> _Conn:
            return _Conn()

        async def close(self) -> None:
            self.closed = True

    async def cancelled(conn: object, role: str) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(module, "verify_runtime_role", cancelled)
    pool = _Pool()
    persistence = module.Persistence(  # type: ignore[call-overload,arg-type]
        backend="postgres", checkpointer=None, pool=pool, app_role="neuron_app"
    )
    with pytest.raises(asyncio.CancelledError):
        await persistence.open()
    assert pool.closed
