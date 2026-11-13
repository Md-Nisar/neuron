"""The knowledge base routes on Postgres, as the app role (RAG-03.01, ADR 0014 K5).

The BOLA matrix for `/v1/knowledge/*`: another user's base answers exactly as an unknown id does,
and is left unchanged. Real tokens through the HTTP API; needs pgvector, as the other knowledge
tests do.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, get_args

import psycopg
import pytest
from fastapi.routing import APIRoute
from psycopg.rows import dict_row
from test_postgres_knowledge_tables import _knowledge_db
from test_postgres_roles import RoleDatabase, _rows, role_db, roles  # noqa: F401
from tests.conftest import JwtApi, bearer

from neuron_agent.api import main as api_main
from neuron_agent.knowledge.authorization import KnowledgeAuthorization
from neuron_agent.knowledge.blobs import LocalBlobStore
from neuron_agent.knowledge.providers import EmbeddingProvider, FakeEmbeddings
from neuron_agent.knowledge.retrieval import Retriever
from neuron_agent.knowledge.service import KnowledgeBases
from neuron_agent.schemas.knowledge import KnowledgeLanguage

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_SCOPES = "knowledge:read knowledge:write knowledge:admin"
_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"
_MAX_BYTES = 4_096


class _Connections:
    """A connection per request, opened on the API's own event loop (a pool would bind to one)."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
        async with await psycopg.AsyncConnection.connect(
            self.dsn, autocommit=True, row_factory=dict_row
        ) as conn:
            yield conn


