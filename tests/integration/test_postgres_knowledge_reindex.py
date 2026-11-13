"""The re-index job and swap (RAG-09.04, ADR 0014 amendment "re-index to a new profile")."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence

import psycopg
import pytest
import structlog
from test_postgres_knowledge_ingest import _document as _queued
from test_postgres_knowledge_ingest import setup  # noqa: F401
from test_postgres_knowledge_profiles import _NEW, _new_profile, _Other, _provider, _stored
from test_postgres_knowledge_search import _migrator
from test_postgres_knowledge_tables import worker  # noqa: F401
from test_postgres_roles import RoleDatabase, _rows, role_db, roles  # noqa: F401

from neuron_agent.knowledge.chunking import estimate_tokens
from neuron_agent.knowledge.ingest import PROFILES, Ingestor
from neuron_agent.knowledge.reindex import Reindexer, ReindexRefusedError

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]


class _Counted(_Other):
    calls = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        type(self).calls += len(texts)
        return super().embed_documents(texts)


def _reindexer(ingestor: Ingestor, embeddings: _Other, locality: str = "self_hosted") -> Reindexer:
    return Reindexer(
        connect=ingestor.connect,
        embeddings=ingestor.embeddings,
        reindex=_provider(embeddings, _NEW, locality),  # type: ignore[arg-type]
        policy="allow_hosted",
    )


async def _ready_base(
    db: RoleDatabase, ingestor: Ingestor, processing: str = "self_hosted"
) -> uuid.UUID:
    doc = await _queued(db, ingestor, processing=processing)
    assert await ingestor.ingest(doc) == "ready"
    [(kb,)] = await _rows(
        db.migrator_dsn, "SELECT kb_id FROM knowledge.documents WHERE doc_id = %s", (doc,)
    )
    return kb


async def _statuses(db: RoleDatabase) -> list[tuple[int, str]]:
    return await _rows(
        db.migrator_dsn, "SELECT profile_id, status FROM knowledge.index_profiles ORDER BY 1"
    )


def _events(logs: Sequence[dict[str, object]]) -> list[object]:
    return [log["event"] for log in logs if log.get("audit")]


async def test_each_base_is_embedded_once_and_the_last_one_swaps(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
) -> None:
    db, ingestor = setup
    first, second = await _ready_base(db, ingestor), await _ready_base(db, ingestor)
    await _new_profile(db)
    reindexer = _reindexer(ingestor, _Counted(1024))

    assert await reindexer.reindex_base(first) == 1
    embedded = _Counted.calls
    assert embedded > 0
    # The second base is not covered yet: the old profile stays, and the base gets a job.
    assert await _statuses(db) == [(1, "active"), (2, "building")]
    assert await _rows(
        db.migrator_dsn,
        "SELECT args->>'kb_id' FROM knowledge.procrastinate_jobs WHERE task_name = 'reindex_kb'",
    ) == [(str(second),)]
    # A retry of a covered base embeds nothing again.
    assert await reindexer.reindex_base(first) == 0
    assert _Counted.calls == embedded

    with structlog.testing.capture_logs() as logs:
        assert await reindexer.reindex_base(second) == 1
    assert await _statuses(db) == [(1, "retired"), (2, "active")]
    assert await _rows(db.migrator_dsn, "SELECT DISTINCT profile_id FROM knowledge.bases") == [(2,)]
    assert "knowledge_reindex_swapped" in _events(logs)
    stored = await _stored(db)
    assert len(stored[2]) == len(stored[1])
    # The re-index's tokens are charged to the documents, beside their first ingestion's.
    once = sum(estimate_tokens(passage) for _, passage in stored[1])
    assert await _rows(
        db.migrator_dsn, "SELECT sum(embedding_tokens)::int FROM knowledge.documents"
    ) == [(2 * once,)]


async def test_a_base_whose_setting_forbids_the_model_fails_the_reindex(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
) -> None:
    db, ingestor = setup
    kb = await _ready_base(db, ingestor, processing="self_hosted")
    await _new_profile(db)
    reindexer = _reindexer(ingestor, _Other(1024), locality="hosted")
    with pytest.raises(ReindexRefusedError):
        await reindexer.reindex_base(kb)
    with structlog.testing.capture_logs() as logs:
        await reindexer.fail("processing_locality_forbidden")
    # The old profile was active throughout; the building one is retired, never swapped.
    assert await _statuses(db) == [(1, "active"), (2, "retired")]
    assert "knowledge_reindex_failed" in _events(logs)
    assert list(await _stored(db)) == [1]
    assert await reindexer.swap() is False


async def test_without_a_building_profile_the_job_does_nothing(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
) -> None:
    db, ingestor = setup
    kb = await _ready_base(db, ingestor)
    reindexer = _reindexer(ingestor, _Other(1024))
    assert await reindexer.reindex_base(kb) == 0
    assert await reindexer.swap() is False
    assert await _statuses(db) == [(1, "active")]


async def test_the_swap_waits_for_an_ingestion_write_that_holds_the_profiles(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
) -> None:
    """An upload's write, which holds the profiles `FOR SHARE`, commits before the swap."""
    db, ingestor = setup
    kb = await _ready_base(db, ingestor)
    await _new_profile(db)
    reindexer = _reindexer(ingestor, _Other(1024))
    assert await reindexer.reindex_base(kb) == 1  # covered, and swapped at the end
    await _new_profile(db, "building")
    await _migrator(
        db, "UPDATE knowledge.index_profiles SET status = 'active' WHERE profile_id = 1"
    )
    await _migrator(db, "UPDATE knowledge.bases SET profile_id = 1")
    # Profile 1 active and profile 2 building again, every chunk covered by both.
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn) as writer:
        await writer.execute(PROFILES + " FOR SHARE")
        swap = asyncio.create_task(reindexer.swap())
        await asyncio.sleep(0.5)
        assert not swap.done()
        await writer.commit()
    assert await asyncio.wait_for(swap, 10) is True
    assert await _statuses(db) == [(1, "retired"), (2, "active")]
