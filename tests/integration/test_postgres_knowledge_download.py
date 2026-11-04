"""Chunk inspection and file download on Postgres, as the app role (RAG-03.04).

A chunk is read under RLS through a live, ready document of a base the caller may read, checked
on every call; the original file always goes out as an attachment a browser does not render.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

import psycopg
import pytest
from test_postgres_knowledge_api import _SCOPES, _create, _upload, api  # noqa: F401
from test_postgres_roles import RoleDatabase, role_db, roles  # noqa: F401
from tests.conftest import JwtApi, bearer

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_NOT_FOUND = (404, {"detail": "knowledge_document_not_found"})


async def _chunks(db: RoleDatabase, doc_id: str, n: int) -> list[str]:
    """`n` chunks of `doc_id` in order, as ingestion leaves them, and the document ready."""
    ids = [str(uuid.uuid4()) for _ in range(n)]
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "UPDATE knowledge.documents SET status = 'ready' WHERE doc_id = %s", (doc_id,)
        )
        for ordinal, chunk in enumerate(ids):
            await conn.execute(
                "INSERT INTO knowledge.chunks (chunk_id, doc_id, kb_id, ordinal, text, headings,"
                " page_start, page_end, token_count, ts_config) SELECT %s, doc_id, kb_id, %s, %s,"
                " ARRAY['Intro'], %s, %s, 3, 'english' FROM knowledge.documents WHERE doc_id = %s",
                (chunk, ordinal, f"Passage {ordinal}.", ordinal + 1, ordinal + 1, doc_id),
            )
    return ids


def _get(client: JwtApi, token: str, path: str, **params: Any) -> tuple[int, Any]:
    response = client.client.get(path, params=params, headers=bearer(token))
    return response.status_code, response.json()


async def test_a_chunk_comes_with_its_neighbours_and_access_is_rechecked_each_time(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
) -> None:
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    kb = _create(client, alice)["kb_id"]
    doc, other = (
        _upload(client, alice, kb, f"Note {n}.".encode(), "text/plain").json()["doc_id"]
        for n in range(2)
    )
    chunks, foreign = await _chunks(db, doc, 5), (await _chunks(db, other, 1))[0]
    path = f"/v1/knowledge/documents/{doc}/chunks/{chunks[2]}"
    status, body = _get(client, alice, path, neighbours=1)
    assert status == 200
    assert {k: body[k] for k in ("doc_id", "kb_id", "ordinal", "text", "headings")} == {
        "doc_id": doc,
        "kb_id": kb,
        "ordinal": 2,
        "text": "Passage 2.",
        "headings": ["Intro"],
    }
    assert (body["page_start"], body["page_end"]) == (3, 3)
    assert [n["chunk_id"] for n in body["neighbours"]] == [chunks[1], chunks[3]]
    assert _get(client, alice, path)[1]["neighbours"] == []
    assert _get(client, alice, path, neighbours=4)[0] == 422
    # A chunk id from another document, even of the same base, is not found under this one.
    assert _get(client, alice, f"/v1/knowledge/documents/{doc}/chunks/{foreign}") == _NOT_FOUND
    assert _get(client, alice, f"/v1/knowledge/documents/{other}/chunks/{chunks[0]}") == _NOT_FOUND
    # Access lost: the passage seen a moment ago is the same 404.
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute("DELETE FROM knowledge.grants WHERE kb_id = %s", (kb,))
    assert _get(client, alice, path) == _NOT_FOUND
    assert _get(client, alice, f"/v1/knowledge/documents/{doc}/file") == _NOT_FOUND


async def test_a_chunk_of_a_document_not_ready_or_deleted_is_not_found(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
) -> None:
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    kb = _create(client, alice)["kb_id"]
    doc = _upload(client, alice, kb, b"Note.", "text/plain").json()["doc_id"]
    path = f"/v1/knowledge/documents/{doc}/chunks/{(await _chunks(db, doc, 1))[0]}"
    assert _get(client, alice, path)[0] == 200
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "UPDATE knowledge.documents SET status = 'embedding' WHERE doc_id = %s", (doc,)
        )
    assert _get(client, alice, path) == _NOT_FOUND
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "UPDATE knowledge.documents SET status = 'ready' WHERE doc_id = %s", (doc,)
        )
    assert (
        client.client.delete(f"/v1/knowledge/documents/{doc}", headers=bearer(alice)).status_code
        == 202
    )
    assert _get(client, alice, path) == _NOT_FOUND


_SVG_MARKDOWN = b'# Notes\n\n<svg onload="alert(1)"><script>alert(2)</script></svg>\n'


@pytest.mark.parametrize(
    ("data", "claimed", "served"),
    [
        (_SVG_MARKDOWN, "text/markdown", "text/plain; charset=utf-8"),
        (b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n", "application/pdf", "application/pdf"),
    ],
)
async def test_the_original_downloads_as_an_attachment_never_rendered(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
    data: bytes,
    claimed: str,
    served: str,
) -> None:
    client, _ = api
    alice = make_token("alice", scopes="knowledge:read knowledge:write")
    kb = _create(client, alice)["kb_id"]
    title = 'Q3 "plan"; filename=evil.htmlé'
    response = client.client.post(
        f"/v1/knowledge/bases/{kb}/documents",
        files={"file": ("x", data, claimed)},
        data={"title": title},
        headers=bearer(alice),
    )
    doc = response.json()["doc_id"]
    reader = make_token("alice", scopes="knowledge:read")
    download = client.client.get(f"/v1/knowledge/documents/{doc}/file", headers=bearer(reader))
    assert download.status_code == 200
    assert download.content == data
    expected = {
        "content-type": served,
        "x-content-type-options": "nosniff",
        "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
        "cache-control": "no-store",
    }
    assert {name: download.headers.get(name) for name in expected} == expected
    assert download.headers["content-disposition"] == (
        'attachment; filename="Q3 _plan__ filename_evil.html_";'
        " filename*=UTF-8''Q3%20%22plan%22%3B%20filename%3Devil.html%C3%A9"
    )
