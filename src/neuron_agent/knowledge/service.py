# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Knowledge base management for the API (ADR 0014; RAG-03.01).

Every statement filters on the caller's owner key (ADR 0014 requirement 2), so another user's
base, a deleted one and an unknown id are the same `knowledge_base_not_found`. Delete is a
tombstone: `deleted_at` hides the base from every query at once, and the purge job, queued in
the same transaction, removes its documents, chunks and files (RAG-03.03).
"""

from __future__ import annotations

import contextlib
import hashlib
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any

import anyio
import psycopg
import structlog
from psycopg_pool import AsyncConnectionPool

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import (
    IdempotencyKeyReusedError,
    IngestionConcurrencyError,
    KnowledgeBaseLimitError,
    KnowledgeBaseNotFoundError,
    KnowledgeDisabledError,
    KnowledgeDocumentNotFoundError,
    PersistenceError,
    UploadRefusedError,
)
from neuron_agent.knowledge import jobs
from neuron_agent.knowledge.authorization import KnowledgeAuthorization
from neuron_agent.knowledge.blobs import BlobStore
from neuron_agent.knowledge.parsing import Limits, ParseError, accepted_type
from neuron_agent.observability.audit import audit
from neuron_agent.persistence.migrations import KNOWLEDGE_PROFILE_ID
from neuron_agent.schemas.knowledge import DocumentAccepted, KnowledgeBase, KnowledgeDocument
from neuron_agent.security.authorization import AuthorizationContext

log = structlog.get_logger(__name__)

_READ, _WRITE = "knowledge:read", "knowledge:write"

_LIST = (
    "SELECT kb_id, name, processing, created_at FROM knowledge.bases"
    " WHERE kb_id = ANY(%s) AND owner_key = %s AND deleted_at IS NULL ORDER BY created_at, kb_id"
)
_COUNT = "SELECT count(*) AS n FROM knowledge.bases WHERE owner_key = %s AND deleted_at IS NULL"
_CREATE = (
    "INSERT INTO knowledge.bases (kb_id, owner_key, name, processing, profile_id)"
    " VALUES (%s, %s, %s, %s, %s) RETURNING kb_id, name, processing, created_at"
)
_OWNER_GRANT = (
    "INSERT INTO knowledge.grants (kb_id, subject_type, subject, access, granted_by)"
    " VALUES (%s, 'owner', %s, 'admin', %s)"
)
_RENAME = (
    "UPDATE knowledge.bases SET name = %s"
    " WHERE kb_id = %s AND owner_key = %s AND deleted_at IS NULL"
    " RETURNING kb_id, name, processing, created_at"
)
_TOMBSTONE = (
    "UPDATE knowledge.bases SET deleted_at = now()"
    " WHERE kb_id = %s AND owner_key = %s AND deleted_at IS NULL RETURNING kb_id"
)

# Documents are found through the bases the caller may read (`allowed_kbs`) and the base's owner
# (ADR 0014 requirement 2); a tombstoned document or base is never shown.
_DOCUMENT_FILTER = (
    " FROM knowledge.documents d JOIN knowledge.bases b USING (kb_id)"
    " WHERE d.kb_id = ANY(%(kbs)s) AND b.owner_key = %(owner)s AND b.deleted_at IS NULL"
    " AND d.deleted_at IS NULL AND d.status <> 'deleting'"
)
_DOCUMENT_COLUMNS = (
    "SELECT d.doc_id, d.kb_id, d.title, d.mime_type, d.size_bytes, d.page_count, d.status,"
    " d.error_code, d.created_at, d.updated_at"
)
_DOCUMENT = _DOCUMENT_COLUMNS + _DOCUMENT_FILTER + " AND d.doc_id = %(doc)s"
_DOCUMENTS = (
    _DOCUMENT_COLUMNS
    + _DOCUMENT_FILTER
    + " AND d.kb_id = %(kb)s ORDER BY d.created_at, d.doc_id LIMIT %(limit)s OFFSET %(offset)s"
)
_DOCUMENT_COUNT = "SELECT count(*) AS n" + _DOCUMENT_FILTER + " AND d.kb_id = %(kb)s"

_LIVE_BASE = (
    "SELECT kb_id FROM knowledge.bases WHERE kb_id = %s AND owner_key = %s AND deleted_at IS NULL"
)
# An `Idempotency-Key` is the caller's, across bases (the index is per uploader): a replay is
# honoured only for the same base while the document and base are live.
_BY_KEY = (
    "SELECT d.doc_id, d.kb_id, d.status, d.kb_id = %(kb)s AND d.deleted_at IS NULL"
    " AND b.deleted_at IS NULL AND b.owner_key = %(owner)s AS replayable"
    " FROM knowledge.documents d JOIN knowledge.bases b USING (kb_id)"
    " WHERE d.uploaded_by = %(owner)s AND d.idempotency_key = %(key)s"
)
_BY_SHA = (
    "SELECT d.doc_id, d.kb_id, d.status"
    " FROM knowledge.documents d JOIN knowledge.bases b USING (kb_id)"
    " WHERE d.kb_id = %(kb)s AND d.sha256 = %(sha)s AND d.deleted_at IS NULL"
    " AND b.owner_key = %(owner)s AND b.deleted_at IS NULL"
)
# Into a live base of the caller's only. A concurrent upload of the same content or key loses on
# the unique indexes and returns the winner's document.
_INSERT_DOCUMENT = (
    "INSERT INTO knowledge.documents (doc_id, kb_id, uploaded_by, title, mime_type, size_bytes,"
    " sha256, blob_key, idempotency_key, status)"
    " SELECT %(doc)s, kb_id, %(owner)s, %(title)s, %(mime)s, %(size)s, %(sha)s, %(blob)s,"
    " %(key)s, 'queued' FROM knowledge.bases"
    " WHERE kb_id = %(kb)s AND owner_key = %(owner)s AND deleted_at IS NULL"
    " ON CONFLICT DO NOTHING RETURNING doc_id"
)
# What the uploader holds (ADR 0014 requirement 7; RAG-02.05). Bytes, documents and pages count
# every row until the purge deletes it, since its file is still stored; documents being ingested
# count while their base is live, as the worker skips the rest.
_USAGE = (
    "SELECT count(*) AS documents, coalesce(sum(d.size_bytes), 0) AS bytes,"
    " coalesce(sum(d.page_count), 0) AS pages, count(*) FILTER (WHERE d.status IN"
    " ('queued', 'parsing', 'embedding') AND d.deleted_at IS NULL AND b.deleted_at IS NULL)"
    " AS ingesting FROM knowledge.documents d JOIN knowledge.bases b USING (kb_id)"
    " WHERE d.uploaded_by = %s"
)
_UPLOAD_STATUS = {"file_too_large": 413, "empty_file": 422}


def _accepted(row: dict[str, Any]) -> DocumentAccepted:
    return DocumentAccepted(
        doc_id=row["doc_id"],
        kb_id=row["kb_id"],
        status=row["status"],
        status_url=f"/v1/knowledge/documents/{row['doc_id']}",
    )


async def _once(data: bytes) -> AsyncIterator[bytes]:
    yield data


class KnowledgeBases:
    def __init__(
        self,
        settings: Settings,
        pool: Callable[[], AsyncConnectionPool[Any] | None],
        blobs: Callable[[], BlobStore] | None = None,
    ) -> None:
        self._settings = settings
        self._pool = pool
        self._blobs = blobs

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
        if not self._settings.knowledge_enabled:
            raise KnowledgeDisabledError("knowledge is not enabled")
        pool = self._pool()
        if pool is None:
            raise PersistenceError("knowledge needs the Postgres pool")
        try:
            async with pool.connection() as conn, conn.transaction():
                yield conn
        except psycopg.Error as exc:
            log.warning("knowledge_operation_failed", error_type=type(exc).__name__)
            raise PersistenceError("knowledge persistence failed") from exc

    async def list(self, owner_key: str) -> list[KnowledgeBase]:
        async with self._transaction() as conn:
            allowed = await KnowledgeAuthorization.allowed_kbs(
                conn, AuthorizationContext(frozenset(), owner_key=owner_key)
            )
            # Phase 1: the grants and the owner predicate agree. Role grants (Phase 2) must keep
            # `allowed_kbs` as the filter, and rename and delete must check `allowed.write`.
            cursor = await conn.execute(_LIST, (list(allowed.read), owner_key))
            bases = [KnowledgeBase(**row) for row in await cursor.fetchall()]
        self._audit("knowledge_bases_read", owner_key, _READ, count=len(bases))
        return bases

    async def create(self, owner_key: str, name: str, processing: str) -> KnowledgeBase:
        async with self._transaction() as conn:
            # Serialises one owner's creates, so concurrent requests cannot pass the limit.
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"knowledge.bases:{owner_key}",),
            )
            cursor = await conn.execute(_COUNT, (owner_key,))
            row = await cursor.fetchone()
            if row is not None and row["n"] >= self._settings.knowledge_max_bases_per_user:
                raise KnowledgeBaseLimitError("knowledge base limit reached")
            cursor = await conn.execute(
                _CREATE, (uuid.uuid4(), owner_key, name, processing, KNOWLEDGE_PROFILE_ID)
            )
            created = await cursor.fetchone()
            assert created is not None  # nosec B101
            await conn.execute(_OWNER_GRANT, (created["kb_id"], owner_key, owner_key))
        base = KnowledgeBase(**created)
        self._audit("knowledge_base_created", owner_key, _WRITE, base.kb_id)
        return base

    async def rename(self, owner_key: str, kb_id: uuid.UUID, name: str) -> KnowledgeBase:
        async with self._transaction() as conn:
            cursor = await conn.execute(_RENAME, (name, kb_id, owner_key))
            row = await cursor.fetchone()
        if row is None:
            raise KnowledgeBaseNotFoundError("knowledge base not found")
        self._audit("knowledge_base_renamed", owner_key, _WRITE, kb_id)
        return KnowledgeBase(**row)

    async def delete(self, owner_key: str, kb_id: uuid.UUID) -> None:
        """Tombstone the base and queue its purge; a second delete finds nothing to delete."""
        async with self._transaction() as conn:
            cursor = await conn.execute(_TOMBSTONE, (kb_id, owner_key))
            if await cursor.fetchone() is None:
                raise KnowledgeBaseNotFoundError("knowledge base not found")
            await jobs.defer(conn, jobs.Task.PURGE_KNOWLEDGE_BASE, kb_id=kb_id)
        self._audit("knowledge_base_deleted", owner_key, _WRITE, kb_id)

    async def check_upload(
        self, owner_key: str, kb_id: uuid.UUID, idempotency_key: str | None
    ) -> DocumentAccepted | None:
        """Before the body is read: the first document of a repeated `Idempotency-Key`, or None
        when the upload may go ahead. `404` unless the base is the caller's and live."""
        async with self._transaction() as conn:
            if idempotency_key is not None:
                cursor = await conn.execute(
                    _BY_KEY, {"kb": kb_id, "owner": owner_key, "key": idempotency_key}
                )
                if (row := await cursor.fetchone()) is not None:
                    if not row["replayable"]:
                        raise IdempotencyKeyReusedError("idempotency key reused")
                    return _accepted(row)
            cursor = await conn.execute(_LIVE_BASE, (kb_id, owner_key))
            if await cursor.fetchone() is None:
                raise KnowledgeBaseNotFoundError("knowledge base not found")
        return None

    async def upload(
        self,
        owner_key: str,
        kb_id: uuid.UUID,
        *,
        data: bytes,
        claimed_type: str,
        title: str,
        idempotency_key: str | None,
    ) -> DocumentAccepted:
        """Check the file, store it and queue its ingestion, or return the base's existing copy.

        A refused file stores nothing. The document row and its job commit together; if they do
        not, the stored file is deleted.
        """
        limits = Limits.from_settings(self._settings)
        try:
            media_type = await anyio.to_thread.run_sync(accepted_type, data, claimed_type, limits)
        except ParseError as exc:
            raise UploadRefusedError(exc.code, _UPLOAD_STATUS.get(exc.code, 415)) from None
        sha256 = hashlib.sha256(data).hexdigest()
        if (
            existing := await self._existing(owner_key, kb_id, sha256, idempotency_key)
        ) is not None:
            return existing
        async with self._transaction() as conn:
            await self._check_quota(conn, owner_key, len(data))
        assert self._blobs is not None  # nosec B101 - wired with knowledge on
        blobs = self._blobs()
        blob = await blobs.put(_once(data), max_bytes=limits.max_bytes)
        doc_id, queued = uuid.uuid4(), False
        try:
            async with self._transaction() as conn:
                # Again under the owner's lock, so concurrent uploads cannot pass a quota together.
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"knowledge.documents:{owner_key}",),
                )
                await self._check_quota(conn, owner_key, blob.size)
                cursor = await conn.execute(
                    _INSERT_DOCUMENT,
                    {
                        "doc": doc_id,
                        "owner": owner_key,
                        "title": title,
                        "mime": media_type,
                        "size": blob.size,
                        "sha": blob.sha256,
                        "blob": blob.key,
                        "key": idempotency_key,
                        "kb": kb_id,
                    },
                )
                if await cursor.fetchone() is not None:
                    await jobs.defer(conn, jobs.Task.INGEST_DOCUMENT, doc_id=doc_id)
                    queued = True
        finally:
            if not queued:
                # Also when the request is cancelled: an orphan blob, never a lost error.
                with anyio.CancelScope(shield=True), contextlib.suppress(Exception):
                    await blobs.delete(blob.key)
        if not queued:
            # Lost a race on the same content or key, or the base was deleted meanwhile.
            log.info("knowledge_upload_not_inserted", kb_id=str(kb_id))
            existing = await self._existing(owner_key, kb_id, sha256, idempotency_key)
            if existing is None:
                raise KnowledgeBaseNotFoundError("knowledge base not found")
            return existing
        self._audit(
            "knowledge_document_uploaded", owner_key, _WRITE, doc_id, resource="knowledge_document"
        )
        return _accepted({"doc_id": doc_id, "kb_id": kb_id, "status": "queued"})

    async def _check_quota(
        self, conn: psycopg.AsyncConnection[Any], owner_key: str, size: int
    ) -> None:
        """Refuse an upload of `size` bytes that would take the owner past a quota."""
        cursor = await conn.execute(_USAGE, (owner_key,))
        usage = await cursor.fetchone()
        assert usage is not None  # nosec B101 - an aggregate always returns a row
        settings = self._settings
        if usage["documents"] >= settings.knowledge_max_documents_per_user:
            raise UploadRefusedError("document_quota_exceeded", 413)
        if usage["bytes"] + size > settings.knowledge_max_bytes_per_user:
            raise UploadRefusedError("byte_quota_exceeded", 413)
        if usage["pages"] >= settings.knowledge_max_pages_per_user:
            raise UploadRefusedError("page_quota_exceeded", 413)
        if usage["ingesting"] >= settings.knowledge_max_ingesting_per_user:
            raise IngestionConcurrencyError("too many documents being ingested")

    async def _existing(
        self, owner_key: str, kb_id: uuid.UUID, sha256: str, idempotency_key: str | None
    ) -> DocumentAccepted | None:
        if (replay := await self.check_upload(owner_key, kb_id, idempotency_key)) is not None:
            return replay
        async with self._transaction() as conn:
            cursor = await conn.execute(_BY_SHA, {"kb": kb_id, "sha": sha256, "owner": owner_key})
            row = await cursor.fetchone()
        return _accepted(row) if row is not None else None

    async def documents(
        self, owner_key: str, kb_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[Sequence[KnowledgeDocument], int]:
        """A page of a readable base's documents and their total; any other base is `404`."""
        async with self._transaction() as conn:
            kbs = await self._readable(conn, owner_key)
            if kb_id not in kbs:
                raise KnowledgeBaseNotFoundError("knowledge base not found")
            params = {"kbs": kbs, "owner": owner_key, "kb": kb_id}
            cursor = await conn.execute(_DOCUMENTS, {**params, "limit": limit, "offset": offset})
            documents = [KnowledgeDocument(**row) for row in await cursor.fetchall()]
            cursor = await conn.execute(_DOCUMENT_COUNT, params)
            total = await cursor.fetchone()
        self._audit("knowledge_documents_read", owner_key, _READ, kb_id, count=len(documents))
        return documents, int(total["n"]) if total else 0

    async def document(self, owner_key: str, doc_id: uuid.UUID) -> KnowledgeDocument:
        """One document of a readable base; any other id is `404`."""
        async with self._transaction() as conn:
            kbs = await self._readable(conn, owner_key)
            cursor = await conn.execute(_DOCUMENT, {"kbs": kbs, "owner": owner_key, "doc": doc_id})
            row = await cursor.fetchone()
        if row is None:
            raise KnowledgeDocumentNotFoundError("knowledge document not found")
        return KnowledgeDocument(**row)

    @staticmethod
    async def _readable(conn: psycopg.AsyncConnection[Any], owner_key: str) -> Sequence[uuid.UUID]:
        allowed = await KnowledgeAuthorization.allowed_kbs(
            conn, AuthorizationContext(frozenset(), owner_key=owner_key)
        )
        return [*allowed.read]

    def _audit(
        self,
        event: str,
        owner_key: str,
        action: str,
        kb_id: uuid.UUID | None = None,
        *,
        count: int | None = None,
        resource: str = "knowledge_base",
    ) -> None:
        audit(
            event,
            outcome="allowed",
            actor=owner_key[:12] if self._settings.auth_mode == "jwt" else None,
            issuer_id=self._settings.auth_issuer_id,
            action=action,
            resource_type=resource,
            resource_id=str(kb_id) if kb_id else None,
            count=count,
        )
