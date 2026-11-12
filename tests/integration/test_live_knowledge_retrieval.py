"""Retrieval quality with the live embedding model and reranker, nightly (RAG-09.05).

The corpus is stored as in `test_postgres_knowledge_retrieval.py`, with its committed passage
vectors, as ingestion stored them. Each answerable case then searches the way production does with
an NVIDIA key: its question embedded by the live model and the fused candidates reranked live.
A provider-side change to either shows up as a drop: recall@5 and MRR must stay within `TOLERANCE`
of `evals/baselines/knowledge_retrieval_live.json`, and a failure names the metric.

Passages are not re-embedded: NVIDIA takes one passage per request, so the corpus would take over
an hour at the nightly's request rate. A model change re-embeds them with
`scripts/build_knowledge_eval.py embed`, which the cached-vector gate already requires.

Live and billed, so marked `integration`; it skips without `NVIDIA_API_KEY` or
`APP_TEST_POSTGRES_DSN` (the nightly job fails on a skip). Calls are paced to 30 a minute, the
nightly's throttle. `APP_KNOWLEDGE_EVAL_REPORT` and `APP_KNOWLEDGE_EVAL_WRITE_BASELINE=1` work as
in the cached-vector gate.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import anyio
import pytest
from scripts.build_knowledge_eval import DATASET, load_vectors
from test_postgres_knowledge_api import _Connections
from test_postgres_knowledge_retrieval import TOLERANCE, _store
from test_postgres_roles import RoleDatabase, role_db, roles  # noqa: F401

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge.providers import create_embedding_provider
from neuron_agent.knowledge.reranking import create_reranker
from neuron_agent.knowledge.retrieval import Retriever
from neuron_agent.retrieval_metrics import (
    Located,
    below_baseline,
    first_hit_rank,
    retrieval_report,
)

# Not `postgres`: the postgres-integration job fails on any skip, and this needs a key.
pytestmark = [pytest.mark.integration, pytest.mark.anyio]

BASELINE = Path("evals/baselines/knowledge_retrieval_live.json")
# Two calls a case (query embedding, rerank) at 30 calls a minute.
SECONDS_PER_CASE = 4.0


async def test_live_recall_and_mrr_hold_the_baseline(
    role_db: RoleDatabase,  # noqa: F811
    live_nvidia_key: str,
) -> None:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    index, vectors = load_vectors()
    settings = Settings(env="development", nvidia_api_key=live_nvidia_key).model_copy(
        update={"knowledge_enabled": True}
    )
    assert (index["model"], index["dimensions"]) == (
        settings.knowledge_embedding_model,
        settings.knowledge_embedding_dimensions,
    ), "the committed vectors are not the configured embedding model's"
    assert settings.knowledge_reranker_effective == "nvidia"
    owners = {user: hashlib.sha256(user.encode()).hexdigest() for user in dataset["users"]}
    names = await _store(role_db, dataset, vectors, settings.knowledge_chunk_max_tokens, owners)
    retriever = Retriever(
        settings,
        lambda: _Connections(role_db.app_dsn),  # type: ignore[arg-type,return-value]
        create_embedding_provider(settings),
        create_reranker(settings),
    )

    ranks: list[int | None] = []
    for case in dataset["cases"]:
        if case["category"] != "answerable":
            continue
        started = time.monotonic()
        result = await retriever.search(owners[case["as_user"]], case["question"], k=10)
        assert result.reranked, "the reranker fell back: the run is inconclusive"
        located = [
            Located(names[p.doc_id], p.page_start, p.page_end, tuple(p.headings), p.text)
            for p in result.passages
        ]
        ranks.append(first_hit_rank(case, located))
        await anyio.sleep(max(0.0, SECONDS_PER_CASE - (time.monotonic() - started)))

    report = retrieval_report(dataset["version"], ranks)
    metrics = {name: report[name] for name in ("recall_at_5", "mrr")}
    if path := os.environ.get("APP_KNOWLEDGE_EVAL_REPORT"):
        Path(path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if os.environ.get("APP_KNOWLEDGE_EVAL_WRITE_BASELINE") == "1":
        BASELINE.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert report["answerable_cases"] == 64
    assert not (dropped := below_baseline(metrics, baseline, TOLERANCE)), dropped