@pytest.fixture
async def api(
    role_db: RoleDatabase,  # noqa: F811
    jwt_api_factory: Callable[..., JwtApi],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[JwtApi, RoleDatabase]:
    await _knowledge_db(role_db)
    built = jwt_api_factory()
    settings = built.settings.model_copy(
        update={
            "knowledge_enabled": True,
            "knowledge_max_bases_per_user": 3,
            "knowledge_parse_max_bytes": _MAX_BYTES,
        }
    )
    connections = _Connections(role_db.app_dsn)
    blobs = LocalBlobStore(tmp_path / "blobs")
    monkeypatch.setattr(api_main, "settings", settings)
    monkeypatch.setattr(
        api_main,
        "knowledge",
        KnowledgeBases(settings, lambda: connections, lambda: blobs),  # type: ignore[arg-type,return-value]
    )
    fake = FakeEmbeddings(1024)
    provider = EmbeddingProvider(
        fake, fake, dimensions=1024, locality="self_hosted", batch_size=8, max_retries=0
    )
    search = Retriever(settings, lambda: connections, provider)  # type: ignore[arg-type,return-value]
    monkeypatch.setattr(api_main, "retriever", lambda: search)
    return built, role_db


def _blobs(tmp_path: Path) -> list[Path]:
    return sorted(path for path in (tmp_path / "blobs").rglob("*") if path.is_file())


def _send(
    api: JwtApi, method: str, path: str, body: dict[str, Any] | None, headers: dict[str, str]
) -> Any:
    if method == "POST" and path.endswith("/documents"):
        files = {"file": ("r.pdf", _PDF, "application/pdf")}
        return api.client.post(path, files=files, headers=headers)
    return api.client.request(method, path, json=body, headers=headers)


def _requests(
    kb_id: str, doc_id: str = "{doc_id}", chunk_id: str = "{chunk_id}"
) -> list[tuple[str, str, dict[str, Any] | None]]:
    """One request per knowledge route, aimed at the `kb_id`, `doc_id` and `chunk_id` it takes.

    Reads come before the delete, which would hide the rest.
    """
    return [
        ("GET", "/v1/knowledge/bases", None),
        ("POST", "/v1/knowledge/bases", {"name": "probe"}),
        ("GET", f"/v1/knowledge/bases/{kb_id}/documents", None),
        ("POST", f"/v1/knowledge/bases/{kb_id}/documents", None),
        ("POST", f"/v1/knowledge/bases/{kb_id}/web-pages", {"url": "https://example.com/p"}),
        ("POST", "/v1/knowledge/search", {"query": "secret plans", "kb_ids": [kb_id]}),
        ("GET", f"/v1/knowledge/documents/{doc_id}", None),
        ("GET", f"/v1/knowledge/documents/{doc_id}/chunks/{chunk_id}", None),
        ("GET", f"/v1/knowledge/documents/{doc_id}/file", None),
        ("DELETE", f"/v1/knowledge/documents/{doc_id}", None),
        ("GET", f"/v1/knowledge/bases/{kb_id}/grants", None),
        (
            "PUT",
            f"/v1/knowledge/bases/{kb_id}/grants",
            {"grants": [{"role": "r", "access": "admin"}]},
        ),
        ("PATCH", f"/v1/knowledge/bases/{kb_id}", {"name": "taken over"}),
        ("DELETE", f"/v1/knowledge/bases/{kb_id}", None),
    ]


def test_the_matrix_covers_every_knowledge_route() -> None:
    declared = {
        (method, route.path)
        for route in api_main.app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/v1/knowledge/")
        for method in route.methods
    }
    assert {(method, path) for method, path, _ in _requests("{kb_id}")} == declared


def _create(api: JwtApi, token: str, name: str = "Greenhouse") -> dict[str, Any]:
    response = api.client.post("/v1/knowledge/bases", json={"name": name}, headers=bearer(token))
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _document(db: RoleDatabase, kb_id: str, title: str = "Alice's tax return") -> str:
    """A document row as the upload (RAG-03.02 part 2) leaves it."""
    doc = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO knowledge.documents (doc_id, kb_id, uploaded_by, title, mime_type,"
            " size_bytes, sha256, blob_key, status)"
            " SELECT %s, kb_id, owner_key, %s, 'text/plain', 3, %s, %s, 'queued'"
            " FROM knowledge.bases WHERE kb_id = %s",
            (doc, title, uuid.uuid4().hex * 2, uuid.uuid4().hex, kb_id),
        )
    return str(doc)


async def _jobs(db: RoleDatabase) -> list[tuple[Any, ...]]:
    return await _rows(
        db.migrator_dsn, "SELECT task_name, args FROM knowledge.procrastinate_jobs ORDER BY id"
    )


async def test_another_users_base_is_the_same_404_as_an_unknown_id(
    api: tuple[JwtApi, RoleDatabase], make_token: Callable[..., str]
) -> None:
    client, db = api
    alice, mallory = make_token("alice", scopes=_SCOPES), make_token("mallory", scopes=_SCOPES)
    base = _create(client, alice, "Alice's secret plans")
    doc, chunk = await _document(db, base["kb_id"]), str(uuid.uuid4())
    for (method, path, body), (_, unknown, unknown_body) in zip(
        _requests(base["kb_id"], doc, chunk),
        _requests(str(uuid.uuid4()), str(uuid.uuid4()), chunk),
        strict=True,
    ):
        response = _send(client, method, path, body, bearer(mallory))
        assert "secret plans" not in response.text
        assert "tax return" not in response.text
        assert base["kb_id"] not in response.text
        if unknown == path:
            assert response.status_code in {200, 201}, (method, path)  # mallory's own scope
            continue
        baseline = _send(client, method, unknown, unknown_body, bearer(mallory))
        assert response.status_code == baseline.status_code == 404, (method, path)
        detail = (
            "knowledge_document_not_found" if "/documents/" in path else "knowledge_base_not_found"
        )
        assert response.json() == baseline.json() == {"detail": detail}
    listed = client.client.get("/v1/knowledge/bases", headers=bearer(alice)).json()
    assert listed == {"bases": [base]}
    assert await _jobs(db) == []


async def test_the_owner_renames_and_deletes_and_the_purge_is_queued_once(
    api: tuple[JwtApi, RoleDatabase], make_token: Callable[..., str]
) -> None:
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    kept, doomed = _create(client, alice, "Kept"), _create(client, alice, "Doomed")
    path = f"/v1/knowledge/bases/{kept['kb_id']}"
    renamed = client.client.patch(path, json={"name": "  Kept   for good "}, headers=bearer(alice))
    assert renamed.json() == {**kept, "name": "Kept for good"}

    gone = f"/v1/knowledge/bases/{doomed['kb_id']}"
    assert client.client.delete(gone, headers=bearer(alice)).status_code == 202
    listed = client.client.get("/v1/knowledge/bases", headers=bearer(alice)).json()
    assert [b["kb_id"] for b in listed["bases"]] == [kept["kb_id"]]
    assert await _jobs(db) == [("purge_knowledge_base", {"kb_id": doomed["kb_id"]})]
    # Tombstoned, not removed: the purge job owns the rest.
    assert await _rows(
        db.migrator_dsn,
        "SELECT deleted_at IS NOT NULL FROM knowledge.bases WHERE kb_id = %s",
        (doomed["kb_id"],),
    ) == [(True,)]
    for method, body in (("DELETE", None), ("PATCH", {"name": "back"})):
        again = client.client.request(method, gone, json=body, headers=bearer(alice))
        assert (again.status_code, again.json()) == (404, {"detail": "knowledge_base_not_found"})
    assert len(await _jobs(db)) == 1


async def test_the_per_user_limit_counts_live_bases_only(
    api: tuple[JwtApi, RoleDatabase], make_token: Callable[..., str]
) -> None:
    client, _ = api
    alice, bob = make_token("alice", scopes=_SCOPES), make_token("bob", scopes=_SCOPES)
    first = [_create(client, alice, f"kb {i}") for i in range(3)][0]
    refused = client.client.post("/v1/knowledge/bases", json={"name": "4"}, headers=bearer(alice))
    assert (refused.status_code, refused.json()) == (
        409,
        {"detail": "knowledge_base_limit_reached"},
    )
    _create(client, bob)  # per user
    client.client.delete(f"/v1/knowledge/bases/{first['kb_id']}", headers=bearer(alice))
    _create(client, alice, "after a delete")


async def test_a_base_keeps_the_language_it_was_created_with(
    api: tuple[JwtApi, RoleDatabase], make_token: Callable[..., str]
) -> None:
    """RAG-09.08: `language` is set at creation only; `simple` by default."""
    client, _ = api
    alice = make_token("alice", scopes=_SCOPES)
    created = client.client.post(
        "/v1/knowledge/bases", json={"name": "Hafen", "language": "german"}, headers=bearer(alice)
    )
    assert (created.status_code, created.json()["language"]) == (201, "german")
    assert _create(client, alice)["language"] == "simple"
    listed = client.client.get("/v1/knowledge/bases", headers=bearer(alice)).json()["bases"]
    assert [b["language"] for b in listed] == ["german", "simple"]
    for body in ({"name": "x", "language": "klingon"}, {"name": "x", "language": "English"}):
        refused = client.client.post("/v1/knowledge/bases", json=body, headers=bearer(alice))
        assert refused.status_code == 422
    renamed = client.client.patch(
        f"/v1/knowledge/bases/{created.json()['kb_id']}",
        json={"name": "y", "language": "simple"},
        headers=bearer(alice),
    )
    assert renamed.status_code == 422  # a rename cannot change it
    # Every language the API offers is a configuration this Postgres has, and none is missing.
    configs = await _rows(api[1].migrator_dsn, "SELECT cfgname::text FROM pg_ts_config")
    assert {row[0] for row in configs} == set(get_args(KnowledgeLanguage))


async def test_allowed_kbs_is_the_owners_live_bases(
    api: tuple[JwtApi, RoleDatabase], make_token: Callable[..., str]
) -> None:
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    kept, deleted = _create(client, alice), _create(client, alice, "Deleted")
    client.client.delete(f"/v1/knowledge/bases/{deleted['kb_id']}", headers=bearer(alice))
    (owner,) = await _rows(db.migrator_dsn, "SELECT DISTINCT owner_key FROM knowledge.bases")
    assert await _rows(
        db.migrator_dsn, "SELECT subject_type, access FROM knowledge.grants ORDER BY created_at"
    ) == [("owner", "admin"), ("owner", "admin")]
    async with await psycopg.AsyncConnection.connect(db.app_dsn, row_factory=dict_row) as conn:
        allowed = await KnowledgeAuthorization.allowed_kbs(conn, owner[0])
        other = await KnowledgeAuthorization.allowed_kbs(conn, "b" * 64)
        anonymous = await KnowledgeAuthorization.allowed_kbs(conn, None, frozenset({"finance"}))
    assert allowed.read == allowed.write == allowed.admin == allowed.owned
    assert allowed.read == {uuid.UUID(kept["kb_id"])}
    assert other.read == other.write == anonymous.read == frozenset()


async def test_the_owner_sees_live_documents_and_their_status(
    api: tuple[JwtApi, RoleDatabase], make_token: Callable[..., str]
) -> None:
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    base = _create(client, alice)
    docs = [await _document(db, base["kb_id"], f"doc {i}") for i in range(3)]
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "UPDATE knowledge.documents SET status = 'failed', error_code = 'no_text'"
            " WHERE doc_id = %s",
            (docs[1],),
        )
        await conn.execute(
            "UPDATE knowledge.documents SET status = 'deleting', deleted_at = now()"
            " WHERE doc_id = %s",
            (docs[2],),
        )
    listing = f"/v1/knowledge/bases/{base['kb_id']}/documents"
    page = client.client.get(f"{listing}?limit=1&offset=1", headers=bearer(alice)).json()
    assert (page["total"], page["limit"], page["offset"]) == (2, 1, 1)
    assert [(d["doc_id"], d["status"], d["error_code"]) for d in page["documents"]] == [
        (docs[1], "failed", "no_text")
    ]
    one = client.client.get(f"/v1/knowledge/documents/{docs[0]}", headers=bearer(alice))
    assert one.status_code == 200
    assert set(one.json()) == {
        "doc_id", "kb_id", "title", "mime_type", "size_bytes", "page_count", "status",
        "error_code", "created_at", "updated_at", "source_url", "fetched_at",
    }  # fmt: skip
    assert (one.json()["source_url"], one.json()["fetched_at"]) == (None, None)  # an upload
    assert (one.json()["title"], one.json()["status"]) == ("doc 0", "queued")
    gone = client.client.get(f"/v1/knowledge/documents/{docs[2]}", headers=bearer(alice))
    assert (gone.status_code, gone.json()) == (404, {"detail": "knowledge_document_not_found"})

    # A deleted base takes its documents with it, before the purge runs.
    client.client.delete(f"/v1/knowledge/bases/{base['kb_id']}", headers=bearer(alice))
    after = client.client.get(f"/v1/knowledge/documents/{docs[0]}", headers=bearer(alice))
    assert after.status_code == 404
    assert client.client.get(listing, headers=bearer(alice)).status_code == 404


