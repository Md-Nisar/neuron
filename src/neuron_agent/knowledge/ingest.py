# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The `ingest_document` task: one document to one chunk set (ADR 0014 K4; RAG-02.04).

    queued -> parsing -> embedding -> ready | failed

The job carries the document id only; the knowledge base, file and settings come from the
document's row. Each status change is guarded: it never touches a tombstoned document
(`deleted_at` set or `deleting`), which the purge job owns. The chunk set is written in one
transaction that first deletes the document's previous chunks, so a re-run or a retry after a
crash replaces the set and never adds a second one. A failure records a stable `error_code`
only; chunk text and exception messages are never logged or stored.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
import structlog
from opentelemetry.trace import Span
from psycopg.rows import dict_row

from neuron_agent.config.settings import ProcessingPolicy
from neuron_agent.knowledge.blobs import BlobStore, BlobStoreError
from neuron_agent.knowledge.chunking import Chunk, chunk_document, estimate_tokens
from neuron_agent.knowledge.parsing import DocumentParser, Limits, ParseError, parse_document
from neuron_agent.knowledge.providers import (
    EmbeddingError,
    EmbeddingProvider,
    ensure_processing_allowed,
)
from neuron_agent.observability import metrics, semconv, telemetry

log = structlog.get_logger(__name__)

Connect = Callable[[], Awaitable[psycopg.AsyncConnection[dict[str, Any]]]]

_LOAD = (
    "SELECT d.kb_id, d.mime_type, d.blob_key, d.sha256, b.processing,"
    " b.ts_config::text AS ts_config, b.profile_id"
    " FROM knowledge.documents d JOIN knowledge.bases b USING (kb_id)"
    " WHERE d.doc_id = %s AND d.deleted_at IS NULL AND d.status <> 'deleting'"
    " AND b.deleted_at IS NULL"
)
_STATUS = (
    "UPDATE knowledge.documents SET status = %s, error_code = %s, updated_at = now()"
    " WHERE doc_id = %s AND deleted_at IS NULL AND status <> 'deleting'"
)
_LOCK = (
    "SELECT d.kb_id FROM knowledge.documents d JOIN knowledge.bases b USING (kb_id)"
    " WHERE d.doc_id = %s AND d.deleted_at IS NULL AND d.status <> 'deleting'"
    " AND b.deleted_at IS NULL FOR UPDATE OF d"
)
# Embedding is paid per chunk and the set is written in one transaction: a cap, below what the
# page and character caps alone allow (about 250,000 chunks of 400 tokens).
MAX_CHUNKS = 20_000
_INSERT_CHUNK = (
    "INSERT INTO knowledge.chunks (chunk_id, doc_id, kb_id, ordinal, text, headings, page_start,"
    " page_end, token_count, ts_config) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::regconfig)"
)
_INSERT_EMBEDDING = (
    "INSERT INTO knowledge.embeddings (chunk_id, profile_id, kb_id, embedding)"
    " VALUES (%s, %s, %s, %s)"
)
# Each ingestion adds what it sent to the embedding provider, so a re-run is charged again.
_READY = (
    "UPDATE knowledge.documents SET status = 'ready', error_code = NULL, parser_version = %s,"
    " page_count = %s, embedding_tokens = embedding_tokens + %s, updated_at = now()"
    " WHERE doc_id = %s AND deleted_at IS NULL AND status <> 'deleting'"
)


class _RefusedError(Exception):
    """Control flow inside `ingest`: the document fails with `code`; never raised past it."""

    def __init__(self, code: str) -> None:
        self.code = code


_CODED = (ParseError, EmbeddingError, BlobStoreError, _RefusedError)


