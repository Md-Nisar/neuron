"""Regression tests for RAG & Knowledge Engine review remediations."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest
from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage, HumanMessage

from neuron_agent.api.main import _RequestBodyLimitMiddleware, upload_body_limit
from neuron_agent.config.settings import Settings
from neuron_agent.knowledge.blobs import StoredBlob
from neuron_agent.knowledge.ingest import Ingestor
from neuron_agent.knowledge.parsing import Limits, PlainTextParser
from neuron_agent.knowledge.providers import EmbeddingError, EmbeddingProvider
from neuron_agent.knowledge.reindex import Reindexer
from neuron_agent.knowledge.retrieval import WEB_SOURCE, Retriever
from neuron_agent.knowledge.service import _DOCUMENT_COLUMNS, _FIND_TABLES
from neuron_agent.knowledge.tools import MAX_CHARS, _capped, _repeated
from neuron_agent.persistence.migrations import _SEARCH_TEXT_OR_QUERY, SEARCH_TEXT_QUERY

pytestmark = pytest.mark.anyio


class _FakeCursor:
    def __init__(
        self,
        *,
        fetchone: Any = None,
        fetchall: list[Any] | None = None,
        rowcount: int = 0,
    ) -> None:
        self._fetchone = fetchone
        self._fetchall = fetchall or []
        self.rowcount = rowcount

    async def fetchone(self) -> Any:
        return self._fetchone

    async def fetchall(self) -> list[Any]:
        return self._fetchall


class _ScriptedConn:
    def __init__(self, responder: Any) -> None:
        self._responder = responder
        self.queries: list[tuple[str, Any]] = []

    @asynccontextmanager
    async def transaction(self) -> Any:
        yield

    @asynccontextmanager
    async def cursor(self) -> Any:
        yield self

    async def execute(self, query: Any, params: Any = None) -> _FakeCursor:
        text = str(query)
        self.queries.append((text, params))
        return self._responder(text, params)

    async def executemany(self, query: Any, params: Any) -> None:
        self.queries.append((str(query), params))

    async def __aenter__(self) -> _ScriptedConn:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


def test_web_source_sql_strips_query_parameters() -> None:
    assert "split_part(d.source_ref, '?', 1) END AS source_url" in WEB_SOURCE
    assert "split_part(d.source_ref, '?', 1) END AS source_url" in _DOCUMENT_COLUMNS


def test_find_tables_sql_searches_column_names_and_filters_on_words() -> None:
    assert "jsonb_array_elements(t.columns)" in _FIND_TABLES
    assert "t.columns::text" not in _FIND_TABLES
    assert "OR hits > 0" in _FIND_TABLES


def test_search_text_sql_includes_headings_and_relaxed_or_fallback() -> None:
    assert "c.headings_tsv @@ websearch_to_tsquery($2, $3)" in SEARCH_TEXT_QUERY
    assert "plainto_tsquery($2, w)" in _SEARCH_TEXT_OR_QUERY
    assert "c.headings_tsv @@ q.tsq" in _SEARCH_TEXT_OR_QUERY


class _SlowQueryEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    async def aembed_query(self, text: str) -> list[float]:
        await asyncio.sleep(5)
        return [0.1, 0.2, 0.3, 0.4]


class _FakePool:
    def __init__(self, conn: _ScriptedConn) -> None:
        self._conn = conn

    @asynccontextmanager
    async def connection(self) -> Any:
        yield self._conn


async def test_retriever_embed_query_timeout_degrades_hybrid_and_fails_dense() -> None:
    kb_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    doc_id = uuid.uuid4()
    slow = _SlowQueryEmbeddings()
    provider = EmbeddingProvider(
        slow, slow, dimensions=4, locality="self_hosted", batch_size=8, max_retries=0
    )

    def respond(query: str, params: Any) -> _FakeCursor:
        if "FROM knowledge.grants" in query:
            return _FakeCursor(
                fetchall=[
                    {
                        "kb_id": kb_id,
                        "access": "owner",
                        "subject_type": "owner",
                    }
                ]
            )
        if "FROM knowledge.bases" in query:
            return _FakeCursor(
                fetchall=[
                    {
                        "kb_id": kb_id,
                        "processing": "self_hosted",
                        "ts_config": "simple",
                        "profile_id": 1,
                        "active": True,
                        "provider": provider.profile.provider,
                        "model": provider.profile.model,
                        "dimensions": provider.profile.dimensions,
                    }
                ]
            )
        if "knowledge.search_text" in query:
            return _FakeCursor(fetchall=[{"chunk_id": chunk_id}])
        if "SELECT c.chunk_id, c.doc_id" in query:
            return _FakeCursor(
                fetchall=[
                    {
                        "chunk_id": chunk_id,
                        "doc_id": doc_id,
                        "kb_id": kb_id,
                        "title": "Doc",
                        "ordinal": 0,
                        "text": "matched by fts",
                        "headings": [],
                        "page_start": None,
                        "page_end": None,
                        "source_url": None,
                        "fetched_at": None,
                    }
                ]
            )
        return _FakeCursor()

    settings = Settings(
        env="test",
        knowledge_enabled=True,
        checkpointer="postgres",
        postgres_dsn="postgresql://app@localhost/n",
        knowledge_embedding_timeout_seconds=1,
    )
    pool = _FakePool(_ScriptedConn(respond))
    retriever = Retriever(settings, lambda: pool, provider)  # type: ignore[arg-type]

    hybrid = await retriever.search("owner-key", "policy", k=5, mode="hybrid")
    assert [p.chunk_id for p in hybrid.passages] == [chunk_id]

    with pytest.raises(EmbeddingError) as caught:
        await retriever.search("owner-key", "policy", k=5, mode="dense")
    assert caught.value.code == "embedding_timeout"


async def test_retriever_fts_merges_multi_config_rankings_into_one() -> None:
    kb_en, kb_fr = uuid.uuid4(), uuid.uuid4()
    c1, c2 = uuid.uuid4(), uuid.uuid4()

    def respond(query: str, params: Any) -> _FakeCursor:
        cfg = (params or {}).get("cfg")
        if cfg == "english":
            return _FakeCursor(fetchall=[{"chunk_id": c1}])
        if cfg == "french":
            return _FakeCursor(fetchall=[{"chunk_id": c2}, {"chunk_id": c1}])
        return _FakeCursor()

    conn = _ScriptedConn(respond)
    rankings = await Retriever._fts(
        conn,  # type: ignore[arg-type]
        [
            {"kb_id": kb_en, "ts_config": "english"},
            {"kb_id": kb_fr, "ts_config": "french"},
        ],
        "policy",
    )
    assert len(rankings) == 1
    assert set(rankings[0]) == {c1, c2}


async def test_purge_retired_chunks_scope_guc() -> None:
    kbs = [{"kb_id": uuid.uuid4()} for _ in range(250)]
    scopes: list[str] = []

    def respond(query: str, params: Any) -> _FakeCursor:
        if "SELECT kb_id FROM knowledge.bases" in query:
            return _FakeCursor(fetchall=kbs)
        if "set_config('neuron.kb_ids'" in query:
            scopes.append(params[0])
            return _FakeCursor()
        if "DELETE FROM knowledge.embeddings" in query:
            return _FakeCursor(rowcount=1)
        return _FakeCursor()

    conn = _ScriptedConn(respond)

    async def connect() -> Any:
        return conn

    fake = _SlowQueryEmbeddings()
    provider = EmbeddingProvider(
        fake, fake, dimensions=4, locality="self_hosted", batch_size=8, max_retries=0
    )
    reindexer = Reindexer(connect, provider, None, "allow_hosted")
    removed = await reindexer.purge_retired(batch=100)
    assert removed == 3
    assert [len(s.split(",")) for s in scopes] == [100, 100, 50]


async def test_ingestor_releases_db_connection_across_external_io() -> None:
    connections_opened = 0
    active_connections = 0
    open_during_io: list[int] = []
    doc_id = uuid.uuid4()
    kb_id = uuid.uuid4()

    class _TrackingEmbed(Embeddings):
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

        def embed_query(self, text: str) -> list[float]:
            return [0.1, 0.2, 0.3, 0.4]

        async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
            open_during_io.append(active_connections)
            return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

        async def aembed_query(self, text: str) -> list[float]:
            return [0.1, 0.2, 0.3, 0.4]

    tracking_embed = _TrackingEmbed()
    provider = EmbeddingProvider(
        tracking_embed,
        tracking_embed,
        dimensions=4,
        locality="self_hosted",
        batch_size=8,
        max_retries=0,
    )

    class _Blobs:
        async def get(self, key: str, sha256: str) -> bytes:
            open_during_io.append(active_connections)
            return b"hello knowledge world"

        async def put(self, chunks: Any, *, max_bytes: int) -> StoredBlob:
            return StoredBlob("a" * 32, "b" * 64, 5)

        async def delete(self, key: str) -> None:
            return None

        async def exists(self, key: str) -> bool:
            return True

        def older_than(self, cutoff: Any) -> Any:
            raise NotImplementedError

    def respond(query: str, params: Any) -> _FakeCursor:
        if "FROM knowledge.documents d JOIN knowledge.bases" in query and "FOR UPDATE" not in query:
            return _FakeCursor(
                fetchone={
                    "kb_id": kb_id,
                    "mime_type": "text/plain",
                    "blob_key": "a" * 32,
                    "sha256": "b" * 64,
                    "source_ref": None,
                    "processing": "self_hosted",
                    "ts_config": "simple",
                }
            )
        if "FROM knowledge.index_profiles" in query:
            return _FakeCursor(
                fetchall=[
                    {
                        "profile_id": 1,
                        "status": "active",
                        "provider": provider.profile.provider,
                        "model": provider.profile.model,
                        "dimensions": provider.profile.dimensions,
                    }
                ]
            )
        if "FOR UPDATE OF d" in query:
            return _FakeCursor(fetchone={"kb_id": kb_id})
        return _FakeCursor()

    class _TrackedConn(_ScriptedConn):
        async def __aenter__(self) -> _ScriptedConn:
            nonlocal active_connections
            active_connections += 1
            return self

        async def __aexit__(self, *_: object) -> None:
            nonlocal active_connections
            active_connections -= 1

    async def connect() -> Any:
        nonlocal connections_opened
        connections_opened += 1
        return _TrackedConn(respond)

    ingestor = Ingestor(
        connect=connect,
        blobs=_Blobs(),
        parsers=(PlainTextParser(),),
        embeddings=provider,
        limits=Limits(10_000, 10, 5_000),
        chunk_max_tokens=100,
        policy="allow_hosted",
    )
    status = await ingestor.ingest(doc_id)
    assert status == "ready"
    assert connections_opened == 3
    assert open_during_io == [0, 0]
    assert active_connections == 0


async def test_request_body_limit_middleware_handles_root_path() -> None:
    seen_calls = 0

    async def app(scope: Any, receive: Any, send: Any) -> None:
        nonlocal seen_calls
        seen_calls += 1

    middleware = _RequestBodyLimitMiddleware(app)
    scope = {
        "type": "http",
        "method": "POST",
        "root_path": "/api",
        "path": f"/api/v1/knowledge/bases/{uuid.uuid4()}/documents",
        "headers": [(b"content-length", str(upload_body_limit()).encode("ascii"))],
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        return None

    await middleware(scope, receive, send)
    assert seen_calls == 1


def test_capped_preserves_longest_prefix_under_json_escape_expansion() -> None:
    non_latin = "こんにちは世界" * 5000
    text, shown = _capped([{"cite_id": "abc", "text": non_latin}])
    assert len(text) <= MAX_CHARS
    assert len(shown) == 1
    assert len(shown[0]["text"]) > 100


def test_repeated_canonicalizes_narrowed_scope() -> None:
    kb_a, kb_other = uuid.uuid4(), uuid.uuid4()
    prior = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "search_knowledge",
                "args": {"query": "Leave Policy", "kb_ids": [str(kb_a)]},
                "id": "call_1",
                "type": "tool_call",
            }
        ],
    )
    current = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "search_knowledge",
                "args": {"query": "leave  policy", "kb_ids": [kb_other]},
                "id": "call_2",
                "type": "tool_call",
            }
        ],
    )
    assert _repeated(
        [HumanMessage("q"), prior, current],
        "call_2",
        {"query": "leave  policy", "kb_ids": [kb_a]},
        frozenset({kb_a}),
    )
