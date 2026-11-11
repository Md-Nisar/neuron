"""Erase and export include knowledge (RAG-07.01), on Postgres as the app and worker roles.

The erase tombstones and queues the purge (as the app role); the purge itself runs as the worker
role through `Purger`, as the worker would run the queued jobs.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import psycopg
import pytest
from test_postgres_knowledge_api import (  # noqa: F401
    _SCOPES,
    _Connections,
    _create,
    _document,
    _jobs,
    api,
)
from test_postgres_knowledge_ingest import _TEXT, setup  # noqa: F401
from test_postgres_knowledge_tables import worker  # noqa: F401
from test_postgres_roles import RoleDatabase, _rows, role_db, roles  # noqa: F401
from tests.conftest import JwtApi, bearer

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge.ingest import Ingestor
from neuron_agent.knowledge.purge import Purger
from neuron_agent.knowledge.service import KnowledgeBases

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_ALICE, _BOB = "a" * 64, "b" * 64


def _service(db: RoleDatabase) -> KnowledgeBases:
    return KnowledgeBases(
        Settings(env="test").model_copy(update={"knowledge_enabled": True}),
        lambda: _Connections(db.app_dsn),  # type: ignore[arg-type,return-value]
    )


async def _ingested(db: RoleDatabase, ingestor: Ingestor, owner: str, documents: int) -> uuid.UUID:
    """A base of `owner`'s with `documents` ready documents: rows, chunks, embeddings, files."""
    kb = await _service(db).create(owner, f"kb {uuid.uuid4().hex[:6]}", "self_hosted")
    for n in range(documents):

        async def body(n: int = n) -> AsyncIterator[bytes]:
            yield f"{_TEXT}\n\nCopy {n}.".encode()

        blob, doc = await ingestor.blobs.put(body(), max_bytes=1_000_000), uuid.uuid4()
        async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as c:
            await c.execute(
                "INSERT INTO knowledge.documents (doc_id, kb_id, uploaded_by, title, mime_type,"
                " size_bytes, sha256, blob_key, status) VALUES (%s, %s, %s, 't', 'text/plain',"
                " %s, %s, %s, 'queued')",
                (doc, kb.kb_id, owner, blob.size, blob.sha256, blob.key),
            )
        assert await ingestor.ingest(doc) == "ready"
    return kb.kb_id


async def _stored(db: RoleDatabase, owner: str) -> dict[str, int]:
    """`owner`'s rows in each knowledge table (through their bases and documents)."""
    queries = {
        "bases": "SELECT count(*) FROM knowledge.bases WHERE owner_key = %s",
        "grants": "SELECT count(*) FROM knowledge.grants WHERE subject = %s",
        "documents": "SELECT count(*) FROM knowledge.documents WHERE uploaded_by = %s",
        "chunks": "SELECT count(*) FROM knowledge.chunks c JOIN knowledge.documents d"
        " USING (doc_id) WHERE d.uploaded_by = %s",
        "embeddings": "SELECT count(*) FROM knowledge.embeddings e JOIN knowledge.chunks c"
        " USING (chunk_id) JOIN knowledge.documents d ON d.doc_id = c.doc_id"
        " WHERE d.uploaded_by = %s",
    }
    return {name: (await _rows(db.migrator_dsn, q, (owner,)))[0][0] for name, q in queries.items()}


def _files(tmp_path: Path) -> int:
    return sum(path.is_file() for path in (tmp_path / "blobs").rglob("*"))


async def _purge_queued(db: RoleDatabase, ingestor: Ingestor) -> None:
    """Run every queued base purge, as the worker would."""
    purger = Purger(ingestor.connect, ingestor.blobs)
    for task, args in await _jobs(db):
        assert task == "purge_knowledge_base"
        await purger.purge_base(uuid.UUID(args["kb_id"]))


