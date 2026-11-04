"""`ingest_document` on Postgres as the worker role (RAG-02.04 AC1-AC4).

Fake embeddings and the plain-text parser, a local blob store; needs pgvector, as the other
knowledge tests do.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from test_postgres_knowledge_tables import _knowledge_db, worker  # noqa: F401
from test_postgres_roles import RoleDatabase, _rows, role_db, roles  # noqa: F401

from neuron_agent.knowledge import ingest
from neuron_agent.knowledge.blobs import LocalBlobStore
from neuron_agent.knowledge.ingest import Ingestor, connector
from neuron_agent.knowledge.parsing import (
    MARKDOWN,
    TEXT,
    Limits,
    ParsedDocument,
    ParseError,
    PlainTextParser,
)
from neuron_agent.knowledge.providers import EmbeddingProvider, FakeEmbeddings

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_OWNER = "c" * 64
_TEXT = "Greenhouse log\n\n" + "\n\n".join(
    f"Day {i}: the tomatoes were watered." for i in range(40)
)


class _Flaky:
    """A parser whose service is down: a retryable error."""

    media_types = frozenset({TEXT})

    async def parse(self, data: bytes, media_type: str, limits: Limits) -> ParsedDocument:
        raise ParseError("parser_unavailable", retryable=True)


def _embeddings(locality: Any = "self_hosted") -> EmbeddingProvider:
    fake = FakeEmbeddings(1024)
    return EmbeddingProvider(
        fake, fake, dimensions=1024, locality=locality, batch_size=8, max_retries=0
    )


@pytest.fixture
async def setup(
    role_db: RoleDatabase,  # noqa: F811
    worker: tuple[str, str],  # noqa: F811
    tmp_path: Path,
) -> tuple[RoleDatabase, Ingestor]:
    dsn = await _knowledge_db(role_db, worker)
    assert dsn is not None
    return (
        role_db,
        Ingestor(
            connect=connector(dsn, "-c search_path=knowledge"),
            blobs=LocalBlobStore(tmp_path / "blobs"),
            parsers=(PlainTextParser(),),
            embeddings=_embeddings(),
            limits=Limits(1_000_000, 100, 50_000),
            chunk_max_tokens=50,
            policy="allow_hosted",
        ),
    )


async def _document(
    db: RoleDatabase,
    ingestor: Ingestor,
    text: str = _TEXT,
    processing: str = "hosted",
    mime_type: str = TEXT,
) -> uuid.UUID:
    """An uploaded document as RAG-03.02 will leave it: blob stored, row `queued`."""

    async def body() -> AsyncIterator[bytes]:
        yield text.encode()

    blob = await ingestor.blobs.put(body(), max_bytes=1_000_000)
    kb, doc = uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO knowledge.bases (kb_id, owner_key, name, profile_id, processing)"
            " VALUES (%s, %s, 'kb', 1, %s)",
            (kb, _OWNER, processing),
        )
        await conn.execute(
            "INSERT INTO knowledge.documents (doc_id, kb_id, uploaded_by, title, mime_type,"
            " size_bytes, sha256, blob_key, status) VALUES (%s, %s, %s, 't', %s, %s,"
            " %s, %s, 'queued')",
            (doc, kb, _OWNER, mime_type, blob.size, blob.sha256, blob.key),
        )
    return doc


async def _state(db: RoleDatabase, doc: uuid.UUID) -> dict[str, Any]:
    (row,) = await _rows(
        db.migrator_dsn,
        "SELECT status, error_code, parser_version FROM knowledge.documents WHERE doc_id = %s",
        (doc,),
    )
    chunks = await _rows(
        db.migrator_dsn,
        "SELECT ordinal, text, headings, page_start, token_count FROM knowledge.chunks"
        " WHERE doc_id = %s ORDER BY ordinal",
        (doc,),
    )
    (embedded,) = await _rows(
        db.migrator_dsn,
        "SELECT count(*) FROM knowledge.embeddings e JOIN knowledge.chunks c USING (chunk_id)"
        " WHERE c.doc_id = %s AND e.profile_id = 1",
        (doc,),
    )
    return {"document": row, "chunks": chunks, "embedded": embedded[0]}


async def test_a_second_run_leaves_exactly_one_chunk_set(
    setup: tuple[RoleDatabase, Ingestor],
) -> None:
    db, ingestor = setup
    doc = await _document(db, ingestor)
    assert await ingestor.ingest(doc) == "ready"
    first = await _state(db, doc)
    assert first["document"] == ("ready", None, "plain-text/1")
    assert len(first["chunks"]) > 1
    assert first["embedded"] == len(first["chunks"])
    assert await ingestor.ingest(doc) == "ready"
    assert await _state(db, doc) == first


async def test_a_crash_before_commit_then_a_retry_equals_a_clean_run(
    setup: tuple[RoleDatabase, Ingestor], monkeypatch: pytest.MonkeyPatch
) -> None:
    db, ingestor = setup
    clean = await _document(db, ingestor)
    await ingestor.ingest(clean)
    doc = await _document(db, ingestor)
    # The last statement of the chunk-set transaction fails: everything in it is rolled back.
    with monkeypatch.context() as patch:
        patch.setattr(ingest, "_READY", "SELECT 1 / 0, %s::text, %s::text, %s::uuid")
        with pytest.raises(psycopg.errors.DivisionByZero):
            await ingestor.ingest(doc)
    crashed = await _state(db, doc)
    assert (crashed["document"][0], crashed["chunks"], crashed["embedded"]) == ("embedding", [], 0)
    assert await ingestor.ingest(doc) == "ready"
    assert await _state(db, doc) == await _state(db, clean)


async def test_a_parser_error_fails_the_document_and_leaves_no_chunks(
    setup: tuple[RoleDatabase, Ingestor],
) -> None:
    db, ingestor = setup
    doc = await _document(db, ingestor)
    await ingestor.ingest(doc)

    # The file is replaced by bytes that are not text (as a corrupt re-upload would be).
    async def body() -> AsyncIterator[bytes]:
        yield b"\x00\x01binary"

    blob = await ingestor.blobs.put(body(), max_bytes=1_000)
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "UPDATE knowledge.documents SET blob_key = %s, sha256 = %s WHERE doc_id = %s",
            (blob.key, blob.sha256, doc),
        )
    assert await ingestor.ingest(doc) == "failed"
    state = await _state(db, doc)
    assert state["document"][:2] == ("failed", "media_type_mismatch")
    assert (state["chunks"], state["embedded"]) == ([], 0)


async def test_a_tombstoned_document_is_left_to_the_purge_job(
    setup: tuple[RoleDatabase, Ingestor],
) -> None:
    db, ingestor = setup
    doc = await _document(db, ingestor)
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "UPDATE knowledge.documents SET status = 'deleting', deleted_at = now()"
            " WHERE doc_id = %s",
            (doc,),
        )
    assert await ingestor.ingest(doc) == "skipped"
    state = await _state(db, doc)
    assert (state["document"][0], state["chunks"]) == ("deleting", [])


async def test_an_unavailable_parser_is_retried_until_the_last_attempt(
    setup: tuple[RoleDatabase, Ingestor],
) -> None:
    db, ingestor = setup
    doc = await _document(db, ingestor)
    flaky = Ingestor(**{**ingestor.__dict__, "parsers": (_Flaky(),)})
    with pytest.raises(ParseError):
        await flaky.ingest(doc, last_attempt=False)
    assert (await _state(db, doc))["document"][0] == "parsing"
    assert await flaky.ingest(doc, last_attempt=True) == "failed"
    assert (await _state(db, doc))["document"][:2] == ("failed", "parser_unavailable")


async def test_a_self_hosted_base_is_never_sent_to_a_hosted_provider(
    setup: tuple[RoleDatabase, Ingestor],
) -> None:
    db, ingestor = setup
    doc = await _document(db, ingestor, processing="self_hosted")
    hosted = Ingestor(**{**ingestor.__dict__, "embeddings": _embeddings("hosted")})
    assert await hosted.ingest(doc) == "failed"
    state = await _state(db, doc)
    assert state["document"][:2] == ("failed", "processing_locality_forbidden")
    assert state["chunks"] == []


async def test_a_document_without_text_fails(setup: tuple[RoleDatabase, Ingestor]) -> None:
    db, ingestor = setup
    doc = await _document(db, ingestor, text="# Only a heading\n", mime_type=MARKDOWN)
    assert await ingestor.ingest(doc) == "failed"
    assert (await _state(db, doc))["document"][:2] == ("failed", "no_text")


async def test_a_document_over_the_chunk_cap_fails(
    setup: tuple[RoleDatabase, Ingestor], monkeypatch: pytest.MonkeyPatch
) -> None:
    db, ingestor = setup
    doc = await _document(db, ingestor)
    monkeypatch.setattr(ingest, "MAX_CHUNKS", 2)
    assert await ingestor.ingest(doc) == "failed"
    state = await _state(db, doc)
    assert (state["document"][:2], state["chunks"]) == (("failed", "too_many_chunks"), [])


async def test_a_base_deleted_during_ingestion_gets_no_chunks(
    setup: tuple[RoleDatabase, Ingestor],
) -> None:
    db, ingestor = setup
    doc = await _document(db, ingestor)

    class _Deleting:
        """The base is deleted while the worker reads the file (the purge job owns the rest)."""

        async def get(self, key: str, sha256: str) -> bytes:
            async with await psycopg.AsyncConnection.connect(
                db.migrator_dsn, autocommit=True
            ) as conn:
                await conn.execute(
                    "UPDATE knowledge.bases SET deleted_at = now()"
                    " WHERE kb_id = (SELECT kb_id FROM knowledge.documents WHERE doc_id = %s)",
                    (doc,),
                )
            return await ingestor.blobs.get(key, sha256)

    racing = Ingestor(**{**ingestor.__dict__, "blobs": _Deleting()})
    assert await racing.ingest(doc) == "skipped"
    state = await _state(db, doc)
    assert (state["document"][0], state["chunks"], state["embedded"]) == ("embedding", [], 0)
