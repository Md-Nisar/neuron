# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The re-index job and the swap (ADR 0014 amendment "re-index to a new profile", RAG-09.04).

`reindex_kb` embeds the chunks of a base's ready documents that have no vector under the
`building` profile, with the re-index model, one document per transaction, and charges the
tokens to the document. A document already covered is skipped, so a retry costs nothing twice.
Then it attempts the swap, as the periodic `reindex_swap` task does: under a `FOR UPDATE` lock
on the building profile, every ready chunk of every live base must have a vector under it, or
the bases still missing some get a `reindex_kb` job and the old profile stays active. Otherwise
the building profile becomes `active`, the old one `retired`, and every base moves to it, in one
transaction. A failed re-index retires the building profile; the active one never changes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import psycopg
import structlog

from neuron_agent.config.settings import ProcessingPolicy
from neuron_agent.knowledge.chunking import estimate_tokens
from neuron_agent.knowledge.ingest import PROFILES, Connect, _vector, lock_document
from neuron_agent.knowledge.jobs import Task, defer
from neuron_agent.knowledge.providers import (
    EmbeddingError,
    EmbeddingProvider,
    ensure_processing_allowed,
    provider_for,
)
from neuron_agent.observability.audit import audit
from neuron_agent.persistence.migrations import KnowledgeProfile

log = structlog.get_logger(__name__)

_BUILDING = (
    "SELECT profile_id, provider, model, dimensions FROM knowledge.index_profiles"
    " WHERE status = 'building'"
)
_SCOPE = "SELECT set_config('neuron.kb_ids', %s, true)"
_PROCESSING = "SELECT processing FROM knowledge.bases WHERE kb_id = %s AND deleted_at IS NULL"
# A ready, live chunk without a vector under the profile; `c.kb_id` narrows it to the bases a
# caller names, and RLS to those in scope.
_UNCOVERED = (
    " FROM knowledge.chunks c JOIN knowledge.documents d USING (doc_id)"
    " JOIN knowledge.bases b ON b.kb_id = d.kb_id"
    " WHERE c.kb_id = ANY (%s) AND d.status = 'ready' AND d.deleted_at IS NULL"
    " AND b.deleted_at IS NULL AND NOT EXISTS (SELECT 1 FROM knowledge.embeddings e"
    " WHERE e.chunk_id = c.chunk_id AND e.profile_id = %s)"
)
_CHUNKS = (
    "SELECT c.chunk_id, array_to_string(c.headings || c.text, E'\\n') AS passage"
    + _UNCOVERED
    + " AND c.doc_id = %s ORDER BY c.ordinal"
)
# Still building: a cancel or a swap in between stops the job's writes.
_STILL_BUILDING = (
    "SELECT 1 FROM knowledge.index_profiles WHERE profile_id = %s AND status = 'building' FOR SHARE"
)
# Only a chunk that still exists: a re-ingestion may have replaced the set meanwhile, and wrote
# its own vectors for both profiles.
_INSERT = (
    "INSERT INTO knowledge.embeddings (chunk_id, profile_id, kb_id, embedding)"
    " SELECT chunk_id, %s, kb_id, %s FROM knowledge.chunks WHERE chunk_id = %s"
    " ON CONFLICT DO NOTHING"
)
_TOKENS = (
    "UPDATE knowledge.documents SET embedding_tokens = embedding_tokens + %s WHERE doc_id = %s"
)
_PENDING = (
    "SELECT DISTINCT (args->>'kb_id')::uuid AS kb_id FROM knowledge.procrastinate_jobs"
    " WHERE task_name = %s AND status IN ('todo', 'doing')"
)


# Retired profiles' vectors, a batch per transaction: no profile is searched or written once
# retired, so nothing races the delete. Every base is in scope (RLS), deleted ones too.
_RETIRED_BATCH = 5_000
_PURGE_RETIRED = (
    "DELETE FROM knowledge.embeddings WHERE ctid IN (SELECT e.ctid FROM knowledge.embeddings e"
    " JOIN knowledge.index_profiles p USING (profile_id) WHERE p.status = 'retired' LIMIT %s)"
)


