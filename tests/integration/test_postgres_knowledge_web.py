"""A web page fetched by the worker and ingested on Postgres (RAG-10.02, part 2)."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Any

import psycopg
import pytest
from test_postgres_knowledge_api import _Connections
from test_postgres_knowledge_ingest import _OWNER, _embeddings
from test_postgres_knowledge_search import _base as _owned_base
from test_postgres_knowledge_tables import _knowledge_db, worker  # noqa: F401
from test_postgres_roles import RoleDatabase, _rows, role_db, roles  # noqa: F401

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge.blobs import LocalBlobStore
from neuron_agent.knowledge.ingest import Ingestor, connector, fetch_page
from neuron_agent.knowledge.parsing import HTML, HtmlParser, Limits
from neuron_agent.knowledge.purge import Purger
from neuron_agent.knowledge.retrieval import Retriever
from neuron_agent.knowledge.service import KnowledgeBases
from neuron_agent.security.egress import FetchedResponse, FetchError

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_URL = "https://docs.example.com/greenhouse"
_LATIN = "text/html; charset=ISO-8859-1"
_PAGE = (
    "<html><head><title>Greenhouse</title></head><body><nav>Home | About</nav><article>"
    "<h1>Greenhouse log</h1>"
    + "".join(f"<p>Day {i}: the tomatoes in the Häuser were watered.</p>" for i in range(30))
    + "</article></body></html>"
)


class _Fetch:
    """Answers every URL with one response, or raises; records what was asked."""

    # By default a page in Latin-1: the worker stores it as UTF-8.
    def __init__(self, body: bytes = _PAGE.encode("latin-1"), content_type: str = _LATIN) -> None:
        self.body, self.content_type = body, content_type
        self.error: FetchError | None = None
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, url: str, max_bytes: int) -> FetchedResponse:
        self.calls.append((url, max_bytes))
        if self.error is not None:
            raise self.error
        return FetchedResponse(url, self.content_type, self.body)


@pytest.fixture
async def web(
    role_db: RoleDatabase,  # noqa: F811
    worker: tuple[str, str],  # noqa: F811
    tmp_path: Path,
) -> tuple[RoleDatabase, Ingestor, _Fetch]:
    dsn = await _knowledge_db(role_db, worker)
    assert dsn is not None
    fetch = _Fetch()
    ingestor = Ingestor(
        connect=connector(dsn, "-c search_path=knowledge"),
        blobs=LocalBlobStore(tmp_path / "blobs"),
        parsers=(HtmlParser(),),
        embeddings=_embeddings(),
        limits=Limits(1_000_000, 100, 50_000),
        chunk_max_tokens=50,
        policy="allow_hosted",
        fetch=fetch,
    )
    return role_db, ingestor, fetch


async def _base(db: RoleDatabase) -> uuid.UUID:
    kb = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO knowledge.bases (kb_id, owner_key, name, profile_id, processing)"
            " VALUES (%s, %s, 'kb', 1, 'hosted')",
            (kb, _OWNER),
        )
    return kb


async def _page(db: RoleDatabase, kb: uuid.UUID, url: str = _URL) -> uuid.UUID:
    """A web page as the add-by-URL route will leave it: URL recorded, no file, `queued`."""
    doc = uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO knowledge.documents (doc_id, kb_id, uploaded_by, title, mime_type,"
            " size_bytes, source_type, source_ref, status)"
            " VALUES (%s, %s, %s, 't', %s, 0, 'web', %s, 'queued')",
            (doc, kb, _OWNER, HTML, url),
        )
    return doc


async def _row(db: RoleDatabase, doc: uuid.UUID) -> dict[str, Any]:
    (row,) = await _rows(
        db.migrator_dsn,
        "SELECT status, error_code, blob_key, sha256, size_bytes, fetched_at IS NOT NULL,"
        " (SELECT count(*) FROM knowledge.chunks c WHERE c.doc_id = d.doc_id)"
        " FROM knowledge.documents d WHERE doc_id = %s",
        (doc,),
    )
    keys = ("status", "error_code", "blob_key", "sha256", "size", "fetched", "chunks")
    return dict(zip(keys, row, strict=True))


async def _text(db: RoleDatabase, doc: uuid.UUID) -> str:
    sql = "SELECT string_agg(text, ' ') FROM knowledge.chunks WHERE doc_id = %s"
    return str((await _rows(db.migrator_dsn, sql, (doc,)))[0][0])


async def test_a_page_is_fetched_once_stored_and_ingested(
    web: tuple[RoleDatabase, Ingestor, _Fetch],
) -> None:
    db, ingestor, fetch = web
    doc = await _page(db, await _base(db))
    assert await ingestor.ingest(doc) == "ready"
    row = await _row(db, doc)
    assert fetch.calls == [(_URL, 1_000_000)]
    assert (row["status"], row["error_code"], row["fetched"]) == ("ready", None, True)
    assert row["sha256"] == hashlib.sha256(_PAGE.encode()).hexdigest()
    assert row["size"] == len(_PAGE.encode())
    assert await ingestor.blobs.get(row["blob_key"], row["sha256"]) == _PAGE.encode()
    text = await _text(db, doc)
    assert "Day 29: the tomatoes in the Häuser were watered." in text
    assert "Home | About" not in text
    # Ingesting again (a retry, a re-index) parses the stored version: no second fetch.
    assert await ingestor.ingest(doc) == "ready"
    assert len(fetch.calls) == 1
    assert (await _row(db, doc))["blob_key"] == row["blob_key"]


@pytest.mark.parametrize(
    ("content_type", "body", "code"),
    [
        ("application/pdf", _PAGE.encode(), "unsupported_type"),
        ("text/html; charset=nope", _PAGE.encode(), "unsupported_encoding"),
        # Each invalid byte becomes a three-byte replacement character: past the cap.
        ("text/html", b"<p>" + b"\xff" * 400_000 + b"</p>", "fetch_too_large"),
    ],
)
async def test_a_response_that_is_not_a_storable_page_fails_the_document(
    web: tuple[RoleDatabase, Ingestor, _Fetch], content_type: str, body: bytes, code: str
) -> None:
    db, ingestor, fetch = web
    fetch.content_type, fetch.body = content_type, body
    doc = await _page(db, await _base(db))
    assert await ingestor.ingest(doc) == "failed"
    row = await _row(db, doc)
    assert (row["error_code"], row["blob_key"], row["fetched"]) == (code, None, False)


async def test_a_private_url_fails_at_once_and_a_timeout_is_retried(
    web: tuple[RoleDatabase, Ingestor, _Fetch],
) -> None:
    db, ingestor, fetch = web
    kb = await _base(db)
    real = Ingestor(**{**ingestor.__dict__, "fetch": fetch_page})  # refuses before connecting
    private = await _page(db, kb, "https://127.0.0.1/admin")
    assert await real.ingest(private, last_attempt=False) == "failed"
    assert (await _row(db, private))["error_code"] == "url_not_allowed"
    fetch.error = FetchError("fetch_timeout")
    slow = await _page(db, kb)
    with pytest.raises(FetchError):
        await ingestor.ingest(slow, last_attempt=False)
    assert await ingestor.ingest(slow, last_attempt=True) == "failed"
    row = await _row(db, slow)
    assert (row["error_code"], row["blob_key"], row["chunks"]) == ("fetch_timeout", None, 0)


async def test_the_same_content_twice_in_a_base_is_refused(
    web: tuple[RoleDatabase, Ingestor, _Fetch],
) -> None:
    db, ingestor, _ = web
    kb = await _base(db)
    first, second = await _page(db, kb), await _page(db, kb, _URL + "?utm=1")
    assert await ingestor.ingest(first) == "ready"
    assert await ingestor.ingest(second) == "failed"
    assert (await _row(db, second))["error_code"] == "duplicate_content"
    assert (await _row(db, first))["status"] == "ready"


async def test_a_page_deleted_before_its_fetch_is_skipped_and_purged(
    web: tuple[RoleDatabase, Ingestor, _Fetch],
) -> None:
    db, ingestor, fetch = web
    doc = await _page(db, await _base(db))
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "UPDATE knowledge.documents SET deleted_at = now() WHERE doc_id = %s", (doc,)
        )
    assert await ingestor.ingest(doc) == "skipped"
    assert fetch.calls == []
    assert await Purger(connect=ingestor.connect, blobs=ingestor.blobs).purge_document(doc) == 1


async def test_a_second_run_racing_the_first_ingests_the_stored_copy(
    web: tuple[RoleDatabase, Ingestor, _Fetch],
) -> None:
    db, ingestor, _ = web
    doc = await _page(db, await _base(db))
    other = _PAGE.replace("29", "XX").encode()
    first = Ingestor(**{**ingestor.__dict__, "fetch": _Fetch(other, "text/html")})
    # This run loaded the row before the other stored its page.
    real_put = ingestor.blobs.put

    async def put_after_the_other_run(*args: Any, **kwargs: Any) -> Any:
        object.__setattr__(ingestor.blobs, "put", real_put)
        assert await first.ingest(doc) == "ready"
        return await real_put(*args, **kwargs)

    object.__setattr__(ingestor.blobs, "put", put_after_the_other_run)
    assert await ingestor.ingest(doc) == "ready"
    row = await _row(db, doc)
    assert await ingestor.blobs.get(row["blob_key"], row["sha256"]) == other
    assert "Day XX" in (text := await _text(db, doc)) and "Day 29" not in text


async def test_the_schema_requires_a_file_or_a_url_and_keeps_a_file_once_set(
    web: tuple[RoleDatabase, Ingestor, _Fetch],
) -> None:
    db, ingestor, _ = web
    kb = await _base(db)
    doc = await _page(db, kb)
    assert await ingestor.ingest(doc) == "ready"
    changes = ("blob_key = 'other'", "sha256 = repeat('0', 64)", "size_bytes = 1")
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        for source, ref in (("upload", None), ("upload", _URL), ("web", None)):
            with pytest.raises(psycopg.errors.CheckViolation):
                await conn.execute(
                    "INSERT INTO knowledge.documents (doc_id, kb_id, uploaded_by, title,"
                    " mime_type, size_bytes, source_type, source_ref, status)"
                    " VALUES (%s, %s, %s, 't', %s, 0, %s, %s, 'queued')",
                    (uuid.uuid4(), kb, _OWNER, HTML, source, ref),
                )
        for change in changes:  # no role, the migrator included, can repoint a document
            with pytest.raises(psycopg.errors.CheckViolation):
                sql = f"UPDATE knowledge.documents SET {change} WHERE doc_id = %s"  # noqa: S608
                await conn.execute(sql, (doc,))
        await conn.execute(
            "UPDATE knowledge.documents SET status = 'failed' WHERE doc_id = %s", (doc,)
        )


async def test_search_and_the_document_list_name_the_page_and_its_fetch_time(
    web: tuple[RoleDatabase, Ingestor, _Fetch],
) -> None:
    db, ingestor, _ = web
    kb = await _owned_base(db, _OWNER)  # with the owner's grant, as the API creates it
    doc = await _page(db, kb)
    assert await ingestor.ingest(doc) == "ready"
    settings = Settings(env="test").model_copy(update={"knowledge_enabled": True})
    pool = lambda: _Connections(db.app_dsn)  # noqa: E731
    result = await Retriever(settings, pool, _embeddings()).search(_OWNER, "tomatoes watered", k=5)  # type: ignore[arg-type]
    assert result.passages
    assert {(p.source_url, p.fetched_at is not None) for p in result.passages} == {(_URL, True)}
    (listed,), _ = await KnowledgeBases(settings, pool).documents(  # type: ignore[arg-type]
        _OWNER, kb, limit=10, offset=0
    )
    assert (listed.source_url, listed.fetched_at) == (_URL, result.passages[0].fetched_at)
