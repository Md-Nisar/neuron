# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Hybrid search over the caller's knowledge bases (ADR 0014 K6; RAG-04.01).

Authorisation comes before ranking, in SQL: the search transaction finds the caller's readable
bases (`allowed_kbs`), sets `neuron.kb_ids` to them with `SET LOCAL` (row-level security repeats
the filter), and every candidate query filters on those bases and a live, `ready` document.
The bases include those shared with the caller's verified roles (RAG-09.03). Dense candidates
(cosine, the active index profile only) and full-text candidates (`websearch_to_tsquery` in each
base's text-search config) are fused with reciprocal rank fusion.

The dense path is chosen in code, never by the planner (RAG-00.02): an exact scan when the
allowed set has at most `knowledge_exact_scan_max_chunks` embeddings, which always returns every
row it can, and HNSW with `relaxed_order` iterative scan above it. The exact query orders by the
uncast column, which the HNSW index (on `embedding::halfvec(d)`) cannot serve; the HNSW query
orders by the indexed expression with bitmap scans and sorts priced out.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
import uuid
from collections.abc import AsyncIterator, Callable, Collection, Iterator, Sequence
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, get_args

import psycopg
import structlog
from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import AppError, KnowledgeDisabledError, PersistenceError
from neuron_agent.knowledge.authorization import KnowledgeAuthorization
from neuron_agent.knowledge.providers import (
    EmbeddingError,
    EmbeddingProvider,
    ensure_processing_allowed,
    provider_for,
)
from neuron_agent.knowledge.reranking import Reranker, RerankError
from neuron_agent.observability import metrics, semconv, telemetry
from neuron_agent.observability.audit import audit
from neuron_agent.persistence.migrations import KnowledgeProfile

log = structlog.get_logger(__name__)

SearchMode = Literal["hybrid", "dense", "fts"]
CANDIDATES = 80
MAX_K = 50
MAX_QUERY_CHARS = 2_000
# A search's own query plus at most two more (RAG-13.04), each searched, all fused, reranked once.
MAX_QUERIES = 3
RRF_K = 60
# A reranker reorders this many fused candidates, then the best `k` are kept (RAG-09.01).
RERANK_CANDIDATES = 40
# A reranker that keeps failing or timing out costs every search its full timeout for nothing.
# After this many failures in a row the retriever keeps the RRF order for the cooldown, then lets
# one search try again (half-open); a success closes the circuit.
_RERANK_BREAKER_FAILURES = 3
_RERANK_BREAKER_COOLDOWN_SECONDS = 30.0

# The readable bases with their index profile. A base is searched by meaning only on the active
# profile, with the configured model that embeds into it (RAG-09.04).
_BASES = (
    "SELECT b.kb_id, b.processing, b.ts_config::text AS ts_config, b.profile_id,"
    " p.status = 'active' AS active, p.provider, p.model, p.dimensions"
    " FROM knowledge.bases b JOIN knowledge.index_profiles p ON p.profile_id = b.profile_id"
    " WHERE b.kb_id = ANY(%(kbs)s) AND b.deleted_at IS NULL"
)
_SCOPE = "SELECT set_config('neuron.kb_ids', %s, true)"
# A chunk counts only through a live, ready document of a live base the caller may read.
_LIVE = (
    " JOIN knowledge.documents d ON d.doc_id = c.doc_id AND d.kb_id = c.kb_id"
    " JOIN knowledge.bases b ON b.kb_id = d.kb_id"
    " WHERE b.kb_id = ANY(%(kbs)s) AND b.deleted_at IS NULL"
    " AND d.deleted_at IS NULL AND d.status = 'ready'"
)
_CHUNKS = " FROM knowledge.chunks c"
# Through a function that applies the `kb_scope` filter itself, so `chunks_tsv_idx` serves the
# match: under RLS it cannot (migration 33). Ids only, best first; passages are read under RLS.
_FTS = (
    "SELECT chunk_id FROM knowledge.search_text(%(kbs)s, %(cfg)s::regconfig, %(q)s, %(n)s)"
    " WITH ORDINALITY ORDER BY ordinality"
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
# the profile row, never user input).
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
# A web page's URL and fetch time, for its citations (RAG-10.02); NULL for a file.
# Query parameters are stripped so signed tokens in a fetched URL never leak into citations.
WEB_SOURCE = (
    "CASE WHEN d.source_type = 'web' THEN split_part(d.source_ref, '?', 1) END AS source_url,"
    " d.fetched_at"
)
_PASSAGES = (
    "SELECT c.chunk_id, c.doc_id, c.kb_id, d.title, c.ordinal, c.text, c.headings,"
    " c.page_start, c.page_end, "
    + WEB_SOURCE
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
    # A web page's (RAG-10.02): where it was fetched from, and when. None for a file.
    source_url: str | None = None
    fetched_at: datetime | None = None


@dataclass(frozen=True)
class SearchResult:
    passages: list[Passage]
    # `exact` or `hnsw` for the dense path taken, `none` when it did not run.
    path: Literal["exact", "hnsw", "none"]
    # True when a reranker ordered the passages; False when none ran or it fell back to RRF.
    reranked: bool = False

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


def _rerank_skipped(code: str) -> None:
    log.warning("knowledge_rerank_skipped", error_code=code)
    metrics.record_knowledge_search_degraded("rerank_skipped", code)


@contextmanager
def _stage(name: str) -> Iterator[None]:
    """A child span for one search stage (RAG-14.01): its duration and name, nothing else."""
    with telemetry.start_span(
        f"{semconv.KNOWLEDGE_SEARCH_SPAN}.{name}",
        attributes={semconv.NEURON_KNOWLEDGE_SEARCH_STAGE: name},
    ):
        yield


def ann_query(profile_id: int, dimensions: int) -> sql.Composed:
    """The HNSW query for one profile; both values come from its row, never from input."""
    return _ANN.format(dims=sql.Literal(dimensions), profile=sql.Literal(profile_id))


class Retriever:
    def __init__(
        self,
        settings: Settings,
        pool: Callable[[], AsyncConnectionPool[Any] | None],
        embeddings: EmbeddingProvider,
        reranker: Reranker | None = None,
        reindex: EmbeddingProvider | None = None,
    ) -> None:
        self._settings = settings
        self._pool = pool
        self._embeddings = embeddings
        self._reranker = reranker
        # The re-index model (RAG-09.04): it embeds queries once its profile is the active one.
        self._reindex = reindex
        self._rerank_failures = 0
        self._rerank_open_until = 0.0
        self._rerank_probing = False

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
        roles: frozenset[str] = frozenset(),
        also: Sequence[str] = (),
    ) -> SearchResult:
        """The `k` best passages for `query` in the caller's readable bases, or only those of
        them in `kb_ids`: any other id there is ignored, as an unknown one is.

        `also` holds up to two more queries for the same search (RAG-13.04): each is searched
        in the same bases and transaction as `query`, all their rankings are fused by RRF, and
        the reranker orders the fused candidates once, against all the queries.

        Callers validate input first; out-of-range values are a programming error here.
        """
        queries = list(dict.fromkeys([query, *also]))
        if (
            not 1 <= k <= MAX_K
            or len(queries) > MAX_QUERIES
            or any(not q.strip() or len(q) > MAX_QUERY_CHARS for q in queries)
        ):
            raise ValueError(
                "search needs 1 <= k <= 50 and one to three queries of 1 to 2,000 characters"
            )
        mode = mode or self._settings.knowledge_search_mode
        if mode not in get_args(SearchMode):  # it labels a metric: keep it bounded
            raise ValueError("search mode must be hybrid, dense or fts")
        attributes = {
            semconv.NEURON_KNOWLEDGE_SEARCH_MODE: mode,
            semconv.NEURON_OWNER_KEY_PREFIX: owner_key[:12],
        }
        started = time.perf_counter()
        # Ids, counts and timings only: the query, passages and titles never reach telemetry.
        with telemetry.start_span(semconv.KNOWLEDGE_SEARCH_SPAN, attributes=attributes) as span:
            try:
                result, searched = await self._search(owner_key, roles, queries, k, kb_ids, mode)
            except Exception as exc:
                code = exc.context.code if isinstance(exc, AppError) else type(exc).__name__
                telemetry.record_error(span, code)
                metrics.record_knowledge_search(
                    time.perf_counter() - started,
                    mode=mode,
                    outcome="error",
                    error_type=code,
                    results=None,
                )
                raise
            span.set_attribute(semconv.NEURON_KNOWLEDGE_KB_IDS, [str(kb) for kb in searched])
            span.set_attribute(semconv.NEURON_KNOWLEDGE_SEARCH_PATH, result.path)
            span.set_attribute(semconv.NEURON_KNOWLEDGE_RESULTS, len(result.passages))
            span.set_attribute(semconv.NEURON_KNOWLEDGE_RERANKED, result.reranked)
            span.set_attribute(semconv.NEURON_OUTCOME, "success")
        metrics.record_knowledge_search(
            time.perf_counter() - started,
            mode=mode,
            outcome="success",
            error_type=None,
            results=len(result.passages),
        )
        return result

    async def _search(
        self,
        owner_key: str,
        roles: frozenset[str],
        queries: list[str],
        k: int,
        kb_ids: Collection[uuid.UUID] | None,
        mode: SearchMode,
    ) -> tuple[SearchResult, list[uuid.UUID]]:
        vectors: list[str] = []
        profile_id: int | None = None
        model: EmbeddingProvider | None = None
        if mode != "fts":
            # The query is embedded before the search transaction, so no connection is held
            # during the provider call; the bases are read again inside it, and only those still
            # on the profile the query was embedded for are searched by meaning.
            async with self._transaction() as conn:
                bases = await self._bases(conn, owner_key, roles, kb_ids)
            profile_id, model = self._model(bases)
            if model is not None and self._dense_bases(bases, profile_id, model):
                embed_timeout = max(
                    1.0,
                    min(
                        float(self._settings.knowledge_embedding_timeout_seconds),
                        float(self._settings.tool_timeout_seconds)
                        - float(self._settings.knowledge_reranker_timeout_seconds)
                        - 2.0,
                    ),
                )
                with _stage("embed"):
                    embedded = await asyncio.gather(
                        *(self._embed(model, q, owner_key, mode, embed_timeout) for q in queries)
                    )
                vectors = [v for v in embedded if v is not None]
        async with self._transaction() as conn:
            bases = await self._bases(conn, owner_key, roles, kb_ids)
            await conn.execute(_SCOPE, (",".join(str(row["kb_id"]) for row in bases),))
            rankings: list[list[uuid.UUID]] = []
            path: Literal["exact", "hnsw", "none"] = "none"
            # Full text first: the HNSW path's planner settings would price out its GIN scan.
            if mode != "dense":
                with _stage("fts"):
                    for q in queries:
                        rankings.extend(await self._fts(conn, bases, q))
            if (
                vectors
                and model is not None
                and (dense := self._dense_bases(bases, profile_id, model))
            ):
                assert profile_id is not None  # nosec B101
                with _stage("dense"):
                    for vector in vectors:
                        path, ranked = await self._dense(
                            conn, dense, vector, profile_id, model.dimensions
                        )
                        rankings.append(ranked)
            with _stage("fuse"):
                fused = fuse(rankings)[: max(k, RERANK_CANDIDATES) if self._reranker else k]
            # Primary-key lookups, which those settings leave alone.
            with _stage("passages"):
                passages = await self._passages(conn, owner_key, bases, fused)
        # After the transaction: no connection is held during the reranker's call.
        if self._reranker is not None and passages:
            with _stage("rerank"):
                passages, reranked = await self._rerank("\n".join(queries), bases, passages, k)
        else:
            passages, reranked = passages[:k], False
        audit(
            "knowledge_searched",
            outcome="allowed",
            actor=owner_key[:12] if self._settings.auth_mode == "jwt" else None,
            issuer_id=self._settings.auth_issuer_id,
            action="knowledge:read",
            resource_type="knowledge_base",
            count=len(passages),
        )
        return SearchResult(passages, path, reranked), [row["kb_id"] for row in bases]

    async def _embed(
        self,
        model: EmbeddingProvider,
        query: str,
        owner_key: str,
        mode: SearchMode,
        timeout: float,
    ) -> str | None:
        """The query's vector as a literal, or None when hybrid search degrades to full text."""
        try:
            async with asyncio.timeout(timeout):
                values = await model.embed_query(query, owner=owner_key)
        except TimeoutError as exc:
            if mode == "dense":
                raise EmbeddingError("embedding_timeout", retryable=True) from exc
            log.warning("knowledge_search_dense_skipped", error_code="embedding_timeout")
            metrics.record_knowledge_search_degraded("dense_skipped", "embedding_timeout")
        except EmbeddingError as exc:
            if mode == "dense":
                raise
            # Hybrid degrades to full text while the provider is down.
            log.warning("knowledge_search_dense_skipped", error_code=exc.code)
            metrics.record_knowledge_search_degraded("dense_skipped", exc.code)
        else:
            return "[" + ",".join(repr(float(value)) for value in values) + "]"
        return None

    async def _rerank(
        self, query: str, bases: Sequence[dict[str, Any]], passages: list[Passage], k: int
    ) -> tuple[list[Passage], bool]:
        """The best `k` passages by the reranker, or by RRF if there is none or it fails.

        Every candidate's base must allow its passages to go to the reranker, as for the
        embedding provider; a search over any base that forbids it keeps the RRF order.
        """
        if self._reranker is None or not passages:
            return passages[:k], False
        probing = False
        if self._rerank_failures >= _RERANK_BREAKER_FAILURES:
            if time.monotonic() < self._rerank_open_until or self._rerank_probing:
                _rerank_skipped("rerank_circuit_open")
                return passages[:k], False
            # Half-open: this one search tries the reranker, the others keep the RRF order; a
            # failure reopens the circuit for another cooldown.
            self._rerank_probing = probing = True
        processing = {row["kb_id"]: row["processing"] for row in bases}
        try:
            for kb_id in {passage.kb_id for passage in passages}:
                ensure_processing_allowed(
                    processing[kb_id],
                    self._reranker.locality,
                    self._settings.knowledge_processing_policy,
                )
            texts = [
                " > ".join(p.headings) + "\n" + p.text if p.headings else p.text for p in passages
            ]
            async with asyncio.timeout(self._settings.knowledge_reranker_timeout_seconds):
                order = await self._reranker.rerank(query, texts)
        except (EmbeddingError, RerankError) as exc:
            _rerank_skipped(exc.code)
            self._rerank_failed(exc)
            return passages[:k], False
        except TimeoutError:
            _rerank_skipped("rerank_timeout")
            self._rerank_failed(None)
            return passages[:k], False
        finally:
            if probing:
                self._rerank_probing = False
        self._rerank_failures = 0
        return [dataclasses.replace(passages[i], score=score) for i, score in order[:k]], True

    def _rerank_failed(self, exc: EmbeddingError | RerankError | None) -> None:
        """Count a provider failure toward opening the circuit. A policy refusal is not one, nor
        is the provider refusing one input, which says nothing about the next search."""
        if isinstance(exc, EmbeddingError) or (
            isinstance(exc, RerankError) and exc.code == "rerank_input_refused"
        ):
            return
        self._rerank_failures += 1
        if self._rerank_failures >= _RERANK_BREAKER_FAILURES:
            self._rerank_open_until = time.monotonic() + _RERANK_BREAKER_COOLDOWN_SECONDS

    @staticmethod
    async def _bases(
        conn: psycopg.AsyncConnection[Any],
        owner_key: str,
        roles: frozenset[str],
        kb_ids: Collection[uuid.UUID] | None,
    ) -> list[dict[str, Any]]:
        allowed = await KnowledgeAuthorization.allowed_kbs(conn, owner_key, roles)
        kbs = allowed.read if kb_ids is None else allowed.read & set(kb_ids)
        cursor = await conn.execute(_BASES, {"kbs": [*kbs]})
        return list(await cursor.fetchall())

    def _model(
        self, bases: Sequence[dict[str, Any]]
    ) -> tuple[int | None, EmbeddingProvider | None]:
        """The active profile among the bases, and the configured model that embeds into it.

        One profile is active at a time (ADR 0014 amendment, RAG-09.04). Without a model for
        it, the search runs on text only rather than compare vectors from two models.
        """
        row = next((row for row in bases if row["active"]), None)
        if row is None:
            return None, None
        profile = KnowledgeProfile(row["provider"], row["model"], row["dimensions"])
        model = provider_for(profile, self._embeddings, self._reindex)
        if model is None:
            log.warning("knowledge_profile_mismatch", profile_id=row["profile_id"])
        return row["profile_id"], model

    def _dense_bases(
        self, bases: Sequence[dict[str, Any]], profile_id: int | None, model: EmbeddingProvider
    ) -> list[uuid.UUID]:
        """Bases searched by meaning: on the profile `model` embeds into, while it is active,
        and whose processing setting and the operator's policy allow the query to go to it."""
        allowed = []
        for row in bases:
            if not row["active"] or row["profile_id"] != profile_id:
                continue
            try:
                ensure_processing_allowed(
                    row["processing"],
                    model.locality,
                    self._settings.knowledge_processing_policy,
                )
            except EmbeddingError:
                continue  # searched by text only
            allowed.append(row["kb_id"])
        return allowed

    async def _dense(
        self,
        conn: psycopg.AsyncConnection[Any],
        kbs: list[uuid.UUID],
        vector: str,
        profile_id: int,
        dimensions: int,
    ) -> tuple[Literal["exact", "hnsw"], list[uuid.UUID]]:
        threshold = self._settings.knowledge_exact_scan_max_chunks
        params = {"kbs": kbs, "v": vector, "n": CANDIDATES}
        cursor = await conn.execute(
            _ALLOWED_VECTORS,
            {"profile": profile_id, "kbs": kbs, "limit": threshold + 1},
        )
        count = await cursor.fetchone()
        if count is not None and count["n"] <= threshold:
            cursor = await conn.execute(_EXACT, {**params, "profile": profile_id})
            path: Literal["exact", "hnsw"] = "exact"
        else:
            # After the FTS query (see `search`): these settings would price out its GIN scan.
            await conn.execute(_ANN_SETTINGS)
            cursor = await conn.execute(ann_query(profile_id, dimensions), params)
            path = "hnsw"
        floor = self._settings.knowledge_search_min_similarity
        return path, [
            row["chunk_id"] for row in await cursor.fetchall() if row["similarity"] >= floor
        ]

    @staticmethod
    async def _fts(
        conn: psycopg.AsyncConnection[Any],
        bases: Sequence[dict[str, Any]],
        query: str,
    ) -> list[list[uuid.UUID]]:
        """One combined FTS ranking across all base text-search configs, weighted by rank
        so multi-language bases do not multiply RRF weight."""
        by_config: dict[str, list[uuid.UUID]] = {}
        for row in bases:
            by_config.setdefault(row["ts_config"], []).append(row["kb_id"])
        scores: dict[uuid.UUID, float] = {}
        for config, kbs in sorted(by_config.items()):
            cursor = await conn.execute(
                _FTS, {"kbs": kbs, "cfg": config, "q": query, "n": CANDIDATES}
            )
            for rank, row in enumerate(await cursor.fetchall(), 1):
                cid = row["chunk_id"]
                scores[cid] = max(scores.get(cid, 0.0), 1.0 / (RRF_K + rank))
        if not scores:
            return []
        ranked = [
            cid for cid, _ in sorted(scores.items(), key=lambda pair: (-pair[1], str(pair[0])))
        ]
        return [ranked[:CANDIDATES]]

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
