"""Reranking against RRF on the knowledge corpus, live (RAG-09.01 AC2).

The corpus is stored as in `test_postgres_knowledge_retrieval.py`, with its committed vectors, so
the only live calls are the reranker's: one per answerable case, over the fused top 40. Both
orders are scored with the same metrics; the reranker must not lose recall@5 beyond the
retrieval gate's tolerance and must raise MRR, since that gain is why it is on by default
(`docs/releases/v1.2.0-rerank-eval.md`).

Live and billed, so marked `integration` (`make test-integration`); it skips without
`NVIDIA_API_KEY` or `APP_TEST_POSTGRES_DSN`. With `APP_KNOWLEDGE_EVAL_REPORT` set, both orders'
metrics and the reranker's latency are written to that path.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import pytest
from scripts.build_knowledge_eval import DATASET, load_vectors
from test_postgres_knowledge_api import _Connections
from test_postgres_knowledge_retrieval import TOLERANCE, _Cached, _store
from test_postgres_roles import RoleDatabase, role_db, roles  # noqa: F401

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge.providers import EmbeddingProvider
from neuron_agent.knowledge.reranking import create_reranker
from neuron_agent.knowledge.retrieval import Retriever
from neuron_agent.retrieval_metrics import Located, first_hit_rank, retrieval_report

# Not `postgres`: the postgres-integration job fails on any skip, and this needs a key.
pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_reranking_beats_rrf_on_the_corpus(
    role_db: RoleDatabase,  # noqa: F811
    live_nvidia_key: str,
) -> None:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    index, vectors = load_vectors()
    settings = Settings(
        env="development", knowledge_reranker="nvidia", nvidia_api_key=live_nvidia_key
    ).model_copy(update={"knowledge_enabled": True})
    owners = {user: hashlib.sha256(user.encode()).hexdigest() for user in dataset["users"]}
    names = await _store(role_db, dataset, vectors, settings.knowledge_chunk_max_tokens, owners)
    cached = _Cached(vectors)
    embeddings = EmbeddingProvider(
        cached,
        cached,
        dimensions=index["dimensions"],
        locality="hosted",
        batch_size=8,
        max_retries=0,
    )
    pool = lambda: _Connections(role_db.app_dsn)  # noqa: E731
    plain = Retriever(settings, pool, embeddings)  # type: ignore[arg-type]
    reranking = Retriever(settings, pool, embeddings, create_reranker(settings))  # type: ignore[arg-type]

    ranks: dict[str, list[int | None]] = {"rrf": [], "reranked": []}
    seconds: list[float] = []
    for case in dataset["cases"]:
        if case["category"] != "answerable":
            continue
        for name, retriever in (("rrf", plain), ("reranked", reranking)):
            started = time.perf_counter()
            result = await retriever.search(owners[case["as_user"]], case["question"], k=10)
            if name == "reranked":
                seconds.append(time.perf_counter() - started)
                assert result.reranked, "the reranker fell back: the run is inconclusive"
            located = [
                Located(names[p.doc_id], p.page_start, p.page_end, tuple(p.headings), p.text)
                for p in result.passages
            ]
            ranks[name].append(first_hit_rank(case, located))

    report = {
        name: {
            **{k: retrieval_report(dataset["version"], r)[k] for k in ("recall_at_5", "mrr")},
            "recall_at_1": round(sum(rank == 1 for rank in r) / len(r), 3),
        }
        for name, r in ranks.items()
    }
    seconds.sort()
    report["model"] = settings.knowledge_reranker_model  # type: ignore[assignment]
    report["search_seconds_p50"] = round(seconds[len(seconds) // 2], 3)  # type: ignore[assignment]
    report["search_seconds_p95"] = round(seconds[int(len(seconds) * 0.95)], 3)  # type: ignore[assignment]
    if path := os.environ.get("APP_KNOWLEDGE_EVAL_REPORT"):
        Path(path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    rrf, reranked = report["rrf"], report["reranked"]
    assert reranked["recall_at_5"] >= rrf["recall_at_5"] - TOLERANCE, report
    assert reranked["mrr"] > rrf["mrr"], report
