# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The periodic reconcile task: rows and jobs that drifted apart (RAG-07.02).

The worker's stalled-job sweep retries a job whose worker died. This task handles what that
sweep cannot see, rows left without a live (`todo` or `doing`) job:

- a document in `queued`, `parsing` or `embedding` past the timeout, for example after
  recording `ingest_failed` itself failed. It is queued again up to `STUCK_REQUEUES` times,
  then set `failed` with `ingest_stalled`;
- a tombstoned document or base past the timeout whose purge used all its attempts. Its purge
  is queued again; the purge only removes tombstoned rows (RAG-03.03).

A row that still has a live job is never touched, so this task and the sweep never retry the
same work. One run at a time, under an advisory lock, in one transaction: each job is queued
in the transaction that reads its row (`jobs.defer`).
"""

from __future__ import annotations

from typing import Any

import psycopg

from neuron_agent.knowledge import jobs
from neuron_agent.knowledge.ingest import Connect

# Jobs queued for a stuck document after its first; then it fails with `ingest_stalled`. Counted
# from the queue's rows, which are never deleted (a job retention policy would reset the count).
STUCK_REQUEUES = 2
# Rows handled per kind and run, so one run stays short; the next run takes the rest.
BATCH = 500
# The advisory lock key that serialises reconcile runs.
_LOCK = 0x4E52_5243


def _jobs(task: jobs.Task, arg: str, column: str, *, live: bool) -> str:
    """Jobs of `task` whose `arg` is the row's `column`; only unfinished ones when `live`.

    Builds SQL from its arguments: call it with constants only, never with user data.
    """
    status = " AND j.status IN ('todo', 'doing', 'aborting')" if live else ""
    return (
        f"knowledge.procrastinate_jobs j WHERE j.task_name = '{task.value}'"  # noqa: S608
        f" AND j.args->>'{arg}' = {column}::text{status}"
    )


_INGEST = jobs.Task.INGEST_DOCUMENT
_STUCK = f"""
SELECT d.doc_id, (SELECT count(*) FROM {_jobs(_INGEST, "doc_id", "d.doc_id", live=False)}) AS runs
FROM knowledge.documents d JOIN knowledge.bases b USING (kb_id)
WHERE d.deleted_at IS NULL AND b.deleted_at IS NULL
    AND d.status IN ('queued', 'parsing', 'embedding')
    AND d.updated_at < now() - make_interval(secs => %(seconds)s)
    AND NOT EXISTS (SELECT 1 FROM {_jobs(_INGEST, "doc_id", "d.doc_id", live=True)})
ORDER BY d.updated_at LIMIT {BATCH}
FOR UPDATE OF d
"""  # noqa: S608  # nosec B608 - constants only
_REQUEUE = (
    "UPDATE knowledge.documents SET status = 'queued', error_code = NULL, updated_at = now()"
    " WHERE doc_id = %s AND deleted_at IS NULL AND status IN ('queued', 'parsing', 'embedding')"
)
_STALLED = (
    "UPDATE knowledge.documents SET status = 'failed', error_code = 'ingest_stalled',"
    " updated_at = now() WHERE doc_id = %s AND deleted_at IS NULL"
    " AND status IN ('queued', 'parsing', 'embedding')"
)
_BASES = f"""
SELECT b.kb_id AS id FROM knowledge.bases b
WHERE b.deleted_at < now() - make_interval(secs => %(seconds)s)
    AND NOT EXISTS (
        SELECT 1 FROM {_jobs(jobs.Task.PURGE_KNOWLEDGE_BASE, "kb_id", "b.kb_id", live=True)})
ORDER BY b.deleted_at LIMIT {BATCH}
"""  # noqa: S608  # nosec B608 - constants only
# A document of a deleted base goes with its base's purge.
_DOCUMENTS = f"""
SELECT d.doc_id AS id FROM knowledge.documents d JOIN knowledge.bases b USING (kb_id)
WHERE d.deleted_at < now() - make_interval(secs => %(seconds)s) AND b.deleted_at IS NULL
    AND NOT EXISTS (
        SELECT 1 FROM {_jobs(jobs.Task.PURGE_DOCUMENT, "doc_id", "d.doc_id", live=True)})
ORDER BY d.deleted_at LIMIT {BATCH}
"""  # noqa: S608  # nosec B608 - constants only


async def reconcile(connect: Connect, stuck_seconds: float) -> dict[str, int]:
    """Run once and return how many rows each action took; empty if another run holds the lock.

    Actions: `ingest_requeued`, `ingest_stalled` and `purge_requeued`.
    """
    counts = {"ingest_requeued": 0, "ingest_stalled": 0, "purge_requeued": 0}
    async with await connect() as conn, conn.transaction():
        cursor = await conn.execute("SELECT pg_try_advisory_xact_lock(%s) AS locked", (_LOCK,))
        if not (row := await cursor.fetchone()) or not row["locked"]:
            return {}
        arguments = {"seconds": stuck_seconds}
        for document in await _fetch(conn, _STUCK, arguments):
            doc_id = document["doc_id"]
            if document["runs"] > STUCK_REQUEUES:
                await conn.execute(_STALLED, (doc_id,))
                counts["ingest_stalled"] += 1
            else:
                await conn.execute(_REQUEUE, (doc_id,))
                await jobs.defer(conn, _INGEST, doc_id=doc_id)
                counts["ingest_requeued"] += 1
        for query, task, name in (
            (_BASES, jobs.Task.PURGE_KNOWLEDGE_BASE, "kb_id"),
            (_DOCUMENTS, jobs.Task.PURGE_DOCUMENT, "doc_id"),
        ):
            for tombstone in await _fetch(conn, query, arguments):
                await jobs.defer(conn, task, **{name: tombstone["id"]})
                counts["purge_requeued"] += 1
    return counts


async def _fetch(
    conn: psycopg.AsyncConnection[dict[str, Any]], query: str, arguments: dict[str, Any]
) -> list[dict[str, Any]]:
    cursor = await conn.execute(query, arguments)
    return await cursor.fetchall()
