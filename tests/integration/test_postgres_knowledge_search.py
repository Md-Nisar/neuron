"""Hybrid search on Postgres, as the app role under row-level security (RAG-04.01).

Chunks are seeded as the migrator with fake embeddings of their own text, so a query equal to a
chunk's text is a perfect dense match and any other query is a random one.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import openai
import psycopg
import pytest
from psycopg import sql
from psycopg.rows import dict_row
from test_postgres_knowledge_api import _Connections
from test_postgres_knowledge_tables import _knowledge_db
from test_postgres_roles import RoleDatabase, role_db, roles  # noqa: F401

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge import retrieval
from neuron_agent.knowledge.ingest import _vector
from neuron_agent.knowledge.providers import EmbeddingError, EmbeddingProvider, FakeEmbeddings
from neuron_agent.knowledge.retrieval import Retriever, fuse

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_A, _B = "a" * 64, "b" * 64
_FAKE = FakeEmbeddings(1024)


def _retriever(db: RoleDatabase, *, locality: Any = "self_hosted", **update: Any) -> Retriever:
    settings = Settings(env="test").model_copy(update={"knowledge_enabled": True, **update})
    provider = EmbeddingProvider(
        _FAKE, _FAKE, dimensions=1024, locality=locality, batch_size=8, max_retries=0
    )
    return Retriever(settings, lambda: _Connections(db.app_dsn), provider)  # type: ignore[arg-type,return-value]


async def _base(db: RoleDatabase, owner: str, processing: str = "self_hosted") -> uuid.UUID:
    kb = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO knowledge.bases (kb_id, owner_key, name, processing, profile_id)"
            " VALUES (%s, %s, 'kb', %s, 1)",
            (kb, owner, processing),
        )
        await conn.execute(
            "INSERT INTO knowledge.grants (kb_id, subject_type, subject, access, granted_by)"
            " VALUES (%s, 'owner', %s, 'admin', %s)",
            (kb, owner, owner),
        )
    return kb


async def _document(
    db: RoleDatabase, kb: uuid.UUID, owner: str, texts: list[str], status: str = "ready"
) -> list[uuid.UUID]:
    """A document in `kb` with one chunk and embedding per text; returns the chunk ids."""
    doc, chunks = uuid.uuid4(), [uuid.uuid4() for _ in texts]
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO knowledge.documents (doc_id, kb_id, uploaded_by, title, mime_type,"
            " size_bytes, sha256, blob_key, status) VALUES (%s, %s, %s, 'doc', 'text/plain', 1,"
            " %s, 'k', %s)",
            (doc, kb, owner, uuid.uuid4().hex * 2, status),
        )
        for ordinal, (chunk, text) in enumerate(zip(chunks, texts, strict=True)):
            await conn.execute(
                "INSERT INTO knowledge.chunks (chunk_id, doc_id, kb_id, ordinal, text,"
                " token_count, ts_config) VALUES (%s, %s, %s, %s, %s, 1, 'simple')",
                (chunk, doc, kb, ordinal, text),
            )
            await conn.execute(
                "INSERT INTO knowledge.embeddings (chunk_id, profile_id, kb_id, embedding)"
                " VALUES (%s, 1, %s, %s)",
                (chunk, kb, _vector(_FAKE.embed_query(text))),
            )
    return chunks


async def _migrator(db: RoleDatabase, statement: str, *params: object) -> None:
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(statement, params)  # type: ignore[arg-type]


def test_rrf_adds_reciprocal_ranks() -> None:
    a, b, c = (uuid.UUID(int=n) for n in range(3))
    fused = fuse([[a, b], [b, c]])
    assert [item for item, _ in fused] == [b, a, c]
    assert fused[0][1] == pytest.approx(1 / 62 + 1 / 61)


@pytest.mark.parametrize("mode", ["hybrid", "dense", "fts"])
async def test_each_user_sees_only_their_own_chunk(role_db: RoleDatabase, mode: Any) -> None:  # noqa: F811
    await _knowledge_db(role_db)
    text = "The falcon plan launches on the first of March."
    own = {
        owner: (await _document(role_db, await _base(role_db, owner), owner, [text]))[0]
        for owner in (_A, _B)
    }
    for owner in (_A, _B):
        result = await _retriever(role_db).search(owner, text, k=5, mode=mode)
        assert [p.chunk_id for p in result.passages] == [own[owner]]
    # No grant, no base: nothing at all.
    assert (await _retriever(role_db).search("c" * 64, text, k=5)).status == "no_relevant_results"


async def test_the_scope_does_not_outlive_the_search(role_db: RoleDatabase) -> None:  # noqa: F811
    await _knowledge_db(role_db)
    await _document(role_db, await _base(role_db, _A), _A, ["shared connection"])
    async with await psycopg.AsyncConnection.connect(
        role_db.app_dsn, autocommit=True, row_factory=dict_row
    ) as conn:

        class _One:
            @asynccontextmanager
            async def connection(self) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
                yield conn

        retriever = _retriever(role_db)
        retriever._pool = lambda: _One()  # type: ignore[assignment,return-value]
        assert (await retriever.search(_A, "shared connection", k=1)).passages
        row = await (
            await conn.execute("SELECT current_setting('neuron.kb_ids', true) AS s")
        ).fetchone()
        assert row is not None and not row["s"]
        assert (
            await (await conn.execute("SELECT count(*) AS n FROM knowledge.chunks")).fetchone()
        ) == {"n": 0}


async def test_a_small_base_returns_k_results(role_db: RoleDatabase) -> None:  # noqa: F811
    await _knowledge_db(role_db)
    kb = await _base(role_db, _A)
    await _document(role_db, kb, _A, [f"passage number {n}" for n in range(30)])
    # An off-topic query and no floor: the exact scan ranks every row, so k return.
    retriever = _retriever(role_db, knowledge_search_min_similarity=-1.0)
    result = await retriever.search(_A, "zebra quantum orchid", k=20, mode="dense")
    assert result.path == "exact"
    assert len(result.passages) == 20
    assert len({p.chunk_id for p in result.passages}) == 20


async def test_an_exact_identifier_is_found_through_full_text(role_db: RoleDatabase) -> None:  # noqa: F811
    await _knowledge_db(role_db)
    kb = await _base(role_db, _A)
    [target, *_] = await _document(
        role_db, kb, _A, ["Fault code ERR-7741-ZQ trips the pump.", "The pump runs at night."]
    )
    # A floor no random vector reaches: the dense path contributes nothing.
    retriever = _retriever(role_db, knowledge_search_min_similarity=0.99)
    assert (await retriever.search(_A, "ERR-7741-ZQ", k=5, mode="dense")).passages == []
    result = await retriever.search(_A, "ERR-7741-ZQ", k=5)
    assert result.path == "exact"
    assert [p.chunk_id for p in result.passages] == [target]


@pytest.mark.parametrize("threshold", [10_000, 0], ids=["exact", "hnsw"])
async def test_tombstoned_and_failed_documents_never_return(
    role_db: RoleDatabase,  # noqa: F811
    threshold: int,
) -> None:
    await _knowledge_db(role_db)
    text = "identical passage in every document"
    kb, gone = await _base(role_db, _A), await _base(role_db, _A)
    [live] = await _document(role_db, kb, _A, [text])
    await _document(role_db, kb, _A, [text], status="failed")
    await _document(role_db, kb, _A, [text], status="embedding")
    [tombstoned] = await _document(role_db, kb, _A, [text])
    await _migrator(
        role_db,
        "UPDATE knowledge.documents SET deleted_at = now(), status = 'deleting'"
        " WHERE doc_id = (SELECT doc_id FROM knowledge.chunks WHERE chunk_id = %s)",
        tombstoned,
    )
    await _document(role_db, gone, _A, [text])
    await _migrator(role_db, "UPDATE knowledge.bases SET deleted_at = now() WHERE kb_id = %s", gone)
    retriever = _retriever(role_db, knowledge_exact_scan_max_chunks=threshold)
    for mode in ("hybrid", "dense", "fts"):
        result = await retriever.search(_A, text, k=10, mode=mode)  # type: ignore[arg-type]
        assert [p.chunk_id for p in result.passages] == [live], mode
    assert (await retriever.search(_A, text, k=10, mode="dense")).path == (
        "exact" if threshold else "hnsw"
    )


async def test_a_base_kept_off_hosted_processing_is_searched_by_text_only(
    role_db: RoleDatabase,  # noqa: F811
) -> None:
    await _knowledge_db(role_db)
    kb = await _base(role_db, _A, processing="self_hosted")
    [chunk] = await _document(role_db, kb, _A, ["greenhouse valve schedule"])
    result = await _retriever(role_db, locality="hosted").search(_A, "valve", k=5)
    assert (result.path, [p.chunk_id for p in result.passages]) == ("none", [chunk])


class _Counting(FakeEmbeddings):
    """Fake query vectors, counted; `fail` raises the provider's outage code instead."""

    def __init__(self, *, fail: bool = False) -> None:
        super().__init__(1024)
        self.calls, self.fail = 0, fail

    def embed_query(self, text: str) -> list[float]:
        self.calls += 1
        if self.fail:
            raise openai.APIConnectionError(request=httpx.Request("POST", "http://embed"))
        return super().embed_query(text)