@dataclass(frozen=True)
class Ingestor:
    connect: Connect
    blobs: BlobStore
    parsers: Sequence[DocumentParser]
    embeddings: EmbeddingProvider
    limits: Limits
    chunk_max_tokens: int
    policy: ProcessingPolicy

    async def ingest(self, doc_id: uuid.UUID, *, last_attempt: bool = True) -> str:
        """Run the document's ingestion and return its final status, or `skipped`.

        A retryable failure (a parser or embedding service that is down) is raised for the
        queue to retry, except on the last attempt, which records it as the document's error.
        """
        started, outcome = time.perf_counter(), "retry"
        attributes = {semconv.NEURON_KNOWLEDGE_DOC_ID: str(doc_id)}
        with telemetry.start_span(semconv.KNOWLEDGE_INGEST_SPAN, attributes=attributes) as span:
            try:
                outcome = await self._ingest(doc_id, span, last_attempt=last_attempt)
            except Exception as exc:
                telemetry.record_error(span, _code(exc))
                raise
            finally:
                span.set_attribute(semconv.NEURON_OUTCOME, outcome)
                metrics.record_knowledge_ingest(time.perf_counter() - started, outcome=outcome)
        return outcome

    async def _ingest(self, doc_id: uuid.UUID, span: Span, *, last_attempt: bool) -> str:
        async with await self.connect() as conn:
            row = await self._start(conn, doc_id)
            if row is None:
                log.info("knowledge.ingest.skipped", doc_id=str(doc_id))
                return "skipped"
            span.set_attribute(semconv.NEURON_KNOWLEDGE_KB_ID, str(row["kb_id"]))
            try:
                # Before anything is read: docling-serve is part of the deployment (internal, no
                # egress), so the setting governs the embedding provider, the only hosted step.
                with _stage("policy"):
                    ensure_processing_allowed(
                        row["processing"], self.embeddings.locality, self.policy
                    )
                chunks, parsed = await self._parse(row)
                span.set_attribute(semconv.NEURON_KNOWLEDGE_CHUNKS, len(chunks))
                await self._set(conn, doc_id, "embedding")
                with _stage("embed"):
                    vectors = await self.embeddings.embed_documents([_passage(c) for c in chunks])
            except (ParseError, EmbeddingError) as exc:
                if exc.retryable and not last_attempt:
                    raise
                return await self._fail_on(conn, doc_id, exc.code)
            except BlobStoreError as exc:
                # An unreachable store may come back; a missing or altered file will not.
                if exc.code == "blob_backend_error" and not last_attempt:
                    raise
                return await self._fail_on(conn, doc_id, exc.code)
            except _RefusedError as exc:
                return await self._fail_on(conn, doc_id, exc.code)
            with _stage("write"):
                written = await self._write(conn, doc_id, row, chunks, vectors, parsed)
        if not written:
            log.info("knowledge.ingest.skipped", doc_id=str(doc_id))  # tombstoned meanwhile
            return "skipped"
        log.info("knowledge.ingest.ready", doc_id=str(doc_id), chunks=len(chunks))
        return "ready"

    async def _start(
        self, conn: psycopg.AsyncConnection[dict[str, Any]], doc_id: uuid.UUID
    ) -> dict[str, Any] | None:
        async with conn.transaction():
            cursor = await conn.execute(_LOAD, (doc_id,))
            row = await cursor.fetchone()
            if row is not None:
                await conn.execute(_STATUS, ("parsing", None, doc_id))
        return row

    async def _parse(self, row: dict[str, Any]) -> tuple[list[Chunk], tuple[str, int | None]]:
        with _stage("fetch"):
            data = await self.blobs.get(row["blob_key"], row["sha256"])
        with _stage("parse"):
            parsed = await parse_document(data, row["mime_type"], self.limits, self.parsers)
            chunks = chunk_document(parsed, self.chunk_max_tokens)
            if not chunks:
                raise _RefusedError("no_text")
            if len(chunks) > MAX_CHUNKS:
                raise _RefusedError("too_many_chunks")
        return chunks, (parsed.parser_version, parsed.page_count)

    async def _set(
        self, conn: psycopg.AsyncConnection[dict[str, Any]], doc_id: uuid.UUID, status: str
    ) -> None:
        async with conn.transaction():
            await conn.execute(_STATUS, (status, None, doc_id))

    async def fail(self, doc_id: uuid.UUID, code: str) -> str:
        """Record a failure the task could not classify (its last attempt raised)."""
        async with await self.connect() as conn:
            return await self._fail_on(conn, doc_id, code)

    async def _fail_on(
        self, conn: psycopg.AsyncConnection[dict[str, Any]], doc_id: uuid.UUID, code: str
    ) -> str:
        """`failed` with `code`, and no chunks: a failed re-run leaves no stale set behind."""
        async with conn.transaction():
            if not await _lock(conn, doc_id):
                return "skipped"
            await conn.execute("DELETE FROM knowledge.chunks WHERE doc_id = %s", (doc_id,))
            await conn.execute(_STATUS, ("failed", code, doc_id))
        log.warning("knowledge.ingest.failed", doc_id=str(doc_id), error_code=code)
        return "failed"

    async def _write(
        self,
        conn: psycopg.AsyncConnection[dict[str, Any]],
        doc_id: uuid.UUID,
        row: dict[str, Any],
        chunks: Sequence[Chunk],
        vectors: Sequence[Sequence[float]],
        parsed: tuple[str, int | None],
    ) -> bool:
        """Replace the document's chunk set and mark it ready, all or nothing."""
        kb_id = row["kb_id"]
        async with conn.transaction():
            if not await _lock(conn, doc_id):
                return False
            # Embeddings go with their chunks (ON DELETE CASCADE).
            await conn.execute("DELETE FROM knowledge.chunks WHERE doc_id = %s", (doc_id,))
            ids = [uuid.uuid4() for _ in chunks]
            async with conn.cursor() as cursor:
                await cursor.executemany(
                    _INSERT_CHUNK,
                    [
                        (
                            chunk_id,
                            doc_id,
                            kb_id,
                            chunk.ordinal,
                            chunk.text,
                            list(chunk.headings),
                            chunk.page_start,
                            chunk.page_end,
                            chunk.token_count,
                            row["ts_config"],
                        )
                        for chunk_id, chunk in zip(ids, chunks, strict=True)
                    ],
                )
                await cursor.executemany(
                    _INSERT_EMBEDDING,
                    [
                        (chunk_id, row["profile_id"], kb_id, _vector(vector))
                        for chunk_id, vector in zip(ids, vectors, strict=True)
                    ],
                )
            tokens = sum(estimate_tokens(_passage(chunk)) for chunk in chunks)
            await conn.execute(_READY, (*parsed, tokens, doc_id))
        return True


