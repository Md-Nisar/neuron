# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The purge tasks: a tombstoned document or knowledge base removed for good (RAG-03.03).

A delete in the API sets `deleted_at` (and `deleting` on documents) and queues the purge in the
same transaction, so no read path returns the rows from then on. The purge deletes each
document's file, then its row, whose chunks and embeddings go with it (ON DELETE CASCADE), and
last the base's row, whose grants go with it. The file goes first and each document commits on
its own: a purge stopped half way leaves rows for the retry to find, never a row-less file, and
a file already gone counts as deleted. Only a row whose own or base's `deleted_at` is set is
ever purged.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import psycopg

from neuron_agent.knowledge.blobs import BlobStore
from neuron_agent.knowledge.ingest import Connect

_TOMBSTONED = (
    "SELECT d.doc_id, d.blob_key FROM knowledge.documents d JOIN knowledge.bases b USING (kb_id)"
)
_DOCUMENT = _TOMBSTONED + (
    " WHERE d.doc_id = %s AND (d.deleted_at IS NOT NULL OR b.deleted_at IS NOT NULL)"
)
# Every document of a deleted base, also one uploaded before the base's delete tombstoned them.
_BASE_DOCUMENTS = _TOMBSTONED + " WHERE d.kb_id = %s AND b.deleted_at IS NOT NULL"
_DELETE_DOCUMENT = (
    "DELETE FROM knowledge.documents WHERE doc_id = %s AND (deleted_at IS NOT NULL"
    " OR kb_id IN (SELECT kb_id FROM knowledge.bases WHERE deleted_at IS NOT NULL))"
)
_DELETE_BASE = "DELETE FROM knowledge.bases WHERE kb_id = %s AND deleted_at IS NOT NULL"


@dataclass(frozen=True)
class Purger:
    connect: Connect
    blobs: BlobStore

    async def purge_document(self, doc_id: uuid.UUID) -> int:
        """Remove a tombstoned document; return how many were removed (0 or 1)."""
        async with await self.connect() as conn:
            return await self._purge(conn, _DOCUMENT, doc_id)

    async def purge_base(self, kb_id: uuid.UUID) -> int:
        """Remove a deleted base and its documents; return how many documents were removed."""
        async with await self.connect() as conn:
            removed = await self._purge(conn, _BASE_DOCUMENTS, kb_id)  # raises if any is left
            async with conn.transaction():
                await conn.execute(_DELETE_BASE, (kb_id,))
        return removed

    async def _purge(
        self, conn: psycopg.AsyncConnection[dict[str, Any]], query: str, key: uuid.UUID
    ) -> int:
        async with conn.transaction():
            cursor = await conn.execute(query, (key,))
            documents = await cursor.fetchall()
        # One document that cannot be purged does not hold up the others; the first error is
        # raised at the end, so the job is retried for what is left.
        failed: Exception | None = None
        for document in documents:
            try:
                await self.blobs.delete(document["blob_key"])
                async with conn.transaction():
                    await conn.execute(_DELETE_DOCUMENT, (document["doc_id"],))
            except Exception as exc:  # noqa: BLE001 - raised below
                failed = failed or exc
        if failed is not None:
            raise failed
        return len(documents)