async def test_only_bases_allowed_hosted_processing_are_searched_by_meaning(
    role_db: RoleDatabase,  # noqa: F811
) -> None:
    await _knowledge_db(role_db)
    text = "the same sentence in two bases"
    [kept] = await _document(role_db, await _base(role_db, _A, "self_hosted"), _A, [text])
    [hosted] = await _document(role_db, await _base(role_db, _A, "hosted"), _A, [text])
    for policy, dense, calls in (("allow_hosted", [hosted], 1), ("self_hosted_only", [], 0)):
        counting = _Counting()
        retriever = _retriever(role_db, locality="hosted", knowledge_processing_policy=policy)
        retriever._embeddings = EmbeddingProvider(
            counting, counting, dimensions=1024, locality="hosted", batch_size=8, max_retries=0
        )
        result = await retriever.search(_A, text, k=5, mode="dense")
        assert ([p.chunk_id for p in result.passages], counting.calls) == (dense, calls)
        # Full text still searches both.
        hybrid = await retriever.search(_A, text, k=5)
        assert {p.chunk_id for p in hybrid.passages} == {kept, hosted}


async def test_hybrid_falls_back_to_full_text_when_the_provider_is_down(
    role_db: RoleDatabase,  # noqa: F811
) -> None:
    await _knowledge_db(role_db)
    [chunk] = await _document(role_db, await _base(role_db, _A), _A, ["pump fault table"])
    failing = _Counting(fail=True)
    retriever = _retriever(role_db)
    retriever._embeddings = EmbeddingProvider(
        failing, failing, dimensions=1024, locality="self_hosted", batch_size=8, max_retries=0
    )
    result = await retriever.search(_A, "pump", k=5)
    assert (result.path, [p.chunk_id for p in result.passages]) == ("none", [chunk])
    with pytest.raises(EmbeddingError):
        await retriever.search(_A, "pump", k=5, mode="dense")


