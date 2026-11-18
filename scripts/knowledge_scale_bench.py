# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Retrieval at scale: search latency and HNSW recall on a synthetic corpus. Local use only.

Runs the real `Retriever` (RLS, `allowed_kbs`, the exact/HNSW choice, full text, RRF) against
a throwaway pgvector database; never point it at a database holding real documents.

    docker run -d --name kbbench -e POSTGRES_PASSWORD=... -p 55432:5432 pgvector/pgvector:pg16
    # as the superuser: roles bench_migrator and bench_app, a database owned by the migrator,
    # CREATE EXTENSION vector, CREATE SCHEMA knowledge AUTHORIZATION bench_migrator
    export BENCH_SUPER_DSN=... BENCH_MIGRATOR_DSN=... BENCH_APP_DSN=...
    uv run --with numpy python -m scripts.knowledge_scale_bench load 100000
    uv run --with numpy python -m scripts.knowledge_scale_bench index
    uv run --with numpy python -m scripts.knowledge_scale_bench bench > figures.json

`load N` grows the corpus to N chunks: a small base (2,000 chunks, the exact path), a mid base
(20,000, HNSW filtered to a fraction of the table) and a big base (the rest), each owned by a
different user. `index` drops and rebuilds the HNSW index through `run_setup`, as an upgrade
does. Vectors are 1,024-dimensional, clustered by topic around a shared direction; text is
Zipf-distributed English-like words. Both are synthetic: real embeddings and prose differ.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import statistics
import struct
import sys
import time
import uuid
from typing import Any

import numpy as np
import psycopg
import structlog
from langchain_core.embeddings import Embeddings
from psycopg_pool import AsyncConnectionPool
from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge.providers import EmbeddingProvider
from neuron_agent.knowledge.retrieval import Retriever
from neuron_agent.persistence.migrations import KnowledgeProfile, run_setup

DIMS = 1024
CHUNKS_PER_DOC = 50
WORDS_PER_CHUNK = 300  # about 400 tokens, the default chunk size
TOPICS = 2_000
BASES = {"small": 2_000, "mid": 20_000}  # "big" takes the rest
QUERIES = 40
CONCURRENCY = 8
HEAD = (
    "the of and to a in is that for it as was with be by on not he this are or his from at which"
    " but have an they you were her she there been one all we their has would when if so no will"
    " more can its who what about up out them some into than other time only could new these"
    " may first then do any like my now over such our man me even most made after also did many"
).split()


def owner(name: str) -> str:
    return hashlib.sha256(f"bench-{name}".encode()).hexdigest()


def kb_id(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"bench/{name}")


VOCAB = HEAD + [f"t{i:05d}" for i in range(40_000)]
_ZIPF = 1.0 / np.arange(1, len(VOCAB) + 1) ** 1.07
_ZIPF /= _ZIPF.sum()


def _rng(seed: str) -> np.random.Generator:
    return np.random.default_rng(int(hashlib.sha256(seed.encode()).hexdigest()[:15], 16))


_space = _rng("space")
_MEAN = _space.standard_normal(DIMS).astype(np.float32)
_MEAN /= np.linalg.norm(_MEAN)
_CENTRES = _space.standard_normal((TOPICS, DIMS)).astype(np.float32)
_CENTRES /= np.linalg.norm(_CENTRES, axis=1, keepdims=True)


def vectors(rng: np.random.Generator, topics: np.ndarray) -> np.ndarray:
    noise = rng.standard_normal((len(topics), DIMS)).astype(np.float32) / np.sqrt(DIMS)
    v = 0.5 * _MEAN + _CENTRES[topics] + noise
    return (v / np.linalg.norm(v, axis=1, keepdims=True)).astype(np.float16)


def texts(rng: np.random.Generator, topics: np.ndarray) -> list[str]:
    words = rng.choice(len(VOCAB), size=(len(topics), WORDS_PER_CHUNK), p=_ZIPF)
    # Each topic has its own few terms, so text and meaning agree a little.
    topical = rng.integers(0, 5, size=(len(topics), 12)) + (topics[:, None] * 5) % 40_000
    words[:, ::25] = topical + len(HEAD)
    return [" ".join(VOCAB[w] for w in row) for row in words]


def _copy_binary_embeddings(ids: list[uuid.UUID], kb: uuid.UUID, vecs: np.ndarray) -> bytes:
    out = io.BytesIO()
    out.write(b"PGCOPY\n\xff\r\n\x00" + struct.pack(">ii", 0, 0))
    tail = struct.pack(">hh", DIMS, 0)
    for cid, vec in zip(ids, vecs.astype(">f2"), strict=True):
        out.write(struct.pack(">hi", 4, 16) + cid.bytes)
        out.write(struct.pack(">ih", 2, 1))
        out.write(struct.pack(">i", 16) + kb.bytes)
        out.write(struct.pack(">i", 4 + 2 * DIMS) + tail + vec.tobytes())
    out.write(struct.pack(">h", -1))
    return out.getvalue()


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\t", " ").replace("\n", " ")


