"""The retention job against a thread that becomes active again after it was listed as stale.

The turn is run from a hook on the job's own hold, so it lands exactly between the listing and
the delete; no sleeps."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
import structlog

from neuron_agent.config.settings import Settings
from neuron_agent.persistence.retention import prune_threads
from neuron_agent.schemas.agent import AgentRequest
from neuron_agent.services.agent_service import AgentService

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("echo_model")]


async def _last_activity(service: AgentService, thread_id: str) -> datetime:
    checkpointer = service._persistence.checkpointer
    assert checkpointer is not None
    item = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})
    assert item is not None
    return datetime.fromisoformat(item.checkpoint["ts"])


async def test_prune_keeps_a_thread_that_got_a_turn_after_it_was_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AgentService(Settings(env="test", checkpointer="memory"))
    thread_id = (await service.invoke(AgentRequest(message="old", user_id="alice"))).thread_id
    cutoff = await _last_activity(service, thread_id) + timedelta(microseconds=1)
    guard = service._run_guard
    hold_thread = guard.hold_thread

    async def hold_after_a_new_turn(**kwargs: Any) -> Any:
        # The job has listed the thread as stale; its owner comes back before the job holds it.
        await service.invoke(AgentRequest(message="new", thread_id=thread_id, user_id="alice"))
        return await hold_thread(**kwargs)

    monkeypatch.setattr(guard, "hold_thread", hold_after_a_new_turn)
    with structlog.testing.capture_logs() as logs:
        pruned = await prune_threads(
            service._persistence, older_than=timedelta(0), now=cutoff, run_guard=guard
        )

    assert pruned == 0
    history = await service.get_history(thread_id, "alice", limit=10, offset=0)
    assert [turn.content for turn in history.messages if turn.role == "user"] == ["old", "new"]
    assert not await guard.is_thread_active(thread_id)  # the hold was given back
    assert [e["thread_id"] for e in logs if e["event"] == "retention_prune_skipped_active"] == [
        thread_id
    ]


async def test_prune_without_a_run_guard_also_reads_the_thread_again() -> None:
    service = AgentService(Settings(env="test", checkpointer="memory"))
    thread_id = (await service.invoke(AgentRequest(message="old", user_id="alice"))).thread_id
    cutoff = await _last_activity(service, thread_id) + timedelta(microseconds=1)
    checkpointer = service._persistence.checkpointer
    assert checkpointer is not None
    alist = checkpointer.alist

    async def list_then_a_new_turn(config: Any, **kwargs: Any) -> Any:
        async for item in alist(config, **kwargs):
            yield item
        if config is None:  # the job's listing, not a read of one thread
            request = AgentRequest(message="new", thread_id=thread_id, user_id="alice")
            await service.invoke(request)

    checkpointer.alist = list_then_a_new_turn  # type: ignore[method-assign]
    assert await prune_threads(service._persistence, older_than=timedelta(0), now=cutoff) == 0
    history = await service.get_history(thread_id, "alice", limit=10, offset=0)
    assert [turn.content for turn in history.messages if turn.role == "user"] == ["old", "new"]
