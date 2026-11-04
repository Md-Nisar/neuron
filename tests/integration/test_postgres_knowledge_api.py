"""The knowledge base routes on Postgres, as the app role (RAG-03.01, ADR 0014 K5).

The BOLA matrix for `/v1/knowledge/*`: another user's base answers exactly as an unknown id does,
and is left unchanged. Real tokens through the HTTP API; needs pgvector, as the other knowledge
tests do.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import psycopg
import pytest
from fastapi.routing import APIRoute
from psycopg.rows import dict_row
from test_postgres_knowledge_tables import _knowledge_db
from test_postgres_roles import RoleDatabase, _rows, role_db, roles  # noqa: F401
from tests.conftest import JwtApi, bearer

from neuron_agent.api import main as api_main
from neuron_agent.knowledge.authorization import KnowledgeAuthorization
from neuron_agent.knowledge.service import KnowledgeBases
from neuron_agent.security.authorization import AuthorizationContext

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_SCOPES = "knowledge:read knowledge:write"


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
) -> tuple[JwtApi, RoleDatabase]:
    await _knowledge_db(role_db)
    built = jwt_api_factory()
    settings = built.settings.model_copy(
        update={"knowledge_enabled": True, "knowledge_max_bases_per_user": 3}
    )
    connections = _Connections(role_db.app_dsn)
    monkeypatch.setattr(api_main, "knowledge", KnowledgeBases(settings, lambda: connections))  # type: ignore[arg-type,return-value]
    return built, role_db


def _requests(kb_id: str, doc_id: str = "{doc_id}") -> list[tuple[str, str, dict[str, Any] | None]]:
    """One request per knowledge route, aimed at `kb_id` and `doc_id` where the route takes one.

    Reads come before the delete, which would hide the rest.
    """
    return [
        ("GET", "/v1/knowledge/bases", None),
        ("POST", "/v1/knowledge/bases", {"name": "probe"}),
        ("GET", f"/v1/knowledge/bases/{kb_id}/documents", None),
        ("GET", f"/v1/knowledge/documents/{doc_id}", None),
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
    doc = await _document(db, base["kb_id"])
    for (method, path, body), (_, unknown, unknown_body) in zip(
        _requests(base["kb_id"], doc), _requests(str(uuid.uuid4()), str(uuid.uuid4())), strict=True
    ):
        response = client.client.request(method, path, json=body, headers=bearer(mallory))
        assert "secret plans" not in response.text
        assert "tax return" not in response.text
        assert base["kb_id"] not in response.text
        if unknown == path:
            assert response.status_code in {200, 201}, (method, path)  # mallory's own scope
            continue
        baseline = client.client.request(
            method, unknown, json=unknown_body, headers=bearer(mallory)
        )
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
        allowed = await KnowledgeAuthorization.allowed_kbs(
            conn, AuthorizationContext(frozenset(), owner_key=owner[0])
        )
        other = await KnowledgeAuthorization.allowed_kbs(
            conn, AuthorizationContext(frozenset(), owner_key="b" * 64)
        )
        anonymous = await KnowledgeAuthorization.allowed_kbs(
            conn, AuthorizationContext(frozenset())
        )
    assert allowed.read == allowed.write == {uuid.UUID(kept["kb_id"])}
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
        "error_code", "created_at", "updated_at",
    }  # fmt: skip
    assert (one.json()["title"], one.json()["status"]) == ("doc 0", "queued")
    gone = client.client.get(f"/v1/knowledge/documents/{docs[2]}", headers=bearer(alice))
    assert (gone.status_code, gone.json()) == (404, {"detail": "knowledge_document_not_found"})

    # A deleted base takes its documents with it, before the purge runs.
    client.client.delete(f"/v1/knowledge/bases/{base['kb_id']}", headers=bearer(alice))
    after = client.client.get(f"/v1/knowledge/documents/{docs[0]}", headers=bearer(alice))
    assert after.status_code == 404
    assert client.client.get(listing, headers=bearer(alice)).status_code == 404
