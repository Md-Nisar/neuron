"""Reranking inside hybrid search, on Postgres as the app role (RAG-09.01).

The reranker only reorders what authorised search found: it sees the caller's passages and no
other, never sees a base that forbids hosted processing, and any failure keeps the RRF order.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

import pytest
from test_postgres_knowledge_search import _A, _B, _base, _document, _retriever
from test_postgres_knowledge_tables import _knowledge_db
from test_postgres_roles import RoleDatabase, role_db, roles  # noqa: F401

from neuron_agent.knowledge.reranking import RerankError
from neuron_agent.knowledge.retrieval import RERANK_CANDIDATES, Retriever

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]


class _Reranker:
    """Reverses the order it is given; `fail` raises, `delay` sleeps first."""

    def __init__(self, *, fail: bool = False, delay: float = 0.0, locality: Any = "hosted") -> None:
        self.locality = locality
        self.calls: list[tuple[str, list[str]]] = []
        self.fail, self.delay = fail, delay

    async def rerank(self, query: str, texts: Sequence[str]) -> list[tuple[int, float]]:
        self.calls.append((query, list(texts)))
        await asyncio.sleep(self.delay)
        if self.fail:
            raise RerankError("rerank_failed")
        return [(i, float(i)) for i in reversed(range(len(texts)))]


def _with(retriever: Retriever, reranker: _Reranker) -> Retriever:
    retriever._reranker = reranker
    return retriever


async def _seeded(db: RoleDatabase, count: int, processing: str = "hosted") -> None:
    await _knowledge_db(db)
    kb = await _base(db, _A, processing)
    await _document(db, kb, _A, [f"valve passage number {n}" for n in range(count)])


async def test_the_reranker_orders_the_top_candidates_and_keeps_k(role_db: RoleDatabase) -> None:  # noqa: F811
    await _seeded(role_db, RERANK_CANDIDATES + 5)
    plain = await _retriever(role_db, locality="hosted").search(_A, "valve", k=50, mode="fts")
    reranker = _Reranker()
    result = await _with(_retriever(role_db, locality="hosted"), reranker).search(
        _A, "valve", k=5, mode="fts"
    )
    [(query, texts)] = reranker.calls
    assert query == "valve"
    # The fused top 40, in RRF order, are reranked; the best k of the reranker's order return.
    assert texts == [p.text for p in plain.passages[:RERANK_CANDIDATES]]
    assert [p.text for p in result.passages] == texts[::-1][:5]
    assert [p.score for p in result.passages] == [39.0, 38.0, 37.0, 36.0, 35.0]
    assert result.reranked is True


@pytest.mark.parametrize("failure", ["error", "timeout"])
async def test_a_failing_reranker_keeps_the_rrf_order(
    role_db: RoleDatabase,  # noqa: F811
    failure: str,
) -> None:
    """AC1: on a timeout or error, results return in RRF order with `reranked: false`."""
    await _seeded(role_db, 12)
    plain = await _retriever(role_db, locality="hosted").search(_A, "valve", k=5, mode="fts")
    reranker = _Reranker(fail=failure == "error", delay=5.0 if failure == "timeout" else 0.0)
    retriever = _with(
        _retriever(role_db, locality="hosted", knowledge_reranker_timeout_seconds=0.05), reranker
    )
    result = await retriever.search(_A, "valve", k=5, mode="fts")
    assert len(reranker.calls) == 1
    assert [p.chunk_id for p in result.passages] == [p.chunk_id for p in plain.passages]
    assert [p.score for p in result.passages] == [p.score for p in plain.passages]
    assert result.reranked is False


@pytest.mark.parametrize(
    ("processing", "policy"),
    [("self_hosted", "allow_hosted"), ("hosted", "self_hosted_only")],
)
async def test_a_hosted_reranker_never_sees_a_base_kept_off_hosted_processing(
    role_db: RoleDatabase,  # noqa: F811
    processing: str,
    policy: str,
) -> None:
    await _seeded(role_db, 3, processing)
    reranker = _Reranker()
    retriever = _with(_retriever(role_db, knowledge_processing_policy=policy), reranker)
    result = await retriever.search(_A, "valve", k=5, mode="fts")
    assert reranker.calls == []
    assert (len(result.passages), result.reranked) == (3, False)


async def test_one_base_kept_off_hosted_processing_skips_the_whole_rerank(
    role_db: RoleDatabase,  # noqa: F811
) -> None:
    """Not a filtered rerank: dropping that base's passages would change what the user sees."""
    await _knowledge_db(role_db)
    [hosted] = await _document(role_db, await _base(role_db, _A, "hosted"), _A, ["valve one"])
    [kept] = await _document(role_db, await _base(role_db, _A, "self_hosted"), _A, ["valve two"])
    reranker = _Reranker()
    result = await _with(_retriever(role_db, locality="hosted"), reranker).search(
        _A, "valve", k=5, mode="fts"
    )
    assert reranker.calls == []
    assert ({p.chunk_id for p in result.passages}, result.reranked) == ({hosted, kept}, False)


async def test_a_self_hosted_reranker_may_rank_any_base(role_db: RoleDatabase) -> None:  # noqa: F811
    await _seeded(role_db, 3, "self_hosted")
    reranker = _Reranker(locality="self_hosted")
    result = await _with(_retriever(role_db), reranker).search(_A, "valve", k=5, mode="fts")
    assert (len(reranker.calls), result.reranked) == (1, True)


async def test_the_reranker_sees_only_the_callers_passages(role_db: RoleDatabase) -> None:  # noqa: F811
    await _knowledge_db(role_db)
    await _document(role_db, await _base(role_db, _A, "hosted"), _A, ["valve note of a"])
    await _document(role_db, await _base(role_db, _B, "hosted"), _B, ["valve note of b"])
    reranker = _Reranker()
    await _with(_retriever(role_db, locality="hosted"), reranker).search(_A, "valve", k=5)
    assert [texts for _, texts in reranker.calls] == [["valve note of a"]]


async def test_nothing_found_calls_no_reranker(role_db: RoleDatabase) -> None:  # noqa: F811
    await _seeded(role_db, 2)
    reranker = _Reranker()
    result = await _with(_retriever(role_db, locality="hosted"), reranker).search(
        _A, "zebra", k=5, mode="fts"
    )
    assert (result.passages, result.reranked, reranker.calls) == ([], False, [])
