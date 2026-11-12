"""Knowledge bases shared by role (RAG-09.03, ADR 0014 amendment), on Postgres with real tokens.

A role grant gives the holders of a verified token role `read`, `write` or `admin` access to
another user's base. A base the caller cannot see is `404`, as before; one they can see but not
change that way is `403`. Revoking a grant counts from the next request. Grants are written here
as rows: the grants API is a later part of the story.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from langchain.tools import ToolRuntime
from test_postgres_knowledge_api import _create, _jobs, api  # noqa: F401
from test_postgres_knowledge_search_api import _ids, _owner_of, _search, _seed
from test_postgres_roles import RoleDatabase, _rows, role_db, roles  # noqa: F401
from tests.conftest import JwtApi, bearer

from neuron_agent.api import main as api_main
from neuron_agent.knowledge import tools as knowledge_tools
from neuron_agent.security.auth import Principal
from neuron_agent.security.authorization import AuthorizationContext

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_SCOPES = "knowledge:read knowledge:write"
_PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


async def _grant(db: RoleDatabase, kb_id: str, role: str, access: str) -> None:
    owner = await _owner_of(db, kb_id)
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO knowledge.grants (kb_id, subject_type, subject, access, granted_by)"
            " VALUES (%s, 'role', %s, %s, %s) ON CONFLICT (kb_id, subject_type, subject)"
            " DO UPDATE SET access = excluded.access",
            (kb_id, role, access, owner),
        )


async def _revoke(db: RoleDatabase, kb_id: str, role: str) -> None:
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "DELETE FROM knowledge.grants WHERE kb_id = %s AND subject_type = 'role'"
            " AND subject = %s",
            (kb_id, role),
        )


def _upload(client: JwtApi, token: str, kb_id: str) -> Any:
    return client.client.post(
        f"/v1/knowledge/bases/{kb_id}/documents",
        files={"file": ("r.pdf", _PDF, "application/pdf")},
        headers=bearer(token),
    )


def _status(client: JwtApi, token: str, method: str, path: str, body: Any = None) -> int:
    return client.client.request(method, path, json=body, headers=bearer(token)).status_code


async def test_a_read_grant_shares_search_and_citations_until_it_is_revoked(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
) -> None:
    """AC1: after the revoke, the member's next search finds nothing and the citation is 404."""
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    bob = make_token("bob", scopes=_SCOPES, roles=["finance"])
    carol = make_token("carol", scopes=_SCOPES, roles=["legal"])
    base = _create(client, alice, "Budget")
    [chunk] = await _seed(db, base["kb_id"], ["quarterly budget forecast"])
    doc = client.client.get(
        f"/v1/knowledge/bases/{base['kb_id']}/documents", headers=bearer(alice)
    ).json()["documents"][0]["doc_id"]
    citation = f"/v1/knowledge/documents/{doc}/chunks/{chunk}"
    assert _ids(_search(client, bob, query="budget forecast")[1]) == []

    await _grant(db, base["kb_id"], "finance", "read")
    listed = client.client.get("/v1/knowledge/bases", headers=bearer(bob)).json()["bases"]
    assert [b["kb_id"] for b in listed] == [base["kb_id"]]
    assert _ids(_search(client, bob, query="budget forecast")[1]) == [chunk]
    assert _status(client, bob, "GET", citation) == 200
    # Another role sees nothing, as an unknown id.
    assert _ids(_search(client, carol, query="budget forecast")[1]) == []
    assert _status(client, carol, "GET", citation) == 404

    await _revoke(db, base["kb_id"], "finance")
    assert _ids(_search(client, bob, query="budget forecast")[1]) == []
    assert _status(client, bob, "GET", citation) == 404
    assert client.client.get("/v1/knowledge/bases", headers=bearer(bob)).json()["bases"] == []


async def test_read_access_cannot_change_the_base(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
) -> None:
    """AC2: a reader's upload is 403 (the base is listed for them) and stores nothing; so are
    rename, delete and a document delete. A base they cannot see stays 404."""
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    bob = make_token("bob", scopes=_SCOPES, roles=["finance"])
    base, hidden = _create(client, alice, "Budget"), _create(client, alice, "Private")
    await _seed(db, base["kb_id"], ["quarterly budget forecast"])
    doc = client.client.get(
        f"/v1/knowledge/bases/{base['kb_id']}/documents", headers=bearer(alice)
    ).json()["documents"][0]["doc_id"]
    await _grant(db, base["kb_id"], "finance", "read")
    jobs = await _jobs(db)

    response = _upload(client, bob, base["kb_id"])
    assert (response.status_code, response.json()) == (403, {"detail": "knowledge_access_denied"})
    assert _upload(client, bob, hidden["kb_id"]).status_code == 404
    kb = f"/v1/knowledge/bases/{base['kb_id']}"
    assert _status(client, bob, "PATCH", kb, {"name": "Mine now"}) == 403
    assert _status(client, bob, "DELETE", kb) == 403
    assert _status(client, bob, "DELETE", f"/v1/knowledge/documents/{doc}") == 403
    assert (
        _status(client, bob, "PATCH", f"/v1/knowledge/bases/{hidden['kb_id']}", {"name": "x"})
        == 404
    )
    assert await _jobs(db) == jobs
    assert await _rows(
        db.migrator_dsn, "SELECT name FROM knowledge.bases WHERE kb_id = %s", (base["kb_id"],)
    ) == [("Budget",)]


