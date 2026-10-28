"""The answer rating stores (ADR 0010 decision 6, ADR 0011)."""

from __future__ import annotations

from typing import Any

import pytest

from neuron_agent.persistence.feedback import InMemoryFeedback, PostgresFeedback

pytestmark = pytest.mark.anyio


async def test_the_first_rating_of_a_run_stands_and_a_repeat_records_nothing() -> None:
    store = InMemoryFeedback()

    first = await store.record("alice", "t1", "r1", -1, "unsafe")
    again = await store.record("alice", "t1", "r1", 1, "helpful")

    assert (first.created, first.score, first.reason) == (True, -1, "unsafe")
    assert (again.created, again.score, again.reason) == (False, -1, "unsafe")


async def test_owners_are_separate_and_a_stored_rating_names_its_thread() -> None:
    store = InMemoryFeedback()
    await store.record("alice", "t1", "r1", 1, None)

    bob = await store.record("bob", "t2", "r1", -1, None)
    alice_elsewhere = await store.record("alice", "t9", "r1", 1, None)

    assert (bob.created, bob.score, bob.thread_id) == (True, -1, "t2")
    assert (alice_elsewhere.created, alice_elsewhere.thread_id) == (False, "t1")


async def test_forgetting_threads_and_owners() -> None:
    store = InMemoryFeedback()
    await store.record("alice", "t1", "r1", 1, None)
    await store.record("alice", "t2", "r2", 1, None)
    await store.record("bob", "t3", "r3", 1, None)

    await store.forget_threads(["t1"])
    assert (await store.record("alice", "t1", "r1", -1, None)).created  # it was gone
    await store.forget_owner("alice")  # also rows whose thread is already gone
    assert (await store.record("alice", "t2", "r2", -1, None)).created
    assert not (await store.record("bob", "t3", "r3", -1, None)).created


class _Pool:
    """Records every statement; answers the given rows to the next fetches, oldest first."""

    def __init__(self, *rows: dict[str, Any] | None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._rows = list(rows)

    def connection(self) -> _Pool:
        return self

    async def __aenter__(self) -> _Pool:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, query: str, params: Any = None) -> _Pool:
        self.calls.append((" ".join(query.split()), params))
        return self

    async def fetchone(self) -> dict[str, Any] | None:
        return self._rows.pop(0) if self._rows else None


async def test_postgres_insert_is_a_parameterised_idempotent_upsert() -> None:
    pool = _Pool({"thread_id": "t1", "score": 1, "reason": "helpful"})

    stored = await PostgresFeedback(pool).record("alice", "t1", "r1", 1, "helpful")  # type: ignore[arg-type]

    [(query, params)] = pool.calls
    assert "ON CONFLICT (owner_key, run_id) DO NOTHING RETURNING" in query
    assert params == ("alice", "t1", "r1", 1, "helpful")
    assert stored.created


async def test_postgres_repeat_reads_the_stored_rating_for_the_same_owner_and_run() -> None:
    pool = _Pool(None, {"thread_id": "t1", "score": -1, "reason": "unsafe"})

    stored = await PostgresFeedback(pool).record("alice", "t1", "r1", 1, None)  # type: ignore[arg-type]

    select_query, select_params = pool.calls[1]
    assert "WHERE owner_key = %s AND run_id = %s" in select_query
    assert select_params == ("alice", "r1")
    assert (stored.created, stored.score, stored.reason) == (False, -1, "unsafe")


async def test_postgres_deletes_are_scoped_and_empty_input_makes_no_query() -> None:
    pool = _Pool()
    store = PostgresFeedback(pool)  # type: ignore[arg-type]

    await store.forget_threads([])
    await store.forget_threads(["t1"])
    await store.forget_owner("alice")

    assert pool.calls == [
        ("DELETE FROM neuron_feedback WHERE thread_id = ANY(%s)", (["t1"],)),
        ("DELETE FROM neuron_feedback WHERE owner_key = %s", ("alice",)),
    ]
