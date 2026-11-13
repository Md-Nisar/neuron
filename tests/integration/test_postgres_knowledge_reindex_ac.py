"""RAG-09.04 acceptance criteria: search during a re-index, after the swap, and after a failure.

Both models are configured, as the runbook says, so the retriever could embed queries with
either; it must embed with the active profile's model only, and search that profile only.
"""

from __future__ import annotations

import uuid

import pytest
from test_postgres_knowledge_api import _Connections
from test_postgres_knowledge_ingest import (
    _OWNER,
    setup,  # noqa: F401
)
from test_postgres_knowledge_profiles import _NEW, _Other, _provider, _stored
from test_postgres_knowledge_reindex import _ready_base, _reindexer, _statuses
from test_postgres_knowledge_search import _migrator
from test_postgres_knowledge_tables import _setup, worker  # noqa: F401
from test_postgres_roles import RoleDatabase, _rows, role_db, roles  # noqa: F401

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge.ingest import Ingestor
from neuron_agent.knowledge.providers import FakeEmbeddings
from neuron_agent.knowledge.retrieval import Retriever, SearchResult
from neuron_agent.persistence import reindex
from neuron_agent.persistence.migrations import KnowledgeProfile

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]


class _OldQueries(FakeEmbeddings):
    calls = 0

    def embed_query(self, text: str) -> list[float]:
        type(self).calls += 1
        return super().embed_query(text)


class _NewQueries(_Other):
    calls = 0

    def embed_query(self, text: str) -> list[float]:
        type(self).calls += 1
        return super().embed_query(text)


async def _search(db: RoleDatabase) -> tuple[SearchResult, int, int]:
    """A dense search as the documents' owner; how many queries each model embedded."""
    old, new = _OldQueries.calls, _NewQueries.calls
    settings = Settings(env="test").model_copy(update={"knowledge_enabled": True})
    retriever = Retriever(
        settings,
        lambda: _Connections(db.app_dsn),  # type: ignore[arg-type,return-value]
        _provider(_OldQueries(1024), KnowledgeProfile()),
        reindex=_provider(_NewQueries(1024), _NEW),
    )
    result = await retriever.search(_OWNER, "were the tomatoes watered", k=3, mode="dense")
    return result, _OldQueries.calls - old, _NewQueries.calls - new


async def _two_bases(db: RoleDatabase, ingestor: Ingestor) -> tuple[uuid.UUID, uuid.UUID]:
    bases = await _ready_base(db, ingestor), await _ready_base(db, ingestor)
    for kb in bases:  # the owner's grant, which search reads, as the API writes it
        await _migrator(
            db,
            "INSERT INTO knowledge.grants (kb_id, subject_type, subject, access, granted_by)"
            " VALUES (%s, 'owner', %s, 'admin', %s)",
            kb,
            _OWNER,
            _OWNER,
        )
    return bases


async def test_while_a_reindex_runs_search_uses_the_old_profile_only(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
) -> None:
    db, ingestor = setup
    first, _ = await _two_bases(db, ingestor)
    await reindex.start(db.migrator_dsn, _NEW, "self_hosted", "allow_hosted")
    await _reindexer(ingestor, _Other(1024)).reindex_base(first)  # half way: no swap yet
    assert await _statuses(db) == [(1, "active"), (2, "building")]

    result, old, new = await _search(db)
    assert result.passages and result.path != "none"
    assert (old, new) == (1, 0)


async def test_after_the_swap_the_next_search_uses_the_new_profile_only(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
) -> None:
    db, ingestor = setup
    bases = await _two_bases(db, ingestor)
    await reindex.start(db.migrator_dsn, _NEW, "self_hosted", "allow_hosted")
    reindexer = _reindexer(ingestor, _Other(1024))
    for kb in bases:
        await reindexer.reindex_base(kb)
    assert await _statuses(db) == [(1, "retired"), (2, "active")]

    result, old, new = await _search(db)
    assert result.passages and result.path != "none"
    assert (old, new) == (0, 1)
    # The old profile is cleaned up: its vectors by the worker, its index by the next setup.
    assert await reindexer.purge_retired(batch=7) > 0
    assert list(await _stored(db)) == [2]
    await _setup(db, knowledge=True, knowledge_reindex_profile=_NEW)
    assert await _indexes(db) == ["embeddings_p2_hnsw"]


async def test_after_a_failed_reindex_the_old_profile_stays_and_the_new_one_is_cleaned_up(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
) -> None:
    db, ingestor = setup
    first, _ = await _two_bases(db, ingestor)
    await reindex.start(db.migrator_dsn, _NEW, "self_hosted", "allow_hosted")
    reindexer = _reindexer(ingestor, _Other(1024))
    await reindexer.reindex_base(first)
    await reindexer.fail("reindex_failed")  # a job that exhausted its retries
    assert await _statuses(db) == [(1, "active"), (2, "retired")]

    result, old, new = await _search(db)
    assert result.passages and (old, new) == (1, 0)
    assert await reindexer.purge_retired() > 0
    assert list(await _stored(db)) == [1]
    await _setup(db, knowledge=True)
    assert await _indexes(db) == ["embeddings_p1_hnsw"]


async def _indexes(db: RoleDatabase) -> list[str]:
    rows = await _rows(
        db.migrator_dsn,
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'knowledge'"
        " AND indexname LIKE 'embeddings_p%%_hnsw' ORDER BY 1",
    )
    return [row[0] for row in rows]