# What a stage records for an error with no stable code; the worker stores the same code.
_UNEXPECTED = "ingest_failed"


def _code(exc: Exception) -> str:
    """The stable code of one of our errors; any other `.code` (a provider's) is not trusted."""
    return exc.code if isinstance(exc, _CODED) else _UNEXPECTED


@contextmanager
def _stage(name: str) -> Iterator[None]:
    """A child span for one ingestion stage; a failure counts by its stable code only."""
    span_name = f"{semconv.KNOWLEDGE_INGEST_SPAN}.{name}"
    with telemetry.start_span(span_name, attributes={semconv.NEURON_KNOWLEDGE_STAGE: name}) as span:
        try:
            yield
        except Exception as exc:
            code = _code(exc)
            telemetry.record_error(span, code)
            metrics.record_knowledge_stage_error(name, code)
            raise


async def _lock(conn: psycopg.AsyncConnection[dict[str, Any]], doc_id: uuid.UUID) -> bool:
    """Lock a live document's row and scope the transaction to its knowledge base.

    False when it was tombstoned. RLS on chunks and embeddings then admits only that base, so
    every read, delete and insert after this sees this document's base and nothing else.
    """
    cursor = await conn.execute(_LOCK, (doc_id,))
    if (row := await cursor.fetchone()) is None:
        return False
    await conn.execute("SELECT set_config('neuron.kb_ids', %s, true)", (str(row["kb_id"]),))
    return True


def _passage(chunk: Chunk) -> str:
    """What is embedded: the heading path, then the text, so a chunk keeps its context."""
    return "\n".join([*chunk.headings, chunk.text])


def _vector(values: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(value)) for value in values) + "]"


def connector(dsn: str, options: str) -> Connect:
    async def connect() -> psycopg.AsyncConnection[dict[str, Any]]:
        return await psycopg.AsyncConnection.connect(dsn, row_factory=dict_row, options=options)

    return connect
