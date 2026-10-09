from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta

import pytest
from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import ThreadNotFoundError
from neuron_agent.persistence.checkpointer import build_persistence
from neuron_agent.persistence.retention import prune_threads
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
        response = await first.invoke(AgentRequest(message="remember me", user_id="alice"))
    finally:
        await first.shutdown()

    restarted = AgentService(settings)
    await restarted.startup()
    try:
        with pytest.raises(ThreadNotFoundError):
            await restarted.invoke(
                AgentRequest(message="steal", thread_id=response.thread_id, user_id="bob")
            )
        await restarted.invoke(
            AgentRequest(message="again", thread_id=response.thread_id, user_id="alice")
        )
        config = {"configurable": {"thread_id": response.thread_id}}
        state = await restarted.graph.aget_state(config)
    finally:
        await restarted.shutdown()
    contents = [m.content for m in state.values["messages"]]
    assert contents[0] == "remember me"
    assert contents[2] == "again"
    assert len(contents) == 4


async def test_postgres_delete_and_prune_threads() -> None:
    settings = _settings()
    service = AgentService(settings)
    await service.startup()
    try:
        old = (await service.invoke(AgentRequest(message="old"))).thread_id
        recent = (await service.invoke(AgentRequest(message="recent"))).thread_id
        doomed = (await service.invoke(AgentRequest(message="doomed"))).thread_id

        await service.delete_thread(doomed, None)
        with pytest.raises(ThreadNotFoundError):
            await service.get_history(doomed, None, limit=10, offset=0)

        checkpointer = service._persistence.checkpointer
        assert checkpointer is not None
        old_ts = (await checkpointer.aget_tuple({"configurable": {"thread_id": old}})).checkpoint[
            "ts"
        ]
        recent_ts = (
            await checkpointer.aget_tuple({"configurable": {"thread_id": recent}})
        ).checkpoint["ts"]
        old_at, recent_at = datetime.fromisoformat(old_ts), datetime.fromisoformat(recent_ts)
        cutoff = old_at + (recent_at - old_at) / 2

        persistence = service._persistence
        # Other threads in the shared test database are older than `old`, so count >= 1.
        assert await prune_threads(persistence, older_than=timedelta(0), now=cutoff) >= 1
        assert await prune_threads(persistence, older_than=timedelta(0), now=cutoff) == 0
        with pytest.raises(ThreadNotFoundError):
            await service.get_history(old, None, limit=10, offset=0)
        assert (await service.get_history(recent, None, limit=10, offset=0)).total == 2
    finally:
        await service.shutdown()


@pytest.mark.usefixtures("echo_agent")
async def test_postgres_owner_metadata_listing_and_bulk_erasure() -> None:
    settings = _settings()
    service = AgentService(settings)
    await service.startup()
    try:
        alice_thread = (
            await service.invoke(AgentRequest(message="alice data", user_id="alice"))
        ).thread_id
        bob_thread = (
            await service.invoke(AgentRequest(message="bob data", user_id="bob"))
        ).thread_id

        alice_page = await service.list_user_threads("alice", limit=100, offset=0)
        assert alice_page.total == 1
        assert [item.thread_id for item in alice_page.threads] == [alice_thread]

        checkpointer = service._persistence.checkpointer
        assert checkpointer is not None
        alice_owner = hashlib.sha256(b"alice").hexdigest()
        owner_checkpoints = [
            item
            async for item in checkpointer.alist(None, filter={"owner": alice_owner})
            if item.config["configurable"].get("checkpoint_ns", "") == ""
        ]
        assert owner_checkpoints
        assert all(item.metadata["owner"] == alice_owner for item in owner_checkpoints)

        erased = await service.erase_user_data("alice")
        assert erased.erased_count == 1
        assert erased.skipped_busy_count == 0
        assert (await service.list_user_threads("alice", limit=100, offset=0)).total == 0
        assert (await service.get_history(bob_thread, "bob", limit=10, offset=0)).total == 2
    finally:
        await service.shutdown()