def _upload(
    api: JwtApi,
    token: str,
    kb_id: str,
    data: bytes = _PDF,
    content_type: str = "application/pdf",
    **headers: str,
) -> Any:
    return api.client.post(
        f"/v1/knowledge/bases/{kb_id}/documents",
        files={"file": ("report.pdf", data, content_type)},
        headers={**bearer(token), **headers},
    )


async def test_a_pdf_upload_is_queued_with_its_job(
    api: tuple[JwtApi, RoleDatabase], make_token: Callable[..., str], tmp_path: Path
) -> None:
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    base = _create(client, alice)
    response = _upload(client, alice, base["kb_id"])
    assert response.status_code == 202, response.text
    accepted = response.json()
    doc = accepted["doc_id"]
    assert accepted == {
        "doc_id": doc,
        "kb_id": base["kb_id"],
        "status": "queued",
        "status_url": f"/v1/knowledge/documents/{doc}",
    }
    status = client.client.get(accepted["status_url"], headers=bearer(alice)).json()
    assert (status["title"], status["mime_type"], status["size_bytes"], status["status"]) == (
        "report.pdf",
        "application/pdf",
        len(_PDF),
        "queued",
    )
    assert await _jobs(db) == [("ingest_document", {"doc_id": doc})]
    (blob,) = _blobs(tmp_path)
    assert blob.read_bytes() == _PDF
    assert "report" not in str(blob)  # no file name in the key