async def test_after_the_purge_nothing_of_the_owner_remains_and_only_then_complete(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
    tmp_path: Path,
) -> None:
    db, ingestor = setup
    alice = [await _ingested(db, ingestor, _ALICE, n) for n in (2, 1)]
    bob = await _ingested(db, ingestor, _BOB, 1)
    bobs = await _stored(db, _BOB)
    service = _service(db)

    first = await service.erase(_ALICE)
    # AC2: tombstoned now, the purge still to run: not complete.
    assert (first.erased_base_count, first.erased_document_count) == (2, 3)
    assert (first.purge_pending, first.complete) == (True, False)
    assert sorted(args["kb_id"] for _, args in await _jobs(db)) == sorted(map(str, alice))
    assert await service.list(_ALICE) == []
    assert await service.export(_ALICE) == []
    # A repeat before the purge erases nothing new and queues no second purge.
    again = await service.erase(_ALICE)
    assert (again.erased_base_count, again.erased_document_count, again.complete) == (0, 0, False)
    assert len(await _jobs(db)) == 2

    await _purge_queued(db, ingestor)
    # AC1: no row and no file of Alice's is left; Bob's are untouched.
    assert await _stored(db, _ALICE) == dict.fromkeys(bobs, 0)
    assert _files(tmp_path) == 1
    assert await _stored(db, _BOB) == bobs
    assert [b.kb_id for b in await service.list(_BOB)] == [bob]
    done = await service.erase(_ALICE)
    assert (done.erased_base_count, done.purge_pending, done.complete) == (0, False, True)
    assert len(await _jobs(db)) == 2


async def test_a_repeat_erase_requeues_a_purge_that_used_all_its_attempts(
    setup: tuple[RoleDatabase, Ingestor],  # noqa: F811
    tmp_path: Path,
) -> None:
    db, ingestor = setup
    await _ingested(db, ingestor, _ALICE, 1)
    service = _service(db)
    await service.erase(_ALICE)
    await _rows(
        db.migrator_dsn,
        "UPDATE knowledge.procrastinate_jobs SET status = 'failed' RETURNING id",
    )
    retried = await service.erase(_ALICE)
    assert (retried.erased_base_count, retried.complete) == (0, False)
    assert len(await _jobs(db)) == 2
    await _purge_queued(db, ingestor)
    assert (await service.erase(_ALICE)).complete is True
    assert _files(tmp_path) == 0


async def test_export_and_erase_everything_include_knowledge(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db = api
    settings = client.settings.model_copy(update={"knowledge_enabled": True})
    connections = _Connections(db.app_dsn)
    monkeypatch.setattr(client.service, "_settings", settings)
    monkeypatch.setattr(
        client.service,
        "_knowledge",
        KnowledgeBases(settings, lambda: connections),  # type: ignore[arg-type,return-value]
    )
    alice = make_token("alice", scopes=f"{_SCOPES} threads:read data:erase")
    bob = make_token("bob", scopes=f"{_SCOPES} threads:read")
    kept = _create(client, alice, "Taxes")
    _create(client, alice, "Empty")
    doc = await _document(db, kept["kb_id"])
    gone = await _document(db, kept["kb_id"], "Deleted")
    response = client.client.delete(f"/v1/knowledge/documents/{gone}", headers=bearer(alice))
    assert response.status_code == 202
    bobs = _create(client, bob, "Bob's")

    # AC3: bases and their live documents, with ids, names, sizes and status; no file content.
    exported = client.client.get("/v1/me/export", headers=bearer(alice)).json()
    bases: list[dict[str, Any]] = exported["knowledge_bases"]
    assert [(b["kb_id"], b["name"]) for b in bases] == [
        (kept["kb_id"], "Taxes"),
        (bases[1]["kb_id"], "Empty"),
    ]
    [document] = bases[0]["documents"]
    assert (document["doc_id"], document["title"], document["size_bytes"]) == (
        doc,
        "Alice's tax return",
        3,
    )
    assert (document["status"], bases[1]["documents"]) == ("queued", [])
    assert bobs["kb_id"] not in str(exported)
    later = client.client.get("/v1/me/export?offset=5", headers=bearer(alice)).json()
    assert later["knowledge_bases"] == []

    # Erase-everything tombstones the knowledge too, and is not complete until the purge ran.
    erased = client.client.delete("/v1/me/threads", headers=bearer(alice)).json()
    assert erased["knowledge"] == {
        "erased_base_count": 2,
        "erased_document_count": 1,
        "purge_pending": True,
        "complete": False,
    }
    assert erased["complete"] is False
    route = client.client.delete("/v1/me/knowledge", headers=bearer(alice))
    assert (route.status_code, route.json()["erased_base_count"], route.json()["complete"]) == (
        200,
        0,
        False,
    )
    # The purge, as the worker leaves it; Bob's base stays.
    await _rows(
        db.migrator_dsn,
        "DELETE FROM knowledge.bases WHERE deleted_at IS NOT NULL RETURNING kb_id",
    )
    done = client.client.delete("/v1/me/threads", headers=bearer(alice)).json()
    assert (done["knowledge"]["purge_pending"], done["complete"]) == (False, True)
    listed = client.client.get("/v1/knowledge/bases", headers=bearer(bob)).json()["bases"]
    assert [b["kb_id"] for b in listed] == [bobs["kb_id"]]
