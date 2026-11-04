"""The purge tasks on Postgres as the worker role (RAG-03.03 AC2).

Documents are ingested first (fake embeddings, the plain-text parser, a local blob store), so a
purge has chunks, embeddings and files to remove; the base is deleted through the API's service.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import anyio
import psycopg
import pytest
from test_postgres_knowledge_api import _Connections, _jobs
from test_postgres_knowledge_ingest import _OWNER, _TEXT, setup  # noqa: F401
from test_postgres_knowledge_tables import worker  # noqa: F401
from test_postgres_roles import RoleDatabase, _rows, role_db, roles  # noqa: F401

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge import service as knowledge_service
from neuron_agent.knowledge.blobs import BlobStore
from neuron_agent.knowledge.ingest import Ingestor
from neuron_agent.knowledge.purge import Purger
from neuron_agent.knowledge.service import KnowledgeBases

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_TABLES = ("bases", "grants", "documents", "chunks", "embeddings")


async def _base(db: RoleDatabase) -> uuid.UUID:
    kb = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO knowledge.bases (kb_id, owner_key, name, profile_id)"
            " VALUES (%s, %s, 'kb', 1)",
            (kb, _OWNER),
        )
        await conn.execute(
            "INSERT INTO knowledge.grants (kb_id, subject_type, subject, access, granted_by)"
            " VALUES (%s, 'owner', %s, 'admin', %s)",
            (kb, _OWNER, _OWNER),
        )
    return kb


async def _ingested(db: RoleDatabase, ingestor: Ingestor, kb: uuid.UUID, n: int) -> uuid.UUID:
    """A ready document in `kb`, with its file, chunks and embeddings."""

    async def body() -> AsyncIterator[bytes]:
        yield f"{_TEXT}\n\nCopy {n}.".encode()

    blob, doc = await ingestor.blobs.put(body(), max_bytes=1_000_000), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO knowledge.documents (doc_id, kb_id, uploaded_by, title, mime_type,"
            " size_bytes, sha256, blob_key, status) VALUES (%s, %s, %s, 't', 'text/plain', %s,"
            " %s, %s, 'queued')",
            (doc, kb, _OWNER, blob.size, blob.sha256, blob.key),
        )
    assert await ingestor.ingest(doc) == "ready"
    return doc


async def _left(db: RoleDatabase, tmp_path: Path) -> dict[str, int]:
    """Rows in each knowledge table and files in the store."""
    counts = {
        table: (await _rows(db.migrator_dsn, f"SELECT count(*) FROM knowledge.{table}"))[0][0]  # noqa: S608
        for table in _TABLES
    }
    return {**counts, "files": sum(p.is_file() for p in (tmp_path / "blobs").rglob("*"))}


def _service(db: RoleDatabase) -> KnowledgeBases:
    return KnowledgeBases(
        Settings(env="test").model_copy(update={"knowledge_enabled": True}),
        lambda: _Connections(db.app_dsn),  # type: ignore[arg-type,return-value]
    )


class _Crashing:
    """A store whose `delete` raises on call `at`, after deleting the file when `after`."""

    def __init__(self, blobs: BlobStore, at: int, *, after: bool) -> None:
        self._blobs, self._at, self._after, self.calls = blobs, at, after, 0

    async def delete(self, key: str) -> None:
        self.calls += 1
        if self.calls == self._at and not self._after:
            raise OSError("store down")
        await self._blobs.delete(key)
        if self.calls == self._at:
            raise OSError("crashed before the row was deleted")


@pytest.mark.parametrize("after", [False, True])
async def test_a_purge_stopped_half_way_completes_on_retry(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
    tmp_path: Path,
    after: bool,
) -> None:
    db, ingestor = setup
    kb = await _base(db)
    for n in range(3):
        await _ingested(db, ingestor, kb, n)
    await _service(db).delete(_OWNER, kb)
    assert await _rows(
        db.migrator_dsn, "SELECT DISTINCT status, deleted_at IS NOT NULL FROM knowledge.documents"
    ) == [("deleting", True)]
    assert await _jobs(db) == [("purge_knowledge_base", {"kb_id": str(kb)})]
    crashing = _Crashing(ingestor.blobs, 2, after=after)
    with pytest.raises(OSError):
        await Purger(ingestor.connect, crashing).purge_base(kb)  # type: ignore[arg-type]
    left = await _left(db, tmp_path)
    # The others were purged past the failure; the base waits for the retry.
    assert (left["bases"], left["documents"], left["files"]) == (1, 1, 1 - after)
    # The retry finds the rest; a file the crash already deleted counts as deleted.
    assert await Purger(ingestor.connect, ingestor.blobs).purge_base(kb) == 1
    assert await _left(db, tmp_path) == dict.fromkeys((*_TABLES, "files"), 0)
    assert await Purger(ingestor.connect, ingestor.blobs).purge_base(kb) == 0


async def test_only_a_tombstoned_document_is_purged(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
    tmp_path: Path,
) -> None:
    db, ingestor = setup
    kb = await _base(db)
    kept, doomed = [await _ingested(db, ingestor, kb, n) for n in range(2)]
    purger = Purger(ingestor.connect, ingestor.blobs)
    # A live document or base: a forged or early job removes nothing.
    assert await purger.purge_document(kept) == 0
    assert await purger.purge_base(kb) == 0
    full = await _left(db, tmp_path)
    await _rows(
        db.migrator_dsn,
        "UPDATE knowledge.documents SET deleted_at = now(), status = 'deleting'"
        " WHERE doc_id = %s RETURNING 1",
        (doomed,),
    )
    assert await purger.purge_document(doomed) == 1
    assert await purger.purge_document(doomed) == 0
    chunks: list[Any] = await _rows(db.migrator_dsn, "SELECT DISTINCT doc_id FROM knowledge.chunks")
    assert chunks == [(kept,)]
    left = await _left(db, tmp_path)
    assert left == {
        **full,
        "documents": 1,
        "files": 1,
        "chunks": left["chunks"],
        "embeddings": left["chunks"],
    }
    assert 0 < left["chunks"] < full["chunks"]


async def test_an_upload_committing_during_the_base_delete_is_tombstoned_with_it(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
) -> None:
    db, _ = setup
    kb, doc = await _base(db), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(db.app_dsn) as upload:
        await upload.execute(
            knowledge_service._INSERT_DOCUMENT,
            {
                "doc": doc,
                "owner": _OWNER,
                "title": "t",
                "mime": "text/plain",
                "size": 1,
                "sha": "a" * 64,
                "blob": "b" * 32,
                "key": None,
                "kb": kb,
            },
        )
        async with anyio.create_task_group() as tasks:
            tasks.start_soon(_service(db).delete, _OWNER, kb)
            await anyio.sleep(0.5)  # the delete now waits on the upload's lock on the base
            await upload.commit()
    assert await _rows(
        db.migrator_dsn,
        "SELECT status, deleted_at IS NOT NULL FROM knowledge.documents WHERE doc_id = %s",
        (doc,),
    ) == [("deleting", True)]
