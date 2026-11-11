"""The reconcile task and the orphan-blob sweep on Postgres as the worker role (RAG-07.02).

Rows are written as the migrator and aged by moving `updated_at` or `deleted_at` back; the
task runs as the worker role, as in the worker.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import anyio
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
from neuron_agent.knowledge.reconcile import STUCK_REQUEUES, reconcile, sweep_blobs

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_AFTER = 600.0


async def _sql(db: RoleDatabase, query: str, *args: Any) -> None:
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(query, args)  # type: ignore[arg-type]


async def _document(
    db: RoleDatabase,
    kb: uuid.UUID,
    status: str,
    age: float,
    deleted: float | None = None,
    key: str | None = None,
) -> uuid.UUID:
    """A document updated `age` seconds ago, and tombstoned `deleted` seconds ago if given."""
    doc, sha, key = uuid.uuid4(), uuid.uuid4().hex * 2, key or uuid.uuid4().hex
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


# Fixed clocks on the hour's fifth and twenty-fifth minute. A deferrer that starts queues each
# task's last tick if it is at most `max_delay` (600 s) old: the ten-minute reconcile always
# has one, the hourly blob sweep (minute 23) only until minute 33.
_HOUR = 1_800_000_000
assert _HOUR % 3600 == 0
_AT_05, _AT_25 = _HOUR + 5 * 60, _HOUR + 25 * 60


async def _defer_twice(app: Any, at: float) -> None:
    """Two workers' deferrers starting at `at`, as the worker role."""
    for _ in range(2):
        deferrer = PeriodicDeferrer(registry=app.periodic_registry, max_delay=600)
        await deferrer.defer_jobs(deferrer.get_previous_tasks(at=at))


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
        await _defer_twice(app, _AT_05)
    [(task, args)] = await _jobs(db)
    assert task == jobs.Task.RECONCILE.value
    doc = await _document(db, await _base(db), "embedding", age=2 * _AFTER)
    await app.tasks[task].func(**args)
    assert await _status(db, doc) == ("queued", None)


async def test_a_worker_starting_after_the_blob_sweeps_tick_queues_it_once_too(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
    worker: tuple[str, str],  # noqa: F811
) -> None:
    # A worker restarted at minute 25 still runs that hour's sweep, once across workers.
    db, ingestor = setup
    dsn = make_conninfo(_DSN or "", dbname=db.name, user=worker[0], password=worker[1])
    app = neuron_worker.build_app(
        Settings(env="test", postgres_worker_dsn=SecretStr(dsn)), ingestor
    )
    async with app.open_async():
        await _defer_twice(app, _AT_25)
    assert sorted(await _jobs(db), key=str) == [
        (jobs.Task.RECONCILE.value, {"timestamp": _HOUR + 20 * 60}),
        (jobs.Task.SWEEP_BLOBS.value, {"timestamp": _HOUR + 23 * 60}),
    ]


async def _stored(ingestor: Ingestor, tmp_path: Path, age: float) -> str:
    """A file in the local store, last written `age` seconds ago."""

    async def body() -> AsyncIterator[bytes]:
        yield b"bytes"

    key = (await ingestor.blobs.put(body(), max_bytes=100)).key
    then = time.time() - age
    os.utime(tmp_path / "blobs" / key, (then, then))
    return key


async def test_only_old_blobs_no_row_names_are_deleted(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
    tmp_path: Path,
) -> None:
    db, ingestor = setup
    grace = 3600.0
    old_orphan = await _stored(ingestor, tmp_path, 2 * grace)
    new_orphan = await _stored(ingestor, tmp_path, grace / 2)
    live = await _stored(ingestor, tmp_path, 2 * grace)
    tombstoned = await _stored(ingestor, tmp_path, 2 * grace)
    kb = await _base(db)
    await _document(db, kb, "ready", age=0, key=live)
    await _document(db, kb, "deleting", age=0, deleted=2 * grace, key=tombstoned)
    # Not blob keys: anything else in the directory is never touched.
    others = ("README", "A" * 32, f"nested/{'a' * 32}")
    for name in others:
        (tmp_path / "blobs" / name).parent.mkdir(exist_ok=True)
        (tmp_path / "blobs" / name).write_text("operator note")
        os.utime(tmp_path / "blobs" / name, (0, 0))
    assert await sweep_blobs(ingestor.connect, ingestor.blobs, grace) == 1
    assert not await ingestor.blobs.exists(old_orphan)  # AC1
    for key in (new_orphan, live, tombstoned):  # AC3; a row of any status keeps its file
        assert await ingestor.blobs.exists(key)
    assert all((tmp_path / "blobs" / name).exists() for name in others)
    assert await sweep_blobs(ingestor.connect, ingestor.blobs, grace) == 0


class _Failing:
    """The store, with `delete` failing for one key."""

    def __init__(self, blobs: Any, key: str) -> None:
        self.blobs, self.key = blobs, key
        self.older_than = blobs.older_than

    async def delete(self, key: str) -> None:
        if key == self.key:
            raise OSError("store down")
        await self.blobs.delete(key)


async def test_a_sweep_stops_at_its_limit_and_past_a_failed_delete(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
    tmp_path: Path,
) -> None:
    db, ingestor = setup
    orphans = [await _stored(ingestor, tmp_path, 7200) for _ in range(3)]
    # A worker reading the wrong (here: empty) database deletes at most the limit per run.
    assert await sweep_blobs(ingestor.connect, ingestor.blobs, 3600, max_deletes=1) == 1
    left = [key for key in orphans if await ingestor.blobs.exists(key)]
    assert len(left) == 2
    failing = _Failing(ingestor.blobs, left[0])
    with pytest.raises(OSError, match="store down"):
        await sweep_blobs(ingestor.connect, failing, 3600)  # type: ignore[arg-type]
    assert [await ingestor.blobs.exists(key) for key in left] == [True, False]


async def test_check_blobs_reports_orphans_and_flags_live_documents_without_a_file(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
    worker: tuple[str, str],  # noqa: F811
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """RAG-07.03 AC2: a database and a store from different moments, as after a restore."""
    db, ingestor = setup
    kb, gone_kb = await _base(db), await _base(db)
    await _document(db, kb, "ready", age=0, key=await _stored(ingestor, tmp_path, 0))
    orphan = await _stored(ingestor, tmp_path, 0)
    missing = await _document(db, kb, "ready", age=0)  # no file was stored
    await _document(db, kb, "deleting", age=0, deleted=1)  # tombstoned: the purge's
    await _document(db, gone_kb, "ready", age=0)  # its base is tombstoned below
    await _sql(db, "UPDATE knowledge.bases SET deleted_at = now() WHERE kb_id = %s", gone_kb)
    (tmp_path / "blobs" / "README").write_text("operator note")
    dsn = make_conninfo(_DSN or "", dbname=db.name, user=worker[0], password=worker[1])
    settings = Settings(
        env="test",
        postgres_worker_dsn=SecretStr(dsn),
        knowledge_blob_root=str(tmp_path / "blobs"),
    )
    code = await anyio.to_thread.run_sync(neuron_worker._check_blobs, settings)
    assert code == 1
    assert json.loads(capsys.readouterr().out) == {
        "blobs": 2,
        "documents": 4,
        "orphan_blobs": 1,
        "missing_blobs": [str(missing)],
    }
    assert await ingestor.blobs.exists(orphan)  # read-only
    await _sql(db, "DELETE FROM knowledge.documents WHERE doc_id = %s", missing)
    assert await anyio.to_thread.run_sync(neuron_worker._check_blobs, settings) == 0
