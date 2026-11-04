"""`POST /v1/knowledge/search` on Postgres, as the app role, with real tokens (RAG-03.05)."""

from __future__ import annotations

import uuid
from collections.abc import Callable

import psycopg
import pytest
import structlog
from test_postgres_knowledge_api import _create, api  # noqa: F401
from test_postgres_knowledge_search import _document
from test_postgres_roles import RoleDatabase, role_db, roles  # noqa: F401
from tests.conftest import JwtApi, bearer

from neuron_agent.api import main as api_main

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_SCOPES = "knowledge:read knowledge:write"


async def _seed(db: RoleDatabase, kb_id: str, texts: list[str]) -> list[str]:
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn) as conn:
        cursor = await conn.execute(
            "SELECT owner_key FROM knowledge.bases WHERE kb_id = %s", (kb_id,)
        )
        row = await cursor.fetchone()
    assert row is not None
    return [str(c) for c in await _document(db, uuid.UUID(kb_id), row[0], texts)]


def _search(client: JwtApi, token: str, **body: object) -> tuple[int, dict[str, object]]:
    response = client.client.post("/v1/knowledge/search", json=body, headers=bearer(token))
    return response.status_code, response.json()


def _ids(body: dict[str, object]) -> list[str]:
    return [hit["chunk_id"] for hit in body["results"]]  # type: ignore[attr-defined,index]


async def test_a_foreign_kb_id_is_ignored_as_not_found(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
) -> None:
    client, db = api
    alice, mallory = make_token("alice", scopes=_SCOPES), make_token("mallory", scopes=_SCOPES)
    theirs = _create(client, alice, "Alice's notes")
    secret = await _seed(db, theirs["kb_id"], ["greenhouse heating schedule"])
    own = _create(client, mallory, "Mallory's notes")
    [mine] = await _seed(db, own["kb_id"], ["greenhouse watering rota"])

    status, body = _search(
        client, mallory, query="greenhouse", kb_ids=[theirs["kb_id"], own["kb_id"]]
    )
    assert (status, body["status"], _ids(body)) == (200, "ok", [mine])
    for kb_ids in ([theirs["kb_id"]], [str(uuid.uuid4())]):
        assert _search(client, mallory, query="greenhouse", kb_ids=kb_ids) == (
            200,
            {"status": "no_relevant_results", "results": []},
        )
    # Alice's own search does find it: the id was ignored for Mallory, not missing.
    status, body = _search(client, alice, query="greenhouse", kb_ids=[theirs["kb_id"]])
    assert (status, _ids(body)) == (200, secret)


async def test_kb_ids_narrows_the_search_and_limit_caps_it(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
) -> None:
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    first, second = _create(client, alice, "One"), _create(client, alice, "Two")
    in_first = await _seed(db, first["kb_id"], [f"orchid note {n}" for n in range(4)])
    in_second = await _seed(db, second["kb_id"], ["orchid repotting"])

    status, body = _search(client, alice, query="orchid", kb_ids=[second["kb_id"]])
    assert (status, _ids(body)) == (200, in_second)
    status, body = _search(client, alice, query="orchid", limit=3)
    assert status == 200
    assert len(_ids(body)) == 3
    assert set(_ids(body)) <= {*in_first, *in_second}
    hit = body["results"][0]  # type: ignore[index]
    assert set(hit) == {
        "chunk_id",
        "doc_id",
        "kb_id",
        "title",
        "ordinal",
        "text",
        "headings",
        "page_start",
        "page_end",
        "score",
    }


async def test_the_route_returns_what_the_retriever_does_and_never_logs_the_query(
    api: tuple[JwtApi, RoleDatabase],  # noqa: F811
    make_token: Callable[..., str],
) -> None:
    """The tool (RAG-04.02) calls the same `Retriever.search`; this pins the route to it."""
    client, db = api
    alice = make_token("alice", scopes=_SCOPES)
    base = _create(client, alice, "Notes")
    await _seed(db, base["kb_id"], ["fern spores", "fern fronds", "moss"])
    query = "fern sentinel-q-7731"
    with structlog.testing.capture_logs() as logs:
        status, body = _search(client, alice, query=query, limit=5)
    assert status == 200
    assert query not in repr(logs) and "sentinel-q-7731" not in repr(logs)
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn) as conn:
        cursor = await conn.execute(
            "SELECT owner_key FROM knowledge.bases WHERE kb_id = %s", (base["kb_id"],)
        )
        row = await cursor.fetchone()
    assert row is not None
    direct = await api_main.retriever().search(row[0], query, k=5)
    assert _ids(body) == [str(p.chunk_id) for p in direct.passages]
