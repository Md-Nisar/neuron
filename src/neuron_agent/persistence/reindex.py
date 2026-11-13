# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The operator's re-index command (ADR 0014 amendment "re-index to a new profile", RAG-09.04).

`start` records the next index profile as `building`, builds its HNSW index concurrently and
queues one `reindex_kb` job per live base; the worker embeds, then swaps (`knowledge/reindex.py`).
It runs as the migration role, holding `setup`'s advisory lock, and refuses a target model that
a live base's processing setting or the policy forbids: that base would lose meaning search
after the swap. `status` reports progress; `cancel` retires the building profile, and the
active one never changes. No API: re-indexing is an operator task.

The queue is reached through Procrastinate's SQL function, as `knowledge/jobs.py` does, since
`persistence/` does not import `knowledge/`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import psycopg
from psycopg.rows import dict_row

from neuron_agent.observability.audit import audit
from neuron_agent.persistence.migrations import (
    CHUNKER,
    CONCURRENT_LOCK_TIMEOUT_MS,
    DEFAULT_LOCK_TIMEOUT_MS,
    LOCK_WAIT_SECONDS,
    KnowledgeProfile,
    _acquire_lock,
    _build_hnsw,
    _set_lock_timeout,
)

_TASK = "reindex_kb"
# One job per live base without a queued or running one, in one statement.
_DEFER = (
    "SELECT knowledge.procrastinate_defer_jobs_v1(array_agg(ROW('knowledge', %s, 0, NULL, NULL,"
    " jsonb_build_object('kb_id', b.kb_id::text), NULL)::knowledge.procrastinate_job_to_defer_v1))"
    " FROM knowledge.bases b WHERE b.deleted_at IS NULL AND NOT EXISTS ("
    " SELECT 1 FROM knowledge.procrastinate_jobs j WHERE j.task_name = %s"
    " AND j.status IN ('todo', 'doing') AND j.args->>'kb_id' = b.kb_id::text)"
    " HAVING count(*) > 0"
)
_STATUS = """
SELECT
    (SELECT count(*) FROM knowledge.bases WHERE deleted_at IS NULL) AS bases,
    (SELECT count(*) FROM knowledge.chunks c JOIN knowledge.documents d USING (doc_id)
        JOIN knowledge.bases b ON b.kb_id = d.kb_id
        WHERE d.status = 'ready' AND d.deleted_at IS NULL AND b.deleted_at IS NULL) AS chunks,
    (SELECT count(*) FROM knowledge.embeddings e JOIN knowledge.chunks c USING (chunk_id)
        JOIN knowledge.documents d USING (doc_id) JOIN knowledge.bases b ON b.kb_id = d.kb_id
        WHERE e.profile_id = %(id)s AND d.status = 'ready' AND d.deleted_at IS NULL
        AND b.deleted_at IS NULL) AS covered,
    (SELECT count(*) FROM knowledge.procrastinate_jobs
        WHERE task_name = %(task)s AND status IN ('todo', 'doing')) AS jobs
"""


class ReindexError(Exception):
    """A refusal whose message is fixed text, safe to print."""


@dataclass(frozen=True)
class Progress:
    profile_id: int | None  # the building profile, if any
    active: int | None
    bases: int = 0
    chunks: int = 0
    covered: int = 0
    jobs: int = 0


