# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""The knowledge bases a caller may read, write and administer (ADR 0014 K5; RAG-03.01, RAG-09.03).

A base's owner holds an `admin` grant, written with the base. Role grants (RAG-09.03) give the
holders of a verified token role `read`, `write` or `admin` access. Callers ask `allowed_kbs` in
the same transaction as the statement it guards, and never trust a KB id they were given until it
is in the answer, so a revoked grant counts from the next request. Nothing is cached.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import psycopg

# An owner grant counts only on a base that owner owns; a role grant on any live base.
_ALLOWED = (
    "SELECT g.kb_id, g.access, g.subject_type FROM knowledge.grants g"
    " JOIN knowledge.bases b USING (kb_id) WHERE b.deleted_at IS NULL AND ("
    "(g.subject_type = 'owner' AND g.subject = %(owner)s AND b.owner_key = %(owner)s)"
    " OR (g.subject_type = 'role' AND g.subject = ANY(%(roles)s::text[])))"
)
_WRITE = frozenset({"write", "admin"})


@dataclass(frozen=True)
class AllowedKbs:
    read: frozenset[uuid.UUID]
    write: frozenset[uuid.UUID]
    admin: frozenset[uuid.UUID] = frozenset()
    # The caller's own bases (the owner grant); only these may be deleted, exported or erased.
    owned: frozenset[uuid.UUID] = frozenset()


class KnowledgeAuthorization:
    @staticmethod
    async def allowed_kbs(
        conn: psycopg.AsyncConnection[Any],
        owner_key: str | None,
        roles: frozenset[str] = frozenset(),
    ) -> AllowedKbs:
        """The live bases the caller may read, write and administer. None without an owner key:
        roles alone never grant access."""
        if owner_key is None:
            return AllowedKbs(frozenset(), frozenset())
        cursor = await conn.execute(_ALLOWED, {"owner": owner_key, "roles": sorted(roles)})
        rows = [
            (row["kb_id"], row["access"], row["subject_type"]) for row in await cursor.fetchall()
        ]
        return AllowedKbs(
            read=frozenset(kb for kb, _, _ in rows),
            write=frozenset(kb for kb, access, _ in rows if access in _WRITE),
            admin=frozenset(kb for kb, access, _ in rows if access == "admin"),
            owned=frozenset(kb for kb, _, subject in rows if subject == "owner"),
        )
