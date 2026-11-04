# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The knowledge bases a caller may read and write (ADR 0014 K5; RAG-03.01).

Phase 1 bases are owner-only: the owner's `admin` grant, written with the base, is its only grant
row. Role grants (Phase 2) add rows that this query will read; callers keep asking `allowed_kbs`
and never trust a KB id they were given until it is in the answer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import psycopg

from neuron_agent.security.authorization import AuthorizationContext

_ALLOWED = (
    "SELECT g.kb_id, g.access FROM knowledge.grants g JOIN knowledge.bases b USING (kb_id)"
    " WHERE g.subject_type = 'owner' AND g.subject = %(owner)s AND b.owner_key = %(owner)s"
    " AND b.deleted_at IS NULL"
)
_WRITE = frozenset({"write", "admin"})


@dataclass(frozen=True)
class AllowedKbs:
    read: frozenset[uuid.UUID]
    write: frozenset[uuid.UUID]


class KnowledgeAuthorization:
    @staticmethod
    async def allowed_kbs(
        conn: psycopg.AsyncConnection[Any], ctx: AuthorizationContext
    ) -> AllowedKbs:
        """The live bases `ctx`'s owner key may read, and those it may write. None without one."""
        if ctx.owner_key is None:
            return AllowedKbs(frozenset(), frozenset())
        cursor = await conn.execute(_ALLOWED, {"owner": ctx.owner_key})
        rows = [(row["kb_id"], row["access"]) for row in await cursor.fetchall()]
        return AllowedKbs(
            read=frozenset(kb for kb, _ in rows),
            write=frozenset(kb for kb, access in rows if access in _WRITE),
        )
