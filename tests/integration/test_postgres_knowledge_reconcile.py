"""The reconcile task on Postgres as the worker role (RAG-07.02 AC2, AC4).

Rows are written as the migrator and aged by moving `updated_at` or `deleted_at` back; the
task runs as the worker role, as in the worker.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import psycopg
import pytest
from procrastinate.periodic import PeriodicDeferrer
from psycopg.conninfo import make_conninfo
from pydantic import SecretStr
from test_postgres_knowledge_api import _jobs
from test_postgres_knowledge_ingest import _OWNER, setup  # noqa: F401
from test_postgres_knowledge_purge import _base
from test_postgres_knowledge_tables import worker  # noqa: F401
from test_postgres_roles import _DSN, RoleDatabase, _rows, role_db, roles  # noqa: F401

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge import jobs
from neuron_agent.knowledge import worker as neuron_worker
from neuron_agent.knowledge.ingest import Ingestor
from neuron_agent.knowledge.reconcile import STUCK_REQUEUES, reconcile

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_AFTER = 600.0


async def _sql(db: RoleDatabase, query: str, *args: Any) -> None:
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(query, args)  # type: ignore[arg-type]


async def _document(
    db: RoleDatabase, kb: uuid.UUID, status: str, age: float, deleted: float | None = None
) -> uuid.UUID:
    """A document updated `age` seconds ago, and tombstoned `deleted` seconds ago if given."""
    doc, sha, key = uuid.uuid4(), uuid.uuid4().hex * 2, uuid.uuid4().hex
    await _sql(
        db,
        "INSERT INTO knowledge.documents (doc_id, kb_id, uploaded_by, title, mime_type, size_bytes,"
        " sha256, blob_key, status, updated_at, deleted_at) VALUES (%s, %s, %s, 't', 'text/plain',"
        " 1, %s, %s, %s, now() - make_interval(secs => %s), now() - make_interval(secs => %s))",
        *(doc, kb, _OWNER, sha, key, status, age, deleted),
    )
    return doc


async def _status(db: RoleDatabase, doc: uuid.UUID) -> tuple[str, str | None]:
    [row] = await _rows(
        db.migrator_dsn,
        "SELECT status, error_code FROM knowledge.documents WHERE doc_id = %s",
        (doc,),
    )
    return row[0], row[1]


async def _finish_jobs(db: RoleDatabase) -> None:
    """Every job ends `failed`, as if each ran out of attempts without moving its document."""
    await _sql(db, "UPDATE knowledge.procrastinate_jobs SET status = 'failed'")


async def test_a_stuck_document_is_requeued_then_failed_as_stalled(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
) -> None:
    db, ingestor = setup
    kb = await _base(db)
    doc = await _document(db, kb, "parsing", age=2 * _AFTER)
    for run in range(STUCK_REQUEUES + 1):
        assert await reconcile(ingestor.connect, _AFTER) == {
            "ingest_requeued": 1,
            "ingest_stalled": 0,
            "purge_requeued": 0,
        }
        assert await _status(db, doc) == ("queued", None)
        assert await _jobs(db) == [("ingest_document", {"doc_id": str(doc)})] * (run + 1)
        # The job is live: nothing is queued again, however old the row is.
        await _sql(db, "UPDATE knowledge.documents SET updated_at = now() - interval '1 day'")
        assert not any((await reconcile(ingestor.connect, _AFTER)).values())
        await _finish_jobs(db)
    counts = await reconcile(ingestor.connect, _AFTER)
    assert counts["ingest_stalled"] == 1
    assert await _status(db, doc) == ("failed", "ingest_stalled")
    assert len(await _jobs(db)) == STUCK_REQUEUES + 1


@pytest.mark.parametrize("status", ["queued", "parsing", "embedding"])
async def test_a_document_inside_the_timeout_or_terminal_is_left_alone(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
    status: str,
) -> None:
    db, ingestor = setup
    kb = await _base(db)
    recent = await _document(db, kb, status, age=_AFTER / 2)
    ready = await _document(db, kb, "ready", age=2 * _AFTER)
    failed = await _document(db, kb, "failed", age=2 * _AFTER)
    assert not any((await reconcile(ingestor.connect, _AFTER)).values())
    assert await _status(db, recent) == (status, None)
    assert [await _status(db, d) for d in (ready, failed)] == [("ready", None), ("failed", None)]
    assert await _jobs(db) == []


async def test_an_unfinished_purge_is_queued_again_once(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
) -> None:
    db, ingestor = setup
    deleted_base, live_base = await _base(db), await _base(db)
    await _document(db, deleted_base, "deleting", age=0, deleted=2 * _AFTER)
    deleted_doc = await _document(db, live_base, "deleting", age=0, deleted=2 * _AFTER)
    await _document(db, live_base, "deleting", age=0, deleted=_AFTER / 2)  # inside the timeout
    await _sql(
        db,
        "UPDATE knowledge.bases SET deleted_at = now() - interval '1 day' WHERE kb_id = %s",
        deleted_base,
    )
    assert (await reconcile(ingestor.connect, _AFTER))["purge_requeued"] == 2
    assert sorted(await _jobs(db), key=str) == sorted(
        [
            ("purge_knowledge_base", {"kb_id": str(deleted_base)}),
            ("purge_document", {"doc_id": str(deleted_doc)}),
        ],
        key=str,
    )
    # While those jobs wait, a second run queues nothing; a stuck-document scan ignores them.
    assert not any((await reconcile(ingestor.connect, _AFTER)).values())
    await _finish_jobs(db)
    assert (await reconcile(ingestor.connect, _AFTER))["purge_requeued"] == 2


async def test_the_worker_schedules_one_reconcile_run_per_tick_and_runs_it(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
    worker: tuple[str, str],  # noqa: F811
) -> None:
    db, ingestor = setup
    dsn = make_conninfo(_DSN or "", dbname=db.name, user=worker[0], password=worker[1])
    settings = Settings(env="test", postgres_worker_dsn=SecretStr(dsn)).model_copy(
        update={"worker_reconcile_after_seconds": _AFTER}
    )
    app = neuron_worker.build_app(settings, ingestor)
    async with app.open_async():
        # Two workers' deferrers for the same tick queue one job, as the worker role.
        for _ in range(2):
            deferrer = PeriodicDeferrer(registry=app.periodic_registry, max_delay=600)
            await deferrer.defer_jobs(deferrer.get_previous_tasks(at=time.time()))
    [(task, args)] = await _jobs(db)
    assert task == jobs.Task.RECONCILE.value
    doc = await _document(db, await _base(db), "embedding", age=2 * _AFTER)
    await app.tasks[task].func(**args)
    assert await _status(db, doc) == ("queued", None)
