# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Search over the caller's knowledge bases (ADR 0014 K6; RAG-04.01).

Authorisation comes before ranking, in SQL: the search transaction finds the caller's readable
bases (`allowed_kbs`), sets `neuron.kb_ids` to them with `SET LOCAL` (row-level security repeats
the filter), and every candidate query filters on those bases, the base's owner and a live,
`ready` document. Full-text candidates (`websearch_to_tsquery` in each base's text-search config)
are ranked and fused with reciprocal rank fusion; dense candidates join them in part 2.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

import psycopg
import structlog
from psycopg_pool import AsyncConnectionPool

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import KnowledgeDisabledError, PersistenceError
from neuron_agent.knowledge.authorization import KnowledgeAuthorization
from neuron_agent.observability.audit import audit
from neuron_agent.security.authorization import AuthorizationContext

log = structlog.get_logger(__name__)

CANDIDATES = 80
MAX_K = 50
MAX_QUERY_CHARS = 2_000
RRF_K = 60

# The readable bases with their text-search config.
_BASES = (
    "SELECT b.kb_id, b.ts_config::text AS ts_config FROM knowledge.bases b"
    " WHERE b.kb_id = ANY(%(kbs)s) AND b.owner_key = %(owner)s AND b.deleted_at IS NULL"
)
_SCOPE = "SELECT set_config('neuron.kb_ids', %s, true)"
# A chunk counts only through a live, ready document of a live base of the caller's.
_LIVE = (
    " JOIN knowledge.documents d ON d.doc_id = c.doc_id AND d.kb_id = c.kb_id"
    " JOIN knowledge.bases b ON b.kb_id = d.kb_id"
    " WHERE b.owner_key = %(owner)s AND b.deleted_at IS NULL"
    " AND d.deleted_at IS NULL AND d.status = 'ready'"
)
_CHUNKS = " FROM knowledge.chunks c"
_FTS = (
    "SELECT c.chunk_id"
    + _CHUNKS
    + _LIVE
    + " AND c.kb_id = ANY(%(kbs)s) AND c.tsv @@ websearch_to_tsquery(%(cfg)s::regconfig, %(q)s)"
    " ORDER BY ts_rank_cd(c.tsv, websearch_to_tsquery(%(cfg)s::regconfig, %(q)s)) DESC,"
    " c.chunk_id LIMIT %(n)s"
)
_PASSAGES = (
    "SELECT c.chunk_id, c.doc_id, c.kb_id, d.title, c.ordinal, c.text, c.headings,"
    " c.page_start, c.page_end"
    + _CHUNKS
    + _LIVE
    + " AND c.kb_id = ANY(%(kbs)s) AND c.chunk_id = ANY(%(ids)s)"
)


@dataclass(frozen=True)
class Passage:
    chunk_id: uuid.UUID
    doc_id: uuid.UUID
    kb_id: uuid.UUID
    title: str
    ordinal: int
    text: str
    headings: list[str]
    page_start: int | None
    page_end: int | None
    score: float


@dataclass(frozen=True)
class SearchResult:
    passages: list[Passage]

    @property
    def status(self) -> Literal["ok", "no_relevant_results"]:
        return "ok" if self.passages else "no_relevant_results"


def fuse(rankings: Sequence[Sequence[uuid.UUID]], k: int = RRF_K) -> list[tuple[uuid.UUID, float]]:
    """Reciprocal rank fusion: each list adds 1 / (k + rank) to its items (rank from 1)."""
    scores: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], str(pair[0])))


class Retriever:
    def __init__(
        self,
        settings: Settings,
        pool: Callable[[], AsyncConnectionPool[Any] | None],
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
            log.warning("knowledge_search_failed", error_type=type(exc).__name__)
            raise PersistenceError("knowledge search failed") from exc

    async def search(self, owner_key: str, query: str, *, k: int) -> SearchResult:
        """The `k` best passages for `query` in the caller's readable bases.

        Callers validate input first; out-of-range values are a programming error here.
        """
        if not 1 <= k <= MAX_K or not query.strip() or len(query) > MAX_QUERY_CHARS:
            raise ValueError("search needs 1 <= k <= 50 and a query of 1 to 2,000 characters")
        async with self._transaction() as conn:
            bases = await self._bases(conn, owner_key)
            await conn.execute(_SCOPE, (",".join(str(row["kb_id"]) for row in bases),))
            fused = fuse(await self._fts(conn, owner_key, bases, query))[:k]
            passages = await self._passages(conn, owner_key, bases, fused)
        audit(
            "knowledge_searched",
            outcome="allowed",
            actor=owner_key[:12] if self._settings.auth_mode == "jwt" else None,
            issuer_id=self._settings.auth_issuer_id,
            action="knowledge:read",
            resource_type="knowledge_base",
            count=len(passages),
        )
        return SearchResult(passages)

    @staticmethod
    async def _bases(conn: psycopg.AsyncConnection[Any], owner_key: str) -> list[dict[str, Any]]:
        allowed = await KnowledgeAuthorization.allowed_kbs(
            conn, AuthorizationContext(frozenset(), owner_key=owner_key)
        )
        cursor = await conn.execute(_BASES, {"kbs": [*allowed.read], "owner": owner_key})
        return list(await cursor.fetchall())

    @staticmethod
    async def _fts(
        conn: psycopg.AsyncConnection[Any],
        owner_key: str,
        bases: Sequence[dict[str, Any]],
        query: str,
    ) -> list[list[uuid.UUID]]:
        """One ranking per text-search config among the bases (`simple` unless set). A base's
        config is fixed when it is created, so its chunks' `tsv` were built with the same one."""
        by_config: dict[str, list[uuid.UUID]] = {}
        for row in bases:
            by_config.setdefault(row["ts_config"], []).append(row["kb_id"])
        rankings: list[list[uuid.UUID]] = []
        for config, kbs in sorted(by_config.items()):
            cursor = await conn.execute(
                _FTS, {"owner": owner_key, "kbs": kbs, "cfg": config, "q": query, "n": CANDIDATES}
            )
            rankings.append([row["chunk_id"] for row in await cursor.fetchall()])
        return rankings

    @staticmethod
    async def _passages(
        conn: psycopg.AsyncConnection[Any],
        owner_key: str,
        bases: Sequence[dict[str, Any]],
        fused: list[tuple[uuid.UUID, float]],
    ) -> list[Passage]:
        if not fused:
            return []
        cursor = await conn.execute(
            _PASSAGES,
            {
                "owner": owner_key,
                "kbs": [row["kb_id"] for row in bases],
                "ids": [chunk_id for chunk_id, _ in fused],
            },
        )
        rows = {row["chunk_id"]: row for row in await cursor.fetchall()}
        return [
            Passage(**rows[chunk_id], score=score) for chunk_id, score in fused if chunk_id in rows
        ]