async def start(
    dsn: str,
    target: KnowledgeProfile,
    locality: Literal["hosted", "self_hosted"],
    policy: str,
    *,
    lock_wait_seconds: float = LOCK_WAIT_SECONDS,
) -> int:
    """Begin a re-index into `target`; returns the new profile's id.

    A `start` that stopped after recording the profile (its index build timed out, say) is
    resumed by running `start` again with the same model: the index is built and the bases
    without a job get one.
    """
    async with await _connect(dsn) as conn:
        await _acquire_lock(conn, lock_wait_seconds)  # not during a `setup`
        await _set_lock_timeout(conn, DEFAULT_LOCK_TIMEOUT_MS)
        async with conn.transaction():
            rows = await _profiles(conn)
            building = [row for row in rows if row["status"] == "building"]
            if building and _identity(building[0]) != target:
                raise ReindexError("a re-index to another model is running: see `reindex status`")
            active = [row for row in rows if row["status"] == "active"]
            if not active:
                raise ReindexError("no active index profile: run `setup` first")
            if _identity(active[0]) == target:
                raise ReindexError("the re-index model is the active model already")
            if locality == "hosted":
                await _refuse_hosted(conn, policy)
            if building:
                new = int(building[0]["profile_id"])
            else:
                new = max(int(row["profile_id"]) for row in rows) + 1
                await conn.execute(
                    "INSERT INTO knowledge.index_profiles"
                    " (profile_id, provider, model, dimensions, chunker, status)"
                    " VALUES (%s, %s, %s, %s, %s, 'building')",
                    (new, target.provider, target.model, target.dimensions, CHUNKER),
                )
        await _set_lock_timeout(conn, CONCURRENT_LOCK_TIMEOUT_MS)
        await _build_hnsw(conn, new, target.dimensions)
        async with conn.transaction():
            await conn.execute(_DEFER, (_TASK, _TASK))
        bases = await _count(conn, "SELECT count(*) FROM knowledge.bases WHERE deleted_at IS NULL")
    audit(
        "knowledge_reindex_started",
        outcome="allowed",
        action="knowledge:reindex",
        resource_type="knowledge_index_profile",
        resource_id=str(new),
        count=bases,
    )
    return new


async def status(dsn: str) -> Progress:
    async with await _connect(dsn) as conn:
        rows = await _profiles(conn)
        active = next((int(r["profile_id"]) for r in rows if r["status"] == "active"), None)
        building = next((int(r["profile_id"]) for r in rows if r["status"] == "building"), None)
        if building is None:
            return Progress(None, active)
        cursor = await conn.execute(_STATUS, {"id": building, "task": _TASK})
        counts = await cursor.fetchone()
    assert counts is not None  # nosec B101 - one row
    return Progress(building, active, **{k: int(v) for k, v in counts.items()})


async def cancel(dsn: str) -> int | None:
    """Retire the building profile; returns its id, or None when none was building."""
    async with await _connect(dsn) as conn:
        await _acquire_lock(conn, LOCK_WAIT_SECONDS)  # not while a `start` builds its index
        async with conn.transaction():
            cursor = await conn.execute(
                "UPDATE knowledge.index_profiles SET status = 'retired'"
                " WHERE status = 'building' RETURNING profile_id"
            )
            row = await cursor.fetchone()
    if row is None:
        return None
    audit(
        "knowledge_reindex_failed",
        outcome="allowed",  # the operator's choice, not an error
        action="knowledge:reindex",
        resource_type="knowledge_index_profile",
        resource_id=str(row["profile_id"]),
        reason="cancelled",
    )
    return int(row["profile_id"])


async def _refuse_hosted(conn: psycopg.AsyncConnection[dict[str, Any]], policy: str) -> None:
    """A hosted model may embed only `hosted` bases, and only under `allow_hosted` (K8)."""
    if policy != "allow_hosted":
        raise ReindexError("the processing policy forbids a hosted re-index model")
    forbidden = await _count(
        conn,
        "SELECT count(*) FROM knowledge.bases WHERE deleted_at IS NULL"
        " AND processing = 'self_hosted'",
    )
    if forbidden:
        raise ReindexError(
            f"{forbidden} knowledge base(s) are self-hosted only: the re-index model must be"
            " self-hosted"
        )


async def _connect(dsn: str) -> psycopg.AsyncConnection[dict[str, Any]]:
    return await psycopg.AsyncConnection.connect(
        dsn, autocommit=True, row_factory=dict_row, prepare_threshold=None
    )


async def _profiles(conn: psycopg.AsyncConnection[dict[str, Any]]) -> list[dict[str, Any]]:
    cursor = await conn.execute(
        "SELECT profile_id, provider, model, dimensions, status FROM knowledge.index_profiles"
        " ORDER BY profile_id"
    )
    return await cursor.fetchall()


async def _count(conn: psycopg.AsyncConnection[dict[str, Any]], query: str) -> int:
    row = await (await conn.execute(query)).fetchone()
    return int(row["count"]) if row else 0


def _identity(row: dict[str, Any]) -> KnowledgeProfile:
    return KnowledgeProfile(str(row["provider"]), str(row["model"]), int(row["dimensions"]))