async def test_a_repeated_idempotency_key_returns_the_first_document_and_stores_nothing(
    api: tuple[JwtApi, RoleDatabase], make_token: Callable[..., str], tmp_path: Path
) -> None:
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    base, other = _create(client, alice), _create(client, alice, "Other")
    key = {"Idempotency-Key": "upload-1"}
    first = _upload(client, alice, base["kb_id"], **key)
    again = _upload(client, alice, base["kb_id"], _PDF + b"different", **key)
    assert again.status_code == 202
    assert again.json() == first.json()
    assert len(_blobs(tmp_path)) == 1
    assert len(await _jobs(db)) == 1
    elsewhere = _upload(client, alice, other["kb_id"], **key)
    assert (elsewhere.status_code, elsewhere.json()) == (409, {"detail": "idempotency_key_reused"})
    # The same content again, without a key: the base's existing document.
    assert _upload(client, alice, base["kb_id"]).json() == first.json()
    assert len(_blobs(tmp_path)) == 1


_HTML = b"<!DOCTYPE html><html><script>alert(1)</script>"


@pytest.mark.parametrize(
    ("data", "content_type", "status", "detail"),
    [
        (_HTML, "application/pdf", 415, "unsupported_media_type"),
        (b"\x89PNG\r\n\x1a\n", "image/png", 415, "unsupported_media_type"),
        (b"%PDF-1.7\n" + b"x" * _MAX_BYTES, "application/pdf", 413, "file_too_large"),
        (b"", "application/pdf", 422, "empty_file"),
    ],
    ids=["html-claiming-pdf", "image", "over-the-cap", "empty"],
)
async def test_a_refused_file_stores_nothing(
    api: tuple[JwtApi, RoleDatabase],
    make_token: Callable[..., str],
    tmp_path: Path,
    data: bytes,
    content_type: str,
    status: int,
    detail: str,
) -> None:
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    base = _create(client, alice)
    response = _upload(client, alice, base["kb_id"], data, content_type)
    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert _blobs(tmp_path) == []
    assert await _rows(db.migrator_dsn, "SELECT count(*) FROM knowledge.documents") == [(0,)]
    assert await _jobs(db) == []