@pytest.mark.parametrize(
    ("query", "k"), [("", 5), ("   ", 5), ("x" * 2_001, 5), ("q", 0), ("q", 51), ("q", -1)]
)
async def test_out_of_range_searches_are_refused(role_db: RoleDatabase, query: str, k: int) -> None:  # noqa: F811
    with pytest.raises(ValueError, match="search needs"):
        await _retriever(role_db).search(_A, query, k=k)


async def _plan(db: RoleDatabase, query: Any, params: dict[str, Any], *setup: str) -> str:
    """The plan of `query` after `setup`, as the app role."""
    statement = sql.SQL("EXPLAIN ") + (sql.SQL(query) if isinstance(query, str) else query)
    async with await psycopg.AsyncConnection.connect(db.app_dsn) as conn, conn.transaction():
        for step in setup:
            await conn.execute(step)  # type: ignore[arg-type]
        rows = await (await conn.execute(statement, params)).fetchall()
    return "\n".join(row[0] for row in rows)


async def test_the_code_forces_the_dense_path_it_chose(role_db: RoleDatabase) -> None:  # noqa: F811
    await _knowledge_db(role_db)
    kb = await _base(role_db, _A)
    await _document(role_db, kb, _A, [f"chunk {n}" for n in range(200)])
    await _migrator(role_db, "ANALYZE knowledge.embeddings")
    params = {
        "owner": _A,
        "kbs": [kb],
        "v": _vector(_FAKE.embed_query("chunk 7")),
        "n": retrieval.CANDIDATES,
        "profile": 1,
    }
    retriever = _retriever(role_db)
    hnsw = await _plan(role_db, retriever.ann_query(), params, retrieval._ANN_SETTINGS)
    exact = await _plan(
        role_db, retrieval._EXACT, params, retrieval._ANN_SETTINGS, "SET LOCAL enable_seqscan = off"
    )
    assert "embeddings_p1_hnsw" in hnsw
    # Even with every other path priced out, the exact query cannot use the HNSW index.
    assert "hnsw" not in exact
