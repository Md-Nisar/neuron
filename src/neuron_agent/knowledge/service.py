# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Knowledge base management for the API (ADR 0014; RAG-03.01).

Every statement filters on the caller's owner key (ADR 0014 requirement 2), so another user's
base, a deleted one and an unknown id are the same `knowledge_base_not_found`. Delete is a
tombstone: `deleted_at` hides the base from every query at once, and the purge job, queued in
the same transaction, removes its documents, chunks and files (RAG-03.03).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from typing import Any

import psycopg
import structlog
from psycopg_pool import AsyncConnectionPool

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import (
    KnowledgeBaseLimitError,
    KnowledgeBaseNotFoundError,
    KnowledgeDisabledError,
    KnowledgeDocumentNotFoundError,
    PersistenceError,
)
from neuron_agent.knowledge import jobs
from neuron_agent.knowledge.authorization import KnowledgeAuthorization
from neuron_agent.observability.audit import audit
from neuron_agent.persistence.migrations import KNOWLEDGE_PROFILE_ID
from neuron_agent.schemas.knowledge import KnowledgeBase, KnowledgeDocument
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


class KnowledgeBases:
    def __init__(
        self, settings: Settings, pool: Callable[[], AsyncConnectionPool[Any] | None]
    ) -> None:
        self._settings = settings
        self._pool = pool

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
    ) -> None:
        audit(
            event,
            outcome="allowed",
            actor=owner_key[:12] if self._settings.auth_mode == "jwt" else None,
            issuer_id=self._settings.auth_issuer_id,
            action=action,
            resource_type="knowledge_base",
            resource_id=str(kb_id) if kb_id else None,
            count=count,
        )
