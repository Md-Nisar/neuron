"""Per-user ingestion quotas at upload, on Postgres (RAG-02.05, ADR 0014 requirement 7).

A refused upload stores no file, no row and no job, so the owner's usage is unchanged.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import anyio
import pytest
from test_postgres_knowledge_api import _PDF, _blobs, _create, _jobs, _upload, api  # noqa: F401
from test_postgres_roles import RoleDatabase, _rows, role_db, roles  # noqa: F401
from tests.conftest import JwtApi, bearer

from neuron_agent.api import main as api_main
from neuron_agent.errors.base import UploadRefusedError
from neuron_agent.knowledge.blobs import StoredBlob

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_SCOPES = "knowledge:read knowledge:write"


def _quota(monkeypatch: pytest.MonkeyPatch, **limits: int) -> None:
    knowledge = api_main.knowledge
    update = {f"knowledge_max_{name}_per_user": value for name, value in limits.items()}
    monkeypatch.setattr(knowledge, "_settings", knowledge._settings.model_copy(update=update))


def _pdf(n: int) -> bytes:
    return _PDF + f"% {n}\n".encode()


async def _stored(db: RoleDatabase) -> tuple[int, int]:
    """Rows and jobs: what a refused upload must leave unchanged."""
    (row,) = await _rows(db.migrator_dsn, "SELECT count(*) FROM knowledge.documents")
    return row[0], len(await _jobs(db))


async def test_an_upload_past_the_byte_quota_is_refused_before_it_is_stored(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, db = api
    _quota(monkeypatch, bytes=len(_pdf(1)) * 2)
    alice = make_token("alice", scopes=_SCOPES)
    base = _create(client, alice)
    for n in (1, 2):
        assert _upload(client, alice, base["kb_id"], _pdf(n)).status_code == 202
    before = await _stored(db)
    blobs = api_main.knowledge._blobs()  # type: ignore[misc]
    puts: list[int] = []
    put = blobs.put

    async def counted(chunks: AsyncIterator[bytes], *, max_bytes: int) -> StoredBlob:
        puts.append(max_bytes)
        return await put(chunks, max_bytes=max_bytes)

    monkeypatch.setattr(blobs, "put", counted)
    response = _upload(client, alice, base["kb_id"], _pdf(3))
    assert (response.status_code, response.json()) == (413, {"detail": "byte_quota_exceeded"})
    assert puts == []  # refused before the file reached the store, not stored and deleted
    assert await _stored(db) == before
    assert len(_blobs(tmp_path)) == 2
    # The same content again is the existing document, not new usage.
    assert _upload(client, alice, base["kb_id"], _pdf(1)).status_code == 202
    # Per owner: Bob is not charged for Alice's files.
    bob = make_token("bob", scopes=_SCOPES)
    assert _upload(client, bob, _create(client, bob)["kb_id"], _pdf(3)).status_code == 202


async def test_document_and_page_quotas_count_what_the_owner_holds(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    base = _create(client, alice)
    assert _upload(client, alice, base["kb_id"], _pdf(1)).status_code == 202
    await _rows(
        db.migrator_dsn,
        "UPDATE knowledge.documents SET status = 'ready', page_count = 7 RETURNING 1",
    )
    _quota(monkeypatch, pages=7)
    response = _upload(client, alice, base["kb_id"], _pdf(2))
    assert (response.status_code, response.json()) == (413, {"detail": "page_quota_exceeded"})
    _quota(monkeypatch, pages=8, documents=1)
    response = _upload(client, alice, base["kb_id"], _pdf(2))
    assert (response.status_code, response.json()) == (413, {"detail": "document_quota_exceeded"})
    # A deleted base's documents still hold their files until the purge removes them.
    assert (
        client.client.delete(
            f"/v1/knowledge/bases/{base['kb_id']}", headers=bearer(alice)
        ).status_code
        == 202
    )
    other = _create(client, alice, "Other")
    response = _upload(client, alice, other["kb_id"], _pdf(2))
    assert response.json() == {"detail": "document_quota_exceeded"}
    assert await _stored(db) == (1, 2)  # the one document; its ingest job and the base's purge


async def test_the_ingesting_limit_is_429_until_a_document_finishes(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db = api
    _quota(monkeypatch, ingesting=1)
    alice = make_token("alice", scopes=_SCOPES)
    base = _create(client, alice)
    assert _upload(client, alice, base["kb_id"], _pdf(1)).status_code == 202
    response = _upload(client, alice, base["kb_id"], _pdf(2))
    assert response.status_code == 429
    assert response.json() == {"detail": "ingestion_concurrency_exceeded"}
    assert response.headers["Retry-After"] == "30"
    assert await _stored(db) == (1, 1)
    await _rows(db.migrator_dsn, "UPDATE knowledge.documents SET status = 'ready' RETURNING 1")
    assert _upload(client, alice, base["kb_id"], _pdf(2)).status_code == 202
    # A deleted base's queued documents are never ingested, so they stop counting.
    client.client.delete(f"/v1/knowledge/bases/{base['kb_id']}", headers=bearer(alice))
    assert (
        _upload(client, alice, _create(client, alice, "Other")["kb_id"], _pdf(3)).status_code == 202
    )


class _Barrier:
    """Holds each upload after its first quota check until `parties` have reached it."""

    def __init__(self, blobs: Any, parties: int) -> None:
        self._blobs, self._left, self._all = blobs, parties, anyio.Event()

    async def put(self, chunks: AsyncIterator[bytes], *, max_bytes: int) -> StoredBlob:
        self._left -= 1
        if self._left == 0:
            self._all.set()
        await self._all.wait()
        stored: StoredBlob = await self._blobs.put(chunks, max_bytes=max_bytes)
        return stored

    async def delete(self, key: str) -> None:
        await self._blobs.delete(key)


async def test_concurrent_uploads_cannot_pass_a_quota_together(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client, db = api
    _quota(monkeypatch, documents=1)
    alice = make_token("alice", scopes=_SCOPES)
    kb_id = uuid.UUID(_create(client, alice)["kb_id"])
    ((owner,),) = await _rows(db.migrator_dsn, "SELECT owner_key FROM knowledge.bases")
    knowledge = api_main.knowledge
    barrier = _Barrier(knowledge._blobs(), parties=2)  # type: ignore[misc]
    monkeypatch.setattr(knowledge, "_blobs", lambda: barrier)
    outcomes: list[str] = []

    async def upload(n: int) -> None:
        try:
            await knowledge.upload(
                owner,
                kb_id,
                data=_pdf(n),
                claimed_type="application/pdf",
                title="report.pdf",
                idempotency_key=None,
            )
            outcomes.append("accepted")
        except UploadRefusedError as exc:
            outcomes.append(exc.context.code)

    async with anyio.create_task_group() as tasks:
        for n in (1, 2):
            tasks.start_soon(upload, n)
    assert sorted(outcomes) == ["accepted", "document_quota_exceeded"]
    assert await _stored(db) == (1, 1)
    assert len(_blobs(tmp_path)) == 1  # the refused upload's file was deleted
