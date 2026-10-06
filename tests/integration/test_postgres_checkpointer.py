from __future__ import annotations

import os

import pytest
from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.schemas.agent import AgentRequest
from neuron_agent.services.agent_service import AgentService

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

_DSN = os.environ.get("APP_TEST_POSTGRES_DSN")


def _settings() -> Settings:
    if not _DSN:
        pytest.skip("APP_TEST_POSTGRES_DSN is not set; see OPERATIONS.md for a local Postgres.")
    return Settings(
        env="test",
        checkpointer="postgres",
        postgres_dsn=SecretStr(_DSN),
        checkpointer_setup_on_startup=True,
    )


async def test_postgres_setup_is_idempotent() -> None:
    settings = _settings()
    for _ in range(2):
        persistence = build_persistence(settings)
        await persistence.open(run_setup=True)
        try:
            assert await persistence.is_ready() is True
        finally:
            await persistence.close()


async def test_thread_state_survives_service_restart() -> None:
    settings = _settings()
    first = AgentService(settings)
    await first.startup()
    try:
        response = await first.invoke(AgentRequest(message="remember me"))
    finally:
        await first.shutdown()

    restarted = AgentService(settings)
    await restarted.startup()
    try:
        config = {"configurable": {"thread_id": response.thread_id}}
        state = await restarted.graph.aget_state(config)
    finally:
        await restarted.shutdown()
    assert state.values["messages"][0].content == "remember me"
    assert state.values["answer"].answer == response.answer
