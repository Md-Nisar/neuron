"""Interleavings between a run and a delete or an erase, forced at the exact point they
overlap (a hook on the claim or on the title write), never with a sleep."""

from __future__ import annotations

from typing import Any

import pytest

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import ThreadNotFoundError
from neuron_agent.schemas.agent import AgentRequest
from neuron_agent.services.agent_service import AgentService

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("echo_model")]


def _service() -> AgentService:
    return AgentService(Settings(env="test", checkpointer="memory"))


async def _checkpoints(service: AgentService, thread_id: str) -> int:
    checkpointer = service._persistence.checkpointer
    assert checkpointer is not None
    return len([c async for c in checkpointer.alist({"configurable": {"thread_id": thread_id}})])


async def test_a_run_that_resolved_its_thread_before_a_delete_does_not_recreate_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    thread_id = (await service.invoke(AgentRequest(message="one", user_id="alice"))).thread_id
    guard = service._run_guard
    claim = guard.claim

    async def claim_after_the_delete(**kwargs: Any) -> Any:
        # The run has checked that the thread is the caller's; the delete lands before its claim.
        await service.delete_thread(thread_id, "alice")
        return await claim(**kwargs)

    monkeypatch.setattr(guard, "claim", claim_after_the_delete)
    with pytest.raises(ThreadNotFoundError):
        await service.invoke(AgentRequest(message="two", thread_id=thread_id, user_id="alice"))

    assert await _checkpoints(service, thread_id) == 0
    # Nothing ran: the thread is free again and the reservation was given back.
    assert not await guard.is_thread_active(thread_id)
    assert await guard.active_threads_of(service.owner_key_for(None, "alice") or "") == frozenset()


async def test_an_erase_never_completes_between_a_runs_lease_and_its_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _service()
    titles = service._persistence.thread_titles
    owner = service.owner_key_for(None, "alice")
    assert owner is not None
    set_if_absent = titles.set_if_absent
    erasures = []

    async def erase_then_store(owner_key: str, thread_id: str, title: str) -> None:
        # The erase lands as the new thread's title is about to be written.
        erasures.append(await service.erase_user_data("alice"))
        await set_if_absent(owner_key, thread_id, title)

    monkeypatch.setattr(titles, "set_if_absent", erase_then_store)
    thread_id = (await service.invoke(AgentRequest(message="my secret", user_id="alice"))).thread_id

    [erasure] = erasures
    # The run still held its thread, so the erase skipped it and said so: it never reports a
    # complete erasure and then leaves the title (the first message's text) behind.
    assert (erasure.erased_count, erasure.skipped_busy_count) == (0, 1)
    assert await titles.titles(owner, [thread_id]) == {thread_id: "my secret"}
    assert await _checkpoints(service, thread_id) > 0
