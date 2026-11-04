# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Hybrid search over the caller's knowledge bases (ADR 0014 K6; RAG-04.01).

Authorisation comes before ranking, in SQL: the search transaction finds the caller's readable
bases (`allowed_kbs`), sets `neuron.kb_ids` to them with `SET LOCAL` (row-level security repeats
the filter), and every candidate query filters on those bases, the base's owner and a live,
`ready` document. Dense candidates (cosine, the active index profile only) and full-text
candidates (`websearch_to_tsquery` in each base's text-search config) are fused with reciprocal
rank fusion.

The dense path is chosen in code, never by the planner (RAG-00.02): an exact scan when the
allowed set has at most `knowledge_exact_scan_max_chunks` embeddings, which always returns every
row it can, and HNSW with `relaxed_order` iterative scan above it. The exact query orders by the
uncast column, which the HNSW index (on `embedding::halfvec(d)`) cannot serve; the HNSW query
orders by the indexed expression with bitmap scans and sorts priced out.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Collection, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

import psycopg
import structlog
from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import KnowledgeDisabledError, PersistenceError
from neuron_agent.knowledge.authorization import KnowledgeAuthorization
from neuron_agent.knowledge.providers import (
    EmbeddingError,
    EmbeddingProvider,
    ensure_processing_allowed,
)
from neuron_agent.observability.audit import audit
from neuron_agent.persistence.migrations import KNOWLEDGE_PROFILE_ID
from neuron_agent.security.authorization import AuthorizationContext

log = structlog.get_logger(__name__)

SearchMode = Literal["hybrid", "dense", "fts"]
CANDIDATES = 80
MAX_K = 50
MAX_QUERY_CHARS = 2_000
RRF_K = 60

# The readable bases, and whether each may be searched by meaning: its index profile must be the
# active one this process embeds queries for.
_BASES = (
    "SELECT b.kb_id, b.processing, b.ts_config::text AS ts_config,"
    " b.profile_id = %(profile)s AND p.status = 'active' AS dense"
    " FROM knowledge.bases b JOIN knowledge.index_profiles p ON p.profile_id = b.profile_id"
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
# Counted only up to the threshold: the answer is "at most" or "more".
_ALLOWED_VECTORS = (
    "SELECT count(*) AS n FROM (SELECT 1 FROM knowledge.embeddings"
    " WHERE profile_id = %(profile)s AND kb_id = ANY(%(kbs)s) LIMIT %(limit)s) s"
)
_EMBEDDINGS = " FROM knowledge.embeddings e"
_EXACT = (
    "SELECT c.chunk_id, 1 - (e.embedding <=> %(v)s::halfvec) AS similarity"
    + _EMBEDDINGS
    + " JOIN knowledge.chunks c ON c.chunk_id = e.chunk_id AND c.kb_id = e.kb_id"
    + _LIVE
    + " AND e.profile_id = %(profile)s AND e.kb_id = ANY(%(kbs)s)"
    " ORDER BY e.embedding <=> %(v)s::halfvec, c.chunk_id LIMIT %(n)s"
)
# The top candidates are taken before the live-document join, so a document not yet purged can
# take a slot (recall only: the join drops it). The dimension is a type modifier and the profile
# must match the partial index's predicate even in a generic plan, so both are literals (from
# settings and a constant, never user input).
_NEAREST = " FROM (SELECT e.chunk_id, e.kb_id,"
_ANN = sql.SQL(
    "SELECT c.chunk_id, 1 - a.distance AS similarity"
    + _NEAREST
    + " e.embedding::halfvec({dims}) <=> %(v)s::halfvec({dims}) AS distance"
    + _EMBEDDINGS
    + " WHERE e.profile_id = {profile} AND e.kb_id = ANY(%(kbs)s)"
    " ORDER BY e.embedding::halfvec({dims}) <=> %(v)s::halfvec({dims}) LIMIT %(n)s) a"
    " JOIN knowledge.chunks c ON c.chunk_id = a.chunk_id AND c.kb_id = a.kb_id"
    + _LIVE
    + " ORDER BY a.distance, c.chunk_id"
)
_ANN_SETTINGS = (
    "SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true),"
    " set_config('hnsw.ef_search', '100', true),"
    " set_config('enable_bitmapscan', 'off', true), set_config('enable_sort', 'off', true)"
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
    # `exact` or `hnsw` for the dense path taken, `none` when it did not run.
    path: Literal["exact", "hnsw", "none"]

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
        embeddings: EmbeddingProvider,
    ) -> None:
        self._settings = settings
        self._pool = pool
        self._embeddings = embeddings

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

    async def search(
        self,
        owner_key: str,
        query: str,
        *,
        k: int,
        kb_ids: Collection[uuid.UUID] | None = None,
        mode: SearchMode | None = None,
    ) -> SearchResult:
        """The `k` best passages for `query` in the caller's readable bases, or only those of
        them in `kb_ids`: any other id there is ignored, as an unknown one is.

        Callers validate input first; out-of-range values are a programming error here.
        """
        if not 1 <= k <= MAX_K or not query.strip() or len(query) > MAX_QUERY_CHARS:
            raise ValueError("search needs 1 <= k <= 50 and a query of 1 to 2,000 characters")
        mode = mode or self._settings.knowledge_search_mode
        vector: str | None = None
        if mode != "fts":
            # The query is embedded before the search transaction, so no connection is held
            # during the provider call; the bases are read again inside it.
            async with self._transaction() as conn:
                bases = await self._bases(conn, owner_key, kb_ids)
            if self._dense_bases(bases):
                try:
                    values = await self._embeddings.embed_query(query)
                except EmbeddingError as exc:
                    if mode == "dense":
                        raise
                    # Hybrid degrades to full text while the provider is down.
                    log.warning("knowledge_search_dense_skipped", error_code=exc.code)
                else:
                    vector = "[" + ",".join(repr(float(value)) for value in values) + "]"
        async with self._transaction() as conn:
            bases = await self._bases(conn, owner_key, kb_ids)
            await conn.execute(_SCOPE, (",".join(str(row["kb_id"]) for row in bases),))
            rankings: list[list[uuid.UUID]] = []
            path: Literal["exact", "hnsw", "none"] = "none"
            # Full text first: the HNSW path's planner settings would price out its GIN scan.
            if mode != "dense":
                rankings.extend(await self._fts(conn, owner_key, bases, query))
            if vector is not None and (dense := self._dense_bases(bases)):
                path, ranked = await self._dense(conn, owner_key, dense, vector)
                rankings.insert(0, ranked)
            fused = fuse(rankings)[:k]
            # Primary-key lookups, which those settings leave alone.
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
        return SearchResult(passages, path)

    @staticmethod
    async def _bases(
        conn: psycopg.AsyncConnection[Any],
        owner_key: str,
        kb_ids: Collection[uuid.UUID] | None,
    ) -> list[dict[str, Any]]:
        allowed = await KnowledgeAuthorization.allowed_kbs(
            conn, AuthorizationContext(frozenset(), owner_key=owner_key)
        )
        kbs = allowed.read if kb_ids is None else allowed.read & set(kb_ids)
        cursor = await conn.execute(
            _BASES, {"kbs": [*kbs], "owner": owner_key, "profile": KNOWLEDGE_PROFILE_ID}
        )
        return list(await cursor.fetchall())

    def _dense_bases(self, bases: Sequence[dict[str, Any]]) -> list[uuid.UUID]:
        """Bases searched by meaning: on the active profile, and whose processing setting and
        the operator's policy allow the query to go to this embedding provider."""
        allowed = []
        for row in bases:
            if not row["dense"]:
                continue
            try:
                ensure_processing_allowed(
                    row["processing"],
                    self._embeddings.locality,
                    self._settings.knowledge_processing_policy,
                )
            except EmbeddingError:
                continue  # searched by text only
            allowed.append(row["kb_id"])
        return allowed

    async def _dense(
        self,
        conn: psycopg.AsyncConnection[Any],
        owner_key: str,
        kbs: list[uuid.UUID],
        vector: str,
    ) -> tuple[Literal["exact", "hnsw"], list[uuid.UUID]]:
        threshold = self._settings.knowledge_exact_scan_max_chunks
        params = {"owner": owner_key, "kbs": kbs, "v": vector, "n": CANDIDATES}
        cursor = await conn.execute(
            _ALLOWED_VECTORS,
            {"profile": KNOWLEDGE_PROFILE_ID, "kbs": kbs, "limit": threshold + 1},
        )
        count = await cursor.fetchone()
        if count is not None and count["n"] <= threshold:
            cursor = await conn.execute(_EXACT, {**params, "profile": KNOWLEDGE_PROFILE_ID})
            path: Literal["exact", "hnsw"] = "exact"
        else:
            # After the FTS query (see `search`): these settings would price out its GIN scan.
            await conn.execute(_ANN_SETTINGS)
            cursor = await conn.execute(self.ann_query(), params)
            path = "hnsw"
        floor = self._settings.knowledge_search_min_similarity
        return path, [
            row["chunk_id"] for row in await cursor.fetchall() if row["similarity"] >= floor
        ]

    def ann_query(self) -> sql.Composed:
        return _ANN.format(
            dims=sql.Literal(self._embeddings.dimensions),
            profile=sql.Literal(KNOWLEDGE_PROFILE_ID),
        )

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
