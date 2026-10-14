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