def load_base(conn: psycopg.Connection[Any], name: str, start: int, count: int) -> None:
    """Add `count` chunks to base `name`, documents `start // 50` onwards."""
    kb = kb_id(name)
    for first in range(start, start + count, 10_000):
        n = min(10_000, start + count - first)
        rng = _rng(f"{name}/{first}")
        docs = [uuid.uuid5(kb, str(d)) for d in range(first // 50, (first + n - 1) // 50 + 1)]
        topics = np.repeat(rng.integers(0, TOPICS, len(docs)), CHUNKS_PER_DOC)[:n]
        ids = [uuid.uuid4() for _ in range(n)]
        with conn.cursor() as cur:
            with cur.copy(
                "COPY knowledge.documents (doc_id, kb_id, uploaded_by, title, mime_type,"
                " size_bytes, sha256, blob_key, status) FROM STDIN"
            ) as copy:
                for d in docs:
                    sha = hashlib.sha256(d.bytes).hexdigest()
                    copy.write(
                        f"{d}\t{kb}\t{owner(name)}\tDoc {d}\ttext/markdown\t1\t{sha}\t"
                        f"bench/{d}\tready\n"
                    )
            with cur.copy(
                "COPY knowledge.chunks (chunk_id, doc_id, kb_id, ordinal, text, token_count,"
                " ts_config) FROM STDIN"
            ) as copy:
                for i, (cid, text) in enumerate(zip(ids, texts(rng, topics), strict=True)):
                    doc = docs[(first + i) // 50 - first // 50]
                    copy.write(
                        f"{cid}\t{doc}\t{kb}\t{(first + i) % 50}\t{_escape(text)}\t400\tsimple\n"
                    )
            with cur.copy(
                "COPY knowledge.embeddings (chunk_id, profile_id, kb_id, embedding)"
                " FROM STDIN (FORMAT binary)"
            ) as copy:
                copy.write(_copy_binary_embeddings(ids, kb, vectors(rng, topics)))
        conn.commit()
        print(f"{name}: {first + n} chunks", file=sys.stderr)


def load(total: int) -> None:
    sizes = {**BASES, "big": total - sum(BASES.values())}
    with psycopg.connect(os.environ["BENCH_SUPER_DSN"]) as conn:
        for name in sizes:
            conn.execute(
                "INSERT INTO knowledge.bases (kb_id, owner_key, name, profile_id)"
                " VALUES (%s, %s, %s, 1) ON CONFLICT DO NOTHING",
                (kb_id(name), owner(name), name),
            )
            conn.execute(
                "INSERT INTO knowledge.grants (kb_id, subject_type, subject, access, granted_by)"
                " VALUES (%s, 'owner', %s, 'admin', %s) ON CONFLICT DO NOTHING",
                (kb_id(name), owner(name), owner(name)),
            )
        conn.commit()
        for name, size in sizes.items():
            row = conn.execute(
                "SELECT count(*) FROM knowledge.chunks WHERE kb_id = %s", (kb_id(name),)
            ).fetchone()
            have = int(row[0]) if row else 0
            if size > have:
                load_base(conn, name, have, size - have)
        conn.execute("ANALYZE")


async def setup() -> None:
    await run_setup(
        os.environ["BENCH_MIGRATOR_DSN"],
        app_role="bench_app",
        knowledge=True,
        knowledge_profile=KnowledgeProfile(),
    )


async def index() -> None:
    with psycopg.connect(os.environ["BENCH_SUPER_DSN"], autocommit=True) as conn:
        conn.execute("DROP INDEX IF EXISTS knowledge.embeddings_p1_hnsw")
    started = time.perf_counter()
    await setup()
    print(json.dumps({"hnsw_build_seconds": round(time.perf_counter() - started, 1)}))


class _Queries(Embeddings):
    """Query text names a precomputed vector; nothing leaves the machine."""

    def __init__(self) -> None:
        self.by_text: dict[str, list[float]] = {}

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        return self.by_text[text]


def _queries(conn: psycopg.Connection[Any], name: str) -> list[tuple[str, list[float]]]:
    """Near a random chunk of the base: its vector plus noise, and a phrase from its text."""
    rows = conn.execute(
        "SELECT c.text, e.embedding::text FROM knowledge.chunks c"
        " JOIN knowledge.embeddings e USING (chunk_id)"
        " WHERE c.kb_id = %s ORDER BY md5(c.chunk_id::text) LIMIT %s",
        (kb_id(name), QUERIES),
    ).fetchall()
    rng = _rng(f"queries/{name}")
    out = []
    for text, emb in rows:
        v = np.array(json.loads(emb), dtype=np.float32)
        v += rng.standard_normal(DIMS).astype(np.float32) / np.sqrt(DIMS) * 0.7
        words = text.split()
        at = int(rng.integers(0, len(words) - 4))
        out.append((" ".join(words[at : at + 3]), (v / np.linalg.norm(v)).tolist()))
    return out


def _pct(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(p * len(ordered)))] * 1000, 1)


def _summary(times: list[float]) -> dict[str, float]:
    return {"p50_ms": _pct(times, 0.5), "p95_ms": _pct(times, 0.95), "max_ms": _pct(times, 1.0)}


async def bench() -> None:
    queries = _Queries()
    model = EmbeddingProvider(
        queries, queries, dimensions=DIMS, locality="hosted", batch_size=1, max_retries=0
    )
    settings = Settings(
        env="test",
        checkpointer="postgres",
        knowledge_enabled=True,
        knowledge_embedding_dimensions=DIMS,
        postgres_dsn=SecretStr(os.environ["BENCH_APP_DSN"]),
    )
    exact_settings = settings.model_copy(update={"knowledge_exact_scan_max_chunks": 10_000_000})
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        os.environ["BENCH_APP_DSN"],
        min_size=CONCURRENCY,
        max_size=CONCURRENCY,
        open=False,
        kwargs={"row_factory": psycopg.rows.dict_row, "autocommit": True},
    )
    await pool.open()
    retriever = Retriever(settings, lambda: pool, model)
    exact = Retriever(exact_settings, lambda: pool, model)
    with psycopg.connect(os.environ["BENCH_SUPER_DSN"]) as conn:
        total = conn.execute("SELECT count(*) FROM knowledge.embeddings").fetchone()
        sets = {name: _queries(conn, name) for name in ("small", "mid", "big")}
    for qs in sets.values():
        queries.by_text.update(qs)
    common = ["the"] * QUERIES  # the worst full-text case
    figures: dict[str, Any] = {"chunks": total[0] if total else 0, "bases": {}}

    async def run(r: Retriever, who: str, text: str, mode: str) -> tuple[float, Any]:
        started = time.perf_counter()
        result = await r.search(owner(who), text, k=10, mode=mode)  # type: ignore[arg-type]
        return time.perf_counter() - started, result

    for name, qs in sets.items():
        await run(retriever, name, qs[0][0], "hybrid")  # warm the cache
        entry: dict[str, Any] = {}
        recalls, paths = [], set()
        for mode in ("dense", "fts", "hybrid"):
            times = []
            for text, _ in qs:
                elapsed, result = await run(retriever, name, text, mode)
                times.append(elapsed)
                if mode == "dense":
                    paths.add(result.path)
                    _, truth = await run(exact, name, text, "dense")
                    want = {p.chunk_id for p in truth.passages}
                    recalls.append(len(want & {p.chunk_id for p in result.passages}) / len(want))
            entry[mode] = _summary(times)
        times = [(await run(retriever, name, q, "fts"))[0] for q in common]
        entry["fts_common_word"] = _summary(times)
        times = [(await run(exact, name, text, "dense"))[0] for text, _ in qs[:10]]
        entry["dense_exact_scan"] = _summary(times)
        entry["dense_path"] = sorted(paths)
        entry["recall_at_10"] = round(statistics.mean(recalls), 3)
        figures["bases"][name] = entry
        print(f"{name}: {json.dumps(entry)}", file=sys.stderr)

    # Concurrency: every base's hybrid queries at once, CONCURRENCY in flight.
    work = [(name, text) for name, qs in sets.items() for text, _ in qs]
    gate = asyncio.Semaphore(CONCURRENCY)
    times: list[float] = []

    async def one(name: str, text: str) -> None:
        async with gate:
            times.append((await run(retriever, name, text, "hybrid"))[0])

    started = time.perf_counter()
    await asyncio.gather(*(one(n, t) for n, t in work * 2))
    wall = time.perf_counter() - started
    figures["concurrent_hybrid"] = {
        "in_flight": CONCURRENCY,
        "searches": len(times),
        "per_second": round(len(times) / wall, 1),
        **_summary(times),
    }
    await pool.close()
    print(json.dumps(figures, indent=2))


def main() -> None:
    # The app's log and audit lines go to stderr, so `bench > figures.json` is valid JSON.
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(sys.stderr))
    command = sys.argv[1]
    if command == "setup":
        asyncio.run(setup())
    elif command == "load":
        load(int(sys.argv[2]))
    elif command == "index":
        asyncio.run(index())
    elif command == "bench":
        asyncio.run(bench())


if __name__ == "__main__":
    main()
