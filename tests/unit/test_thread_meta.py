"""The conversation title stores (ADR 0011)."""

from __future__ import annotations

from typing import Any

import pytest

from neuron_agent.persistence.thread_meta import (
    TITLE_MAX_CHARS,
    InMemoryThreadTitles,
    PostgresThreadTitles,
    derive_title,
)

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("message", "title"),
    [
        ("hello", "hello"),
        ("  a \n\t b   c ", "a b c"),
        ("x" * 200, "x" * TITLE_MAX_CHARS),
        ("word " * 40, ("word " * 40)[:TITLE_MAX_CHARS].rstrip()),
        ("   \n\t ", None),
        ("", None),
    ],
)
def test_derive_title(message: str, title: str | None) -> None:
    assert derive_title(message) == title


async def test_a_title_is_set_once_and_read_only_by_its_owner() -> None:
    store = InMemoryThreadTitles()
    await store.set_if_absent("alice", "t1", "first")
    await store.set_if_absent("alice", "t1", "second")

    assert await store.titles("alice", ["t1", "t2"]) == {"t1": "first"}
    assert await store.titles("bob", ["t1"]) == {}


async def test_forgetting_threads_and_owners() -> None:
    store = InMemoryThreadTitles()
    await store.set_if_absent("alice", "t1", "one")
    await store.set_if_absent("alice", "t2", "two")
    await store.set_if_absent("bob", "t3", "three")

    await store.forget_threads(["t1"])
    assert await store.titles("alice", ["t1", "t2"]) == {"t2": "two"}
    await store.forget_owner("alice")  # also removes rows whose thread is already gone
    assert await store.titles("alice", ["t2"]) == {}
    assert await store.titles("bob", ["t3"]) == {"t3": "three"}


class _FakePool:
    """Records every statement and its parameters; returns the given rows for a SELECT."""

    def __init__(self, rows: list[dict[str, str]] | None = None) -> None:
        self.calls: list[tuple[str, Any]] = []
        self._rows = rows or []

    def connection(self) -> _FakePool:
        return self

    async def __aenter__(self) -> _FakePool:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, query: str, params: Any = None) -> _FakePool:
        self.calls.append((" ".join(query.split()), params))
        return self

    async def fetchall(self) -> list[dict[str, str]]:
        return self._rows


async def test_postgres_statements_are_parameterised_and_owner_scoped() -> None:
    pool = _FakePool([{"thread_id": "t1", "title": "one"}])
    store = PostgresThreadTitles(pool)  # type: ignore[arg-type]

    await store.set_if_absent("alice", "t1", "it's a 'title'; DROP TABLE x")
    titles = await store.titles("alice", ["t1"])
    await store.forget_threads(["t1"])
    await store.forget_owner("alice")

    assert titles == {"t1": "one"}
    insert, select, by_thread, by_owner = pool.calls
    assert insert[0].endswith("ON CONFLICT DO NOTHING")
    assert insert[1] == ("alice", "t1", "it's a 'title'; DROP TABLE x")
    assert "owner_key = %s" in select[0] and select[1] == ("alice", ["t1"])
    assert by_thread[1] == (["t1"],)
    assert by_owner[0].endswith("WHERE owner_key = %s") and by_owner[1] == ("alice",)
    assert all("DROP TABLE" not in query for query, _ in pool.calls)


async def test_postgres_rename_is_an_owner_scoped_upsert() -> None:
    pool = _FakePool()
    await PostgresThreadTitles(pool).rename("alice", "t1", "new")  # type: ignore[arg-type]

    [(query, params)] = pool.calls
    assert "ON CONFLICT (owner_key, thread_id) DO UPDATE SET title = EXCLUDED.title" in query
    assert params == ("alice", "t1", "new")


async def test_rename_replaces_a_title() -> None:
    store = InMemoryThreadTitles()
    await store.set_if_absent("alice", "t1", "first")
    await store.rename("alice", "t1", "renamed")

    assert await store.titles("alice", ["t1"]) == {"t1": "renamed"}


async def test_postgres_empty_inputs_make_no_query() -> None:
    pool = _FakePool()
    store = PostgresThreadTitles(pool)  # type: ignore[arg-type]

    assert await store.titles("alice", []) == {}
    await store.forget_threads([])

    assert pool.calls == []