async def test_a_body_declared_over_the_cap_is_413_before_it_is_read(
    api: tuple[JwtApi, RoleDatabase], make_token: Callable[..., str], tmp_path: Path
) -> None:
    client, _ = api
    alice = make_token("alice", scopes=_SCOPES)
    base = _create(client, alice)
    response = client.client.post(
        f"/v1/knowledge/bases/{base['kb_id']}/documents",
        content=b"x" * (api_main.upload_body_limit() + 1),
        headers={**bearer(alice), "Content-Type": "multipart/form-data; boundary=x"},
    )
    assert (response.status_code, response.json()) == (413, {"detail": "payload_too_large"})
    assert _blobs(tmp_path) == []


async def test_a_body_that_does_not_arrive_in_time_frees_its_slot(
    api: tuple[JwtApi, RoleDatabase],
    make_token: Callable[..., str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = api
    alice = make_token("alice", scopes=_SCOPES)
    base = _create(client, alice)
    monkeypatch.setattr(api_main, "_UPLOAD_READ_SECONDS", 0)
    response = _upload(client, alice, base["kb_id"])
    assert (response.status_code, response.json()) == (408, {"detail": "upload_timeout"})
    assert api_main._upload_slots.in_flight == 0
    assert _blobs(tmp_path) == []


async def test_a_document_delete_is_202_once_and_queues_one_purge(
    api: tuple[JwtApi, RoleDatabase], make_token: Callable[..., str]
) -> None:
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    base = _create(client, alice)
    kept, doomed = [await _document(db, base["kb_id"], f"doc {i}") for i in range(2)]
    path = f"/v1/knowledge/documents/{doomed}"
    assert client.client.delete(path, headers=bearer(alice)).status_code == 202
    assert await _jobs(db) == [("purge_document", {"doc_id": doomed})]
    assert await _rows(
        db.migrator_dsn,
        "SELECT status, deleted_at IS NOT NULL FROM knowledge.documents WHERE doc_id = %s",
        (doomed,),
    ) == [("deleting", True)]
    for method in ("DELETE", "GET"):
        again = client.client.request(method, path, headers=bearer(alice))
        assert (again.status_code, again.json()) == (
            404,
            {"detail": "knowledge_document_not_found"},
        )
    assert len(await _jobs(db)) == 1  # the second delete queued nothing
    listed = client.client.get(
        f"/v1/knowledge/bases/{base['kb_id']}/documents", headers=bearer(alice)
    )
    assert [d["doc_id"] for d in listed.json()["documents"]] == [kept]
    # Read-only callers cannot delete.
    reader = make_token("alice", scopes="knowledge:read")
    assert (
        client.client.delete(f"/v1/knowledge/documents/{kept}", headers=bearer(reader)).status_code
        == 403
    )
