"""A reranker that keeps failing stops costing every search its full timeout."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import anyio
import pytest

from neuron_agent.config.settings import ProcessingLocality, Settings
from neuron_agent.knowledge import retrieval
from neuron_agent.knowledge.reranking import RerankError
from neuron_agent.knowledge.retrieval import Passage, Retriever

pytestmark = pytest.mark.anyio


class _Reranker:
    locality: ProcessingLocality = "hosted"

    def __init__(self, outcomes: list[Exception | None]) -> None:
        self.outcomes = outcomes
        self.calls = 0

    async def rerank(self, query: str, texts: Sequence[str]) -> list[tuple[int, float]]:
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome is not None:
            raise outcome
        return [(len(texts) - 1 - i, 1.0 - i) for i in range(len(texts))]


def _passages(kb: uuid.UUID) -> list[Passage]:
    return [
        Passage(uuid.uuid4(), uuid.uuid4(), kb, "t", i, f"text {i}", [], None, None, 0.0)
        for i in range(3)
    ]


async def _search(retriever: Retriever, kb: uuid.UUID) -> tuple[list[Passage], bool]:
    bases = [{"kb_id": kb, "processing": "hosted"}]
    return await retriever._rerank("q", bases, _passages(kb), 2)


def _retriever(reranker: _Reranker) -> Retriever:
    return Retriever(Settings(env="test"), lambda: None, None, reranker)  # type: ignore[arg-type]


async def test_three_failures_open_the_circuit_and_the_cooldown_ends_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [1000.0]
    monkeypatch.setattr(retrieval.time, "monotonic", lambda: now[0])
    kb = uuid.uuid4()
    reranker = _Reranker([RerankError("rerank_timeout")] * 3)
    retriever = _retriever(reranker)

    for _ in range(3):
        assert (await _search(retriever, kb))[1] is False
    assert reranker.calls == 3

    # Open: the RRF order is kept without calling the provider.
    passages, reranked = await _search(retriever, kb)
    assert (reranker.calls, reranked, [p.text for p in passages]) == (
        3,
        False,
        ["text 0", "text 1"],
    )

    # Cooldown over: one search tries again, succeeds and closes the circuit.
    now[0] += retrieval._RERANK_BREAKER_COOLDOWN_SECONDS + 1
    assert (await _search(retriever, kb))[1] is True
    assert (await _search(retriever, kb))[1] is True
    assert reranker.calls == 5


async def test_a_failed_probe_reopens_the_circuit_for_another_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [1000.0]
    monkeypatch.setattr(retrieval.time, "monotonic", lambda: now[0])
    kb = uuid.uuid4()
    reranker = _Reranker([RerankError("rerank_timeout")] * 4)
    retriever = _retriever(reranker)
    for _ in range(3):
        await _search(retriever, kb)
    now[0] += retrieval._RERANK_BREAKER_COOLDOWN_SECONDS + 1
    await _search(retriever, kb)  # the probe fails
    await _search(retriever, kb)
    assert reranker.calls == 4


async def test_a_success_in_between_keeps_the_circuit_closed() -> None:
    kb = uuid.uuid4()
    outcomes: list[Exception | None] = [RerankError("rerank_timeout")] * 2 + [None]
    reranker = _Reranker(outcomes * 3)
    retriever = _retriever(reranker)
    for _ in range(9):
        await _search(retriever, kb)
    assert reranker.calls == 9


async def test_only_one_search_probes_a_half_open_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [1000.0]
    monkeypatch.setattr(retrieval.time, "monotonic", lambda: now[0])
    kb = uuid.uuid4()
    reranker = _Reranker([RerankError("rerank_timeout")] * 3)
    retriever = _retriever(reranker)
    for _ in range(3):
        await _search(retriever, kb)
    now[0] += retrieval._RERANK_BREAKER_COOLDOWN_SECONDS + 1

    release = anyio.Event()
    inner = reranker.rerank

    async def slow(query: str, texts: Sequence[str]) -> list[tuple[int, float]]:
        await release.wait()
        return await inner(query, texts)

    reranker.rerank = slow  # type: ignore[method-assign]
    results: list[bool] = []

    async def search() -> None:
        results.append((await _search(retriever, kb))[1])

    async with anyio.create_task_group() as group:
        group.start_soon(search)
        await anyio.sleep(0)
        group.start_soon(search)  # arrives while the probe is in flight: skips the reranker
        group.start_soon(search)
        await anyio.sleep(0)
        release.set()
    assert sorted(results) == [False, False, True]
    assert reranker.calls == 4