class ReindexRefusedError(Exception):
    """The re-index cannot finish (a base's setting forbids the model): it fails, no retry."""

    def __init__(self, code: str) -> None:
        self.code = code


@dataclass(frozen=True)
class Reindexer:
    connect: Connect
    embeddings: EmbeddingProvider
    reindex: EmbeddingProvider | None
    policy: ProcessingPolicy

    async def reindex_base(self, kb_id: uuid.UUID) -> int:
        """Embed the base's uncovered chunks under the building profile, then try the swap.

        Returns the number of documents embedded; 0 when no profile is building.
        """
        async with await self.connect() as conn:
            profile = await _building(conn)
            if profile is None:
                return 0
            model = self._model(profile)
            done = 0
            while (
                doc_id := await self._next(conn, kb_id, profile["profile_id"], model)
            ) is not None:
                if not await self._embed(conn, kb_id, doc_id, profile["profile_id"], model):
                    return done  # cancelled or swapped meanwhile
                done += 1
        await self.swap()
        return done

    def _model(self, profile: dict[str, Any]) -> EmbeddingProvider:
        identity = KnowledgeProfile(profile["provider"], profile["model"], profile["dimensions"])
        model = provider_for(identity, self.embeddings, self.reindex)
        if model is None:  # the worker's settings may not have the re-index model yet
            raise EmbeddingError("knowledge_profile_mismatch", retryable=True)
        return model

    async def _next(
        self,
        conn: psycopg.AsyncConnection[dict[str, Any]],
        kb_id: uuid.UUID,
        profile_id: int,
        model: EmbeddingProvider,
    ) -> uuid.UUID | None:
        """A document of the live base with chunks to embed, checking the base's setting."""
        async with conn.transaction():
            row = await (await conn.execute(_PROCESSING, (kb_id,))).fetchone()
            if row is None:
                return None  # deleted: the purge removes it
            await conn.execute(_SCOPE, (str(kb_id),))
            cursor = await conn.execute(
                "SELECT c.doc_id" + _UNCOVERED + " LIMIT 1", ([kb_id], profile_id)
            )
            found = await cursor.fetchone()
        if found is None:
            return None
        try:
            ensure_processing_allowed(row["processing"], model.locality, self.policy)
        except EmbeddingError as exc:
            raise ReindexRefusedError(exc.code) from None
        return uuid.UUID(str(found["doc_id"]))

    async def _embed(
        self,
        conn: psycopg.AsyncConnection[dict[str, Any]],
        kb_id: uuid.UUID,
        doc_id: uuid.UUID,
        profile_id: int,
        model: EmbeddingProvider,
    ) -> bool:
        async with conn.transaction():
            await conn.execute(_SCOPE, (str(kb_id),))
            rows = await (await conn.execute(_CHUNKS, ([kb_id], profile_id, doc_id))).fetchall()
        # Outside a transaction: no connection waits on the provider.
        vectors = await model.embed_documents([row["passage"] for row in rows])
        async with conn.transaction():
            # The document first, then the profile, in ingestion's order (see `swap`).
            if not await lock_document(conn, doc_id):
                return True  # tombstoned meanwhile: the next query skips it
            if not await (await conn.execute(_STILL_BUILDING, (profile_id,))).fetchone():
                return False
            async with conn.cursor() as cursor:
                await cursor.executemany(
                    _INSERT,
                    [
                        (profile_id, _vector(vector), row["chunk_id"])
                        for row, vector in zip(rows, vectors, strict=True)
                    ],
                )
            tokens = sum(estimate_tokens(row["passage"]) for row in rows)
            await conn.execute(_TOKENS, (tokens, doc_id))
        return True

    async def swap(self) -> bool:
        """Make the building profile active if it covers every ready chunk; True if it did."""
        async with await self.connect() as conn, conn.transaction():
            if await (await conn.execute(_BUILDING)).fetchone() is None:
                return False  # nothing to swap: no lock taken
            # Every profile in use, in id order as ingestion and the job lock them (after their
            # document), so neither deadlocks with this; while held, neither can commit.
            locked = await (await conn.execute(PROFILES + " FOR UPDATE")).fetchall()
            building = [r for r in locked if r["status"] == "building"]
            if not building:
                return False  # cancelled or swapped meanwhile
            new = building[0]["profile_id"]
            # Before the bases are listed: a base created meanwhile would be neither checked
            # nor moved. Creates, renames and deletes wait for this transaction.
            await conn.execute("LOCK TABLE knowledge.bases IN SHARE MODE")
            cursor = await conn.execute(
                "SELECT kb_id FROM knowledge.bases WHERE deleted_at IS NULL"
            )
            bases = [r["kb_id"] for r in await cursor.fetchall()]
            await conn.execute(_SCOPE, (",".join(map(str, bases)),))
            cursor = await conn.execute("SELECT DISTINCT c.kb_id" + _UNCOVERED, (bases, new))
            missing = {r["kb_id"] for r in await cursor.fetchall()}
            if missing:
                pending = await conn.execute(_PENDING, (Task.REINDEX_KB.value,))
                for kb_id in missing - {r["kb_id"] for r in await pending.fetchall()}:
                    await defer(conn, Task.REINDEX_KB, kb_id=kb_id)
                log.info("knowledge.reindex.pending", profile_id=new, bases=len(missing))
                return False
            old = await conn.execute(
                "UPDATE knowledge.index_profiles SET status = 'retired' WHERE status = 'active'"
                " RETURNING profile_id"
            )
            retired = await old.fetchone()
            await conn.execute(
                "UPDATE knowledge.index_profiles SET status = 'active' WHERE profile_id = %s",
                (new,),
            )
            moved = await conn.execute(
                "UPDATE knowledge.bases SET profile_id = %s WHERE profile_id <> %s", (new, new)
            )
        log.info(
            "knowledge.reindex.swapped",
            profile_id=new,
            retired=retired["profile_id"] if retired else None,
            bases=moved.rowcount,
        )
        audit(
            "knowledge_reindex_swapped",
            outcome="allowed",
            action="knowledge:reindex",
            resource_type="knowledge_index_profile",
            resource_id=str(new),
            count=moved.rowcount,
        )
        return True

    async def purge_retired(self, batch: int = _RETIRED_BATCH) -> int:
        """Delete the vectors of retired profiles, after a swap or a failure; returns the count."""
        deleted = 0
        async with await self.connect() as conn:
            while True:
                async with conn.transaction():
                    cursor = await conn.execute("SELECT kb_id FROM knowledge.bases")
                    bases = ",".join(str(r["kb_id"]) for r in await cursor.fetchall())
                    await conn.execute(_SCOPE, (bases,))
                    removed = (await conn.execute(_PURGE_RETIRED, (batch,))).rowcount
                deleted += removed
                if removed < batch:
                    return deleted

    async def fail(self, code: str) -> None:
        """Retire the building profile; the active one stays (a failed or refused job)."""
        async with await self.connect() as conn, conn.transaction():
            cursor = await conn.execute(
                "UPDATE knowledge.index_profiles SET status = 'retired'"
                " WHERE status = 'building' RETURNING profile_id"
            )
            row = await cursor.fetchone()
        if row is None:
            return
        log.warning("knowledge.reindex.failed", profile_id=row["profile_id"], error_code=code)
        audit(
            "knowledge_reindex_failed",
            outcome="error",
            action="knowledge:reindex",
            resource_type="knowledge_index_profile",
            resource_id=str(row["profile_id"]),
            reason=code,
        )


async def _building(conn: psycopg.AsyncConnection[dict[str, Any]]) -> dict[str, Any] | None:
    async with conn.transaction():
        return await (await conn.execute(_BUILDING)).fetchone()
