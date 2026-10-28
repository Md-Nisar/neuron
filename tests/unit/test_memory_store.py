"""Per-user memory in a `BaseStore` (#245, ADR 0009 decision 7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from langgraph.store.memory import InMemoryStore

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import MemoryFullError, ValidationAppError
from neuron_agent.memory.store import MemoryStore
from neuron_agent.persistence.checkpointer import build_persistence

pytestmark = pytest.mark.anyio

_ALICE = "a" * 64
_BOB = "b" * 64
_KEY = b"k" * 32


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def _memory(
    *, max_items: int = 5, max_chars: int = 100, ttl_days: int | None = None
) -> tuple[MemoryStore, InMemoryStore, _Clock]:
    clock, store = _Clock(), InMemoryStore()
    return (
        MemoryStore(
            store,
            id_key=_KEY,
            max_items=max_items,
            max_chars=max_chars,
            ttl_days=ttl_days,
            clock=clock,
        ),
        store,
        clock,
    )


async def test_a_memory_is_listed_with_the_users_own_words() -> None:
    memory, _, _ = _memory()
    saved = await memory.remember(_ALICE, "  I prefer window seats  ")

    assert [m.text for m in await memory.list(_ALICE)] == ["I prefer window seats"]
    assert saved.id == (await memory.list(_ALICE))[0].id


async def test_remembering_the_same_thing_twice_is_one_memory() -> None:
    memory, _, _ = _memory()
    first = await memory.remember(_ALICE, "I prefer window seats")
    again = await memory.remember(_ALICE, "i prefer   WINDOW seats")

    assert again.id == first.id
    assert len(await memory.list(_ALICE)) == 1


async def test_users_never_see_each_others_memories() -> None:
    memory, store, _ = _memory()
    saved = await memory.remember(_ALICE, "my passport number is on the fridge")

    assert await memory.list(_BOB) == []
    assert await memory.forget(_BOB, saved.id) is False  # a foreign ID deletes nothing
    assert await memory.erase(_BOB) == 0
    assert len(await memory.list(_ALICE)) == 1
    # Stored under the owner key, in a namespace of its own.
    assert [item.namespace for item in await store.asearch(("memories",))] == [("memories", _ALICE)]


async def test_a_request_without_an_owner_is_one_anonymous_bucket_apart_from_users() -> None:
    memory, _, _ = _memory()
    await memory.remember(None, "development note")
    assert [m.text for m in await memory.list(None)] == ["development note"]
    assert await memory.list(_ALICE) == []


async def test_the_item_limit_refuses_a_new_memory_but_not_a_repeat() -> None:
    memory, _, _ = _memory(max_items=2)
    await memory.remember(_ALICE, "one")
    await memory.remember(_ALICE, "two")

    with pytest.raises(MemoryFullError):
        await memory.remember(_ALICE, "three")
    assert (await memory.remember(_ALICE, "two")).text == "two"  # already there: no new item
    await memory.remember(_BOB, "bob's own one")  # the limit is per user


@pytest.mark.parametrize("text", ["", "   ", "x" * 101, "bell\x07char"])
async def test_text_passes_the_input_policy(text: str) -> None:
    memory, _, _ = _memory(max_chars=100)
    with pytest.raises(ValidationAppError):
        await memory.remember(_ALICE, text)
    assert await memory.list(_ALICE) == []


async def test_memories_expire_and_free_their_slot() -> None:
    memory, store, clock = _memory(max_items=1, ttl_days=30)
    await memory.remember(_ALICE, "short lived")

    clock.now += timedelta(days=29)
    assert len(await memory.list(_ALICE)) == 1
    clock.now += timedelta(days=2)
    assert await memory.list(_ALICE) == []
    assert await store.asearch(("memories", _ALICE)) == []  # removed, not just hidden
    await memory.remember(_ALICE, "short lived")  # the same text can be stored again
    assert len(await memory.list(_ALICE)) == 1


async def test_listing_is_oldest_first_and_forget_and_erase_remove() -> None:
    memory, _, clock = _memory()
    first = await memory.remember(_ALICE, "first")
    clock.now += timedelta(minutes=1)
    await memory.remember(_ALICE, "second")
    clock.now += timedelta(minutes=1)
    await memory.remember(_ALICE, "third")

    assert [m.text for m in await memory.list(_ALICE)] == ["first", "second", "third"]
    assert await memory.forget(_ALICE, first.id) is True
    assert await memory.forget(_ALICE, first.id) is False
    assert await memory.erase(_ALICE) == 2
    assert await memory.list(_ALICE) == []


def test_the_store_exists_only_when_memory_is_enabled() -> None:
    assert build_persistence(Settings(env="test")).store is None
    on = build_persistence(Settings(env="test", memory_enabled=True))
    assert isinstance(on.store, InMemoryStore)
    none = build_persistence(Settings(env="test", memory_enabled=True, checkpointer="none"))
    assert isinstance(none.store, InMemoryStore)


async def test_purge_removes_expired_memories_of_users_who_never_return() -> None:
    memory, store, clock = _memory(ttl_days=10)
    await memory.remember(_ALICE, "old news")
    clock.now += timedelta(days=5)
    await memory.remember(_BOB, "newer")
    clock.now += timedelta(days=6)  # alice's is 11 days old, bob's 6

    assert await memory.purge_expired() == 1
    assert await store.asearch(("memories", _ALICE)) == []
    assert len(await store.asearch(("memories", _BOB))) == 1


async def test_purge_does_nothing_without_a_ttl() -> None:
    memory, store, clock = _memory()
    await memory.remember(_ALICE, "kept")
    clock.now += timedelta(days=3650)
    assert await memory.purge_expired() == 0
    assert len(await store.asearch(("memories", _ALICE))) == 1


async def test_an_id_is_keyed_and_per_owner_not_a_hash_of_the_words() -> None:
    import hashlib

    memory, store, _ = _memory()
    mine = await memory.remember(_ALICE, "I am vegetarian")
    theirs = await memory.remember(_BOB, "I am vegetarian")

    assert mine.id != theirs.id  # not comparable between users
    assert mine.id != hashlib.sha256(b"i am vegetarian").hexdigest()[:32]  # no dictionary check
    other_key = MemoryStore(store, id_key=b"x" * 32, max_items=5, max_chars=100)
    assert other_key.memory_id(_ALICE, "I am vegetarian") != mine.id
    assert memory.memory_id(_ALICE, "  i AM   vegetarian ") == mine.id  # stable for a repeat


async def test_operations_leave_a_span_and_a_count_with_no_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import InMemoryMetricReader
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from neuron_agent.observability import metrics, telemetry

    exporter, reader = InMemorySpanExporter(), InMemoryMetricReader()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    meter_provider = MeterProvider(metric_readers=[reader], views=metrics.metric_views())
    monkeypatch.setattr(telemetry, "tracer", lambda: tracer_provider.get_tracer("t"))
    monkeypatch.setattr(metrics, "_meter", lambda: meter_provider.get_meter("t"))

    memory, _, _ = _memory(max_items=1)
    saved = await memory.remember(_ALICE, "private words")
    await memory.list(_ALICE)
    with pytest.raises(MemoryFullError):
        await memory.remember(_ALICE, "more private words")
    await memory.forget(_ALICE, saved.id)
    await memory.erase(_ALICE)

    spans = exporter.get_finished_spans()
    assert [s.name for s in spans] == [
        "neuron.memory.remember",
        "neuron.memory.list",
        "neuron.memory.remember",
        "neuron.memory.forget",
        "neuron.memory.erase",
    ]
    assert [dict(s.attributes or {})["neuron.outcome"] for s in spans] == [
        "success",
        "success",
        "error",
        "success",
        "success",
    ]
    assert "private" not in str([dict(s.attributes or {}) for s in spans])
    data = reader.get_metrics_data()
    assert data is not None
    points = [
        p
        for r in data.resource_metrics
        for s in r.scope_metrics
        for m in s.metrics
        if m.name == "neuron.memory.operations"
        for p in m.data.data_points
    ]
    assert sum(p.value for p in points) == 5
    assert "private" not in str([dict(p.attributes) for p in points])