async def test_write_lets_a_member_upload_on_their_own_quota_and_admin_rename(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
) -> None:
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    bob = make_token("bob", scopes=_SCOPES, roles=["finance"])
    base = _create(client, alice, "Budget")
    kb = f"/v1/knowledge/bases/{base['kb_id']}"
    await _grant(db, base["kb_id"], "finance", "write")

    response = _upload(client, bob, base["kb_id"])
    assert response.status_code == 202, response.text
    doc = response.json()["doc_id"]
    # Quotas stay per uploader (RAG-02.05): the document is filed under bob, not the owner.
    [(uploader,)] = await _rows(
        db.migrator_dsn, "SELECT uploaded_by FROM knowledge.documents WHERE doc_id = %s", (doc,)
    )
    assert uploader != await _owner_of(db, base["kb_id"])
    assert _status(client, bob, "PATCH", kb, {"name": "Shared budget"}) == 403

    await _grant(db, base["kb_id"], "finance", "admin")
    assert _status(client, bob, "PATCH", kb, {"name": "Shared budget"}) == 200
    # Only the owner deletes a base, even with an admin grant.
    assert _status(client, bob, "DELETE", kb) == 403
    assert _status(client, alice, "DELETE", kb) == 202


async def test_erase_removes_the_members_uploads_and_the_owners_bases(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
) -> None:
    """A member's erase removes their uploads to shared bases and leaves the base; the owner's
    erase removes the base with every member's upload in it."""
    client, db = api
    alice = make_token("alice", scopes=_SCOPES + " data:erase")
    bob = make_token("bob", scopes=_SCOPES + " data:erase", roles=["finance"])
    base = _create(client, alice, "Budget")
    await _grant(db, base["kb_id"], "finance", "write")
    mine = _upload(client, bob, base["kb_id"]).json()["doc_id"]
    alices = client.client.post(
        f"/v1/knowledge/bases/{base['kb_id']}/documents",
        files={"file": ("a.pdf", _PDF + b"%alice\n", "application/pdf")},
        headers=bearer(alice),
    ).json()["doc_id"]

    erased = client.client.delete("/v1/me/knowledge", headers=bearer(bob))
    assert erased.status_code == 200, erased.text
    assert erased.json()["erased_base_count"] == 0
    assert erased.json()["erased_document_count"] == 1
    assert await _rows(
        db.migrator_dsn,
        "SELECT doc_id::text, deleted_at IS NOT NULL FROM knowledge.documents ORDER BY created_at",
    ) == [(mine, True), (alices, False)]
    assert ("purge_document", {"doc_id": mine}) in await _jobs(db)
    # A repeat queues nothing new while that purge waits.
    jobs = await _jobs(db)
    client.client.delete("/v1/me/knowledge", headers=bearer(bob))
    assert await _jobs(db) == jobs

    assert client.client.delete("/v1/me/knowledge", headers=bearer(alice)).status_code == 200
    assert await _rows(db.migrator_dsn, "SELECT deleted_at IS NOT NULL FROM knowledge.bases") == [
        (True,)
    ]


async def test_the_search_tool_reads_roles_from_the_runs_principal(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    base = _create(client, alice, "Budget")
    [chunk] = await _seed(db, base["kb_id"], ["quarterly budget forecast"])
    await _grant(db, base["kb_id"], "finance", "read")
    route = api_main.retriever()
    monkeypatch.setattr(knowledge_tools, "create_embedding_provider", lambda _: route._embeddings)
    specs = knowledge_tools.knowledge_specs(route._settings, route._pool)
    search = next(spec.tool for spec in specs if spec.name == "search_knowledge")

    async def found(held: frozenset[str]) -> list[str]:
        principal = Principal(
            issuer="iss",
            subject="bob",
            scopes=frozenset(),
            token_id=None,
            expires_at=datetime.now(UTC),
            roles=held,
        )
        context = AuthorizationContext(frozenset(), principal=principal, owner_key="b" * 64)
        runtime = ToolRuntime(
            state={"messages": []},
            context=context,
            config={},
            stream_writer=lambda _: None,
            tool_call_id=f"call-{uuid.uuid4()}",
            store=None,
        )
        message = await search.ainvoke(
            {
                "name": "search_knowledge",
                "args": {"query": "budget forecast", "runtime": runtime},
                "id": runtime.tool_call_id,
                "type": "tool_call",
            }
        )
        return [ref["chunk_id"] for ref in message.artifact.values()]

    assert await found(frozenset({"finance"})) == [chunk]
    assert await found(frozenset({"legal"})) == []


async def test_an_owner_grant_counts_only_on_the_owners_base_and_a_revoked_writer_cannot_replay(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
) -> None:
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    bob = make_token("bob", scopes=_SCOPES, roles=["finance"])
    base, bobs = _create(client, alice, "Budget"), _create(client, bob, "Bob's")
    # A stray owner grant naming bob on alice's base gives him nothing.
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO knowledge.grants (kb_id, subject_type, subject, access, granted_by)"
            " VALUES (%s, 'owner', %s, 'admin', %s)",
            (base["kb_id"], await _owner_of(db, bobs["kb_id"]), await _owner_of(db, bobs["kb_id"])),
        )
    assert [
        b["kb_id"]
        for b in client.client.get("/v1/knowledge/bases", headers=bearer(bob)).json()["bases"]
    ] == [bobs["kb_id"]]

    await _grant(db, base["kb_id"], "finance", "write")
    headers = {**bearer(bob), "Idempotency-Key": "upload-1"}
    path = f"/v1/knowledge/bases/{base['kb_id']}/documents"
    files = {"file": ("r.pdf", _PDF, "application/pdf")}
    assert client.client.post(path, files=files, headers=headers).status_code == 202
    await _grant(db, base["kb_id"], "finance", "read")
    # The replay is refused before the key is looked up: no document id comes back.
    again = client.client.post(path, files=files, headers=headers)
    assert (again.status_code, again.json()) == (403, {"detail": "knowledge_access_denied"})
