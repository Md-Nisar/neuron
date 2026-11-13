"""The operator's re-index command (RAG-09.04): start, status and cancel, then the worker."""

from __future__ import annotations

import pytest
import structlog
from test_postgres_knowledge_ingest import setup  # noqa: F401
from test_postgres_knowledge_profiles import _NEW, _Other
from test_postgres_knowledge_reindex import _events, _ready_base, _reindexer, _statuses
from test_postgres_knowledge_search import _migrator
from test_postgres_knowledge_tables import worker  # noqa: F401
from test_postgres_roles import RoleDatabase, _rows, role_db, roles  # noqa: F401

from neuron_agent.knowledge.ingest import Ingestor
from neuron_agent.persistence import reindex
from neuron_agent.persistence.migrations import KnowledgeProfile

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]


async def _queued(db: RoleDatabase) -> list[str]:
    rows = await _rows(
        db.migrator_dsn,
        "SELECT args->>'kb_id' FROM knowledge.procrastinate_jobs"
        " WHERE task_name = 'reindex_kb' AND status = 'todo' ORDER BY 1",
    )
    return [row[0] for row in rows]


async def test_start_builds_the_profile_queues_each_live_base_and_the_worker_swaps(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
) -> None:
    db, ingestor = setup
    first, second = await _ready_base(db, ingestor), await _ready_base(db, ingestor)
    deleted = await _ready_base(db, ingestor)
    await _migrator(db, "UPDATE knowledge.bases SET deleted_at = now() WHERE kb_id = %s", deleted)

    with structlog.testing.capture_logs() as logs:
        new = await reindex.start(db.migrator_dsn, _NEW, "self_hosted", "allow_hosted")
    assert new == 2
    assert "knowledge_reindex_started" in _events(logs)
    assert await _statuses(db) == [(1, "active"), (2, "building")]
    assert await _rows(
        db.migrator_dsn,
        "SELECT indexname FROM pg_indexes WHERE indexname = 'embeddings_p2_hnsw'",
    ) == [("embeddings_p2_hnsw",)]
    assert await _queued(db) == sorted([str(first), str(second)])
    # Run again (after a start that stopped half way): resumed, with no second job per base.
    assert await reindex.start(db.migrator_dsn, _NEW, "self_hosted", "allow_hosted") == 2
    assert await _queued(db) == sorted([str(first), str(second)])
    other = KnowledgeProfile("openai_compatible", "third-embed", 1024)
    with pytest.raises(reindex.ReindexError, match="another model is running"):
        await reindex.start(db.migrator_dsn, other, "self_hosted", "allow_hosted")

    progress = await reindex.status(db.migrator_dsn)
    assert (progress.profile_id, progress.active, progress.bases, progress.covered) == (2, 1, 2, 0)
    assert progress.chunks > 0 and progress.jobs == 2

    reindexer = _reindexer(ingestor, _Other(1024))
    for kb in (first, second):
        await reindexer.reindex_base(kb)
    assert await _statuses(db) == [(1, "retired"), (2, "active")]
    assert await reindex.status(db.migrator_dsn) == reindex.Progress(None, 2)


async def test_cancel_retires_the_building_profile_and_keeps_the_active_one(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
) -> None:
    db, ingestor = setup
    await _ready_base(db, ingestor)
    await reindex.start(db.migrator_dsn, _NEW, "self_hosted", "allow_hosted")
    with structlog.testing.capture_logs() as logs:
        assert await reindex.cancel(db.migrator_dsn) == 2
    assert "knowledge_reindex_failed" in _events(logs)
    assert await _statuses(db) == [(1, "active"), (2, "retired")]
    assert await reindex.cancel(db.migrator_dsn) is None
    # A later re-index takes the next id.
    assert await reindex.start(db.migrator_dsn, _NEW, "self_hosted", "allow_hosted") == 3


@pytest.mark.parametrize(
    ("policy", "processing", "message"),
    [
        ("self_hosted_only", "hosted", "policy forbids"),
        ("allow_hosted", "self_hosted", "self-hosted only"),
    ],
)
async def test_start_refuses_a_hosted_model_a_base_or_the_policy_forbids(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
    policy: str,
    processing: str,
    message: str,
) -> None:
    db, ingestor = setup
    await _ready_base(db, ingestor, processing=processing)
    with pytest.raises(reindex.ReindexError, match=message):
        await reindex.start(db.migrator_dsn, _NEW, "hosted", policy)
    assert await _statuses(db) == [(1, "active")]


async def test_start_refuses_the_active_model(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
) -> None:
    db, _ = setup
    with pytest.raises(reindex.ReindexError, match="active model already"):
        await reindex.start(db.migrator_dsn, KnowledgeProfile(), "self_hosted", "allow_hosted")
