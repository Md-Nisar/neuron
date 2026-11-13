"""Adding a web page by URL through the API, on Postgres (RAG-10.02, part 3)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from test_postgres_knowledge_api import _SCOPES, _create, _jobs, _rows, api  # noqa: F401
from test_postgres_roles import RoleDatabase, role_db, roles  # noqa: F401
from tests.conftest import JwtApi, bearer

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_URL = "https://docs.example.com/greenhouse?lang=en"


def _add(client: JwtApi, token: str, kb_id: str, url: str = _URL, **headers: str) -> Any:
    path = f"/v1/knowledge/bases/{kb_id}/web-pages"
    return client.client.post(path, json={"url": url}, headers={**bearer(token), **headers})


async def test_a_page_is_queued_with_its_url_and_no_file(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
) -> None:
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    base = _create(client, alice)
    response = _add(client, alice, base["kb_id"], _URL + "#section-2")
    assert response.status_code == 202, response.text
    accepted = response.json()
    doc = accepted["doc_id"]
    status = client.client.get(accepted["status_url"], headers=bearer(alice)).json()
    assert (status["title"], status["mime_type"], status["size_bytes"], status["status"]) == (
        "https://docs.example.com/greenhouse",  # no query in the default title
        "text/html",
        0,
        "queued",
    )
    assert await _rows(
        db.migrator_dsn,
        "SELECT source_type, source_ref, blob_key, sha256 FROM knowledge.documents",
    ) == [("web", _URL, None, None)]
    assert await _jobs(db) == [("ingest_document", {"doc_id": doc})]
    # Nothing to download until the worker has fetched it.
    file = client.client.get(f"/v1/knowledge/documents/{doc}/file", headers=bearer(alice))
    assert file.status_code == 404


async def test_the_same_url_or_key_again_returns_the_first_document(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
) -> None:
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    base, other = _create(client, alice), _create(client, alice, "Other")
    key = {"Idempotency-Key": "page-1"}
    first = _add(client, alice, base["kb_id"], **key).json()
    assert _add(client, alice, base["kb_id"]).json() == first
    assert _add(client, alice, base["kb_id"], _URL + "&b=2", **key).json() == first
    replay = _add(client, alice, other["kb_id"], **key)
    assert (replay.status_code, replay.json()) == (409, {"detail": "idempotency_key_reused"})
    # In another base the page is a document of its own.
    assert _add(client, alice, other["kb_id"]).json()["doc_id"] != first["doc_id"]
    assert len(await _jobs(db)) == 2


@pytest.mark.parametrize(
    "url",
    [
        "http://docs.example.com/",
        "https://127.0.0.1/admin",
        "https://localhost/",
        "https://[::1]/",
        "https://10.0.0.8/",
        "https://user:secret@docs.example.com/",
        "ftp://docs.example.com/",
        "https://docs.example.com/a b",
    ],
)
async def test_a_url_that_is_not_public_https_is_refused_and_stores_nothing(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
    url: str,
) -> None:
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    response = _add(client, alice, _create(client, alice)["kb_id"], url)
    assert (response.status_code, response.json()) == (422, {"detail": "url_not_allowed"})
    assert "secret" not in response.text
    assert await _rows(db.migrator_dsn, "SELECT count(*) FROM knowledge.documents") == [(0,)]
    assert await _jobs(db) == []


async def test_a_reader_cannot_add_a_page(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
) -> None:
    client, _ = api
    alice = make_token("alice", scopes=_SCOPES)
    reader = make_token("bob", scopes="knowledge:read")
    response = _add(client, reader, _create(client, alice)["kb_id"])
    assert response.status_code == 403
