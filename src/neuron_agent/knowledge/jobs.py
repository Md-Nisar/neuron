# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The knowledge job queue (ADR 0014 K4; RAG-02.01).

Jobs are Procrastinate's, in its tables in the `knowledge` schema (migration 25). They carry ids
only, never document text, file names or a raw identity, and the document row stays the public
status: there is no job resource. `defer` queues a job on the caller's connection, inside the
caller's transaction, so the job exists exactly when the row it is about was committed (outbox).
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

import psycopg
from psycopg import pq
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

# The one queue the worker listens on.
QUEUE = "knowledge"


class Task(StrEnum):
    """Task names the worker registers."""

    INGEST_DOCUMENT = "ingest_document"
    PURGE_DOCUMENT = "purge_document"
    PURGE_KNOWLEDGE_BASE = "purge_knowledge_base"
    # Periodic, queued by the worker itself (RAG-07.02); it carries only Procrastinate's timestamp.
    RECONCILE = "reconcile_knowledge"


# Procrastinate's `procrastinate_job_to_defer_v1`: queue, task, priority, lock, queueing lock,
# arguments, scheduled time.
_DEFER = (
    "SELECT knowledge.procrastinate_defer_jobs_v1(ARRAY[ROW(%s, %s, 0, NULL, NULL, %s, NULL)"
    "::knowledge.procrastinate_job_to_defer_v1])"
)


async def defer(conn: psycopg.AsyncConnection[Any], task: Task, **ids: uuid.UUID) -> int:
    """Queue `task` with `ids` as its arguments and return the job id.

    Refuses anything but UUID arguments, and a connection that is not inside a transaction: the
    caller writes the row the job is about and defers the job in that same transaction.
    """
    if not all(isinstance(value, uuid.UUID) for value in ids.values()):
        raise TypeError("job arguments are ids only")
    if conn.info.transaction_status != pq.TransactionStatus.INTRANS:
        raise ValueError("defer runs inside the transaction that writes the job's row")
    async with conn.cursor(row_factory=tuple_row) as cursor:
        await cursor.execute(
            _DEFER, (QUEUE, task.value, Jsonb({name: str(value) for name, value in ids.items()}))
        )
        row = await cursor.fetchone()
    assert row is not None  # nosec B101
    return int(row[0][0])
