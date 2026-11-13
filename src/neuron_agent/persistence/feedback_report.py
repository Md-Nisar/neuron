# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The negative feedback report: chunks cited by thumbs-down answers (RAG-09.07).

Joins `neuron_feedback` to each run's citation set. The set is not a table: the graph stamps
it on the run's answer in the thread's checkpoint (RAG-05.02), so the join reads the
negative ratings, then each thread's latest checkpoint, and keeps the answer carrying the
rated run ID. The report holds IDs, the fixed reason and the rating time only, never the
query, the answer or any chunk text; a maintainer reads a chunk through the chunk route,
which checks access. Nothing reaches logs or telemetry. Operator-only:
`python -m neuron_agent.persistence.cli feedback-report`.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage
from pydantic import ValidationError

from neuron_agent.persistence.checkpointer import Persistence
from neuron_agent.schemas.agent import Citation

_NEGATIVE = (
    "SELECT thread_id, run_id, reason, created_at FROM neuron_feedback "
    "WHERE score = -1 ORDER BY created_at, run_id"
)


def cited_chunks(messages: Any, run_id: str) -> list[dict[str, str]] | None:
    """The chunk and document IDs the run's answer cited; None if no answer carries the run.

    A citation that does not validate is skipped, as thread history drops it.
    """
    if not isinstance(messages, list):
        return None
    for message in messages:
        if isinstance(message, AIMessage) and message.additional_kwargs.get("run_id") == run_id:
            chunks = []
            for raw in message.additional_kwargs.get("citations") or []:
                try:
                    citation = Citation.model_validate(raw)
                except ValidationError:
                    continue
                chunks.append({"chunk_id": str(citation.chunk_id), "doc_id": str(citation.doc_id)})
            return chunks
    return None


async def negative_feedback_report(persistence: Persistence) -> dict[str, Any]:
    """Every thumbs-down run whose answer cited knowledge, with the cited chunk IDs."""
    if persistence.pool is None or persistence.checkpointer is None:
        raise RuntimeError("the feedback report needs the Postgres checkpointer")
    async with persistence.pool.connection() as conn:
        rows = await (await conn.execute(_NEGATIVE)).fetchall()
    runs, missing = [], 0
    for row in rows:
        latest = await persistence.checkpointer.aget_tuple(
            {"configurable": {"thread_id": row["thread_id"], "checkpoint_ns": ""}}
        )
        messages = latest.checkpoint["channel_values"].get("messages") if latest else None
        chunks = cited_chunks(messages, row["run_id"])
        if chunks is None:
            missing += 1
        elif chunks:
            runs.append(
                {
                    "run_id": row["run_id"],
                    "thread_id": row["thread_id"],
                    "reason": row["reason"],
                    "rated_at": row["created_at"].isoformat(),
                    "chunks": chunks,
                }
            )
    return {"negative_runs": len(rows), "answer_missing": missing, "cited_runs": runs}
