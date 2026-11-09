"""Retrieval quality on the knowledge corpus, gated against a baseline (RAG-08.01, part 2).

Every document of `knowledge_cases.json` is chunked by Neuron's chunker from its committed
parser output (`tests/fixtures/knowledge/eval/parsed.json.gz`) and stored as ingestion stores it,
with its passage's committed embedding, on Postgres. Each answerable case then searches as its
own user through `Retriever`, with its question's committed embedding, so no provider is called.
recall@5 and MRR must stay within `TOLERANCE` of `evals/baselines/knowledge_retrieval.json`.

A chunker or parser change that alters a passage fails here until its vectors are rebuilt:
`scripts/build_knowledge_eval.py` (see its docstring). With `APP_KNOWLEDGE_EVAL_REPORT` set,
the report's `retrieval` section is written to that path; with
`APP_KNOWLEDGE_EVAL_WRITE_BASELINE=1`, the run's metrics become the baseline.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import jsonschema
import psycopg
import pytest
from langchain_core.embeddings import Embeddings
from scripts.build_knowledge_eval import DATASET, key, load_parsed, load_vectors, passages
from test_postgres_knowledge_api import _Connections
from test_postgres_knowledge_tables import _knowledge_db
from test_postgres_roles import RoleDatabase, role_db, roles  # noqa: F401

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge.ingest import _INSERT_CHUNK, _INSERT_EMBEDDING, _passage, _vector
from neuron_agent.knowledge.providers import EmbeddingProvider
from neuron_agent.knowledge.retrieval import Retriever
from neuron_agent.persistence.migrations import KNOWLEDGE_PROFILE_ID
from neuron_agent.retrieval_metrics import (
    Located,
    below_baseline,
    first_hit_rank,
    retrieval_report,
)

pytestmark = [pytest.mark.eval, pytest.mark.postgres, pytest.mark.anyio]

BASELINE = Path("evals/baselines/knowledge_retrieval.json")
SCHEMA = Path("tests/fixtures/eval_report.schema.json")
# Below the baseline by more than this fails: about one case in 64 for recall@5.
TOLERANCE = 0.02


class _Cached(Embeddings):
    """Questions' committed vectors; a passage is never embedded here."""

    def __init__(self, vectors: Mapping[str, Sequence[float]]) -> None:
        self._vectors = vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        return list(self._vectors[key("query", text)])


async def _store(
    db: RoleDatabase,
    dataset: dict[str, Any],
    vectors: Mapping[str, Sequence[float]],
    max_tokens: int,
    owners: Mapping[str, str],
) -> dict[uuid.UUID, str]:
    """Each user's documents in one knowledge base of theirs (`owners` maps each dataset user
    to its owner key); returns doc_id -> dataset id."""
    chunks = passages(load_parsed(), max_tokens)
    absent = [_passage(c) for cs in chunks.values() for c in cs]
    absent = [t for t in absent if key("passage", t) not in vectors]
    assert not absent, (
        f"{len(absent)} passages have no committed vector (the chunker or parser output changed):"
        " run `scripts/build_knowledge_eval.py embed` with NVIDIA_API_KEY"
    )
    await _knowledge_db(db)
    kbs = {owner: uuid.uuid4() for owner in owners.values()}
    names: dict[uuid.UUID, str] = {}
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        for owner, kb in kbs.items():
            await conn.execute(
                "INSERT INTO knowledge.bases (kb_id, owner_key, name, profile_id)"
                " VALUES (%s, %s, 'eval', %s)",
                (kb, owner, KNOWLEDGE_PROFILE_ID),
            )
            await conn.execute(
                "INSERT INTO knowledge.grants (kb_id, subject_type, subject, access, granted_by)"
                " VALUES (%s, 'owner', %s, 'admin', %s)",
                (kb, owner, owner),
            )
        for doc in dataset["documents"]:
            owner, doc_id = owners[doc["owner"]], uuid.uuid4()
            names[doc_id] = doc["id"]
            await conn.execute(
                "INSERT INTO knowledge.documents (doc_id, kb_id, uploaded_by, title, mime_type,"
                " size_bytes, sha256, blob_key, status) VALUES (%s, %s, %s, %s, %s, %s, %s, 'k',"
                " 'ready')",
                (doc_id, kbs[owner], owner, doc["title"], doc["media_type"], doc["size_bytes"],
                 doc["sha256"]),
            )  # fmt: skip
            ids = [uuid.uuid4() for _ in chunks[doc["id"]]]
            async with conn.cursor() as cursor:
                await cursor.executemany(
                    _INSERT_CHUNK,
                    [
                        (i, doc_id, kbs[owner], c.ordinal, c.text, list(c.headings),
                         c.page_start, c.page_end, c.token_count, "simple")
                        for i, c in zip(ids, chunks[doc["id"]], strict=True)
                    ],
                )  # fmt: skip
                await cursor.executemany(
                    _INSERT_EMBEDDING,
                    [
                        (i, KNOWLEDGE_PROFILE_ID, kbs[owner],
                         _vector(vectors[key("passage", _passage(c))]))
                        for i, c in zip(ids, chunks[doc["id"]], strict=True)
                    ],
                )  # fmt: skip
        await conn.execute("ANALYZE")
    return names


async def test_recall_and_mrr_hold_the_baseline(role_db: RoleDatabase) -> None:  # noqa: F811
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    index, vectors = load_vectors()
    settings = Settings(env="test").model_copy(update={"knowledge_enabled": True})
    assert (index["model"], index["dimensions"]) == (
        settings.knowledge_embedding_model,
        settings.knowledge_embedding_dimensions,
    ), "the committed vectors are not the configured embedding model's"
    owners = {user: hashlib.sha256(user.encode()).hexdigest() for user in dataset["users"]}
    names = await _store(role_db, dataset, vectors, settings.knowledge_chunk_max_tokens, owners)
    cached = _Cached(vectors)
    retriever = Retriever(
        settings,
        lambda: _Connections(role_db.app_dsn),  # type: ignore[arg-type,return-value]
        EmbeddingProvider(
            cached,
            cached,
            dimensions=index["dimensions"],
            locality="hosted",
            batch_size=8,
            max_retries=0,
        ),
    )
    ranks: list[int | None] = []
    for case in dataset["cases"]:
        if case["category"] != "answerable":
            continue
        result = await retriever.search(owners[case["as_user"]], case["question"], k=10)
        located = [
            Located(names[p.doc_id], p.page_start, p.page_end, tuple(p.headings), p.text)
            for p in result.passages
        ]
        ranks.append(first_hit_rank(case, located))

    report = retrieval_report(dataset["version"], ranks)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(report, {"$ref": "#/$defs/retrieval", "$defs": schema["$defs"]})
    if path := os.environ.get("APP_KNOWLEDGE_EVAL_REPORT"):
        Path(path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    metrics = {name: report[name] for name in ("recall_at_5", "mrr")}
    if os.environ.get("APP_KNOWLEDGE_EVAL_WRITE_BASELINE") == "1":
        BASELINE.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert report["answerable_cases"] == 64
    assert not (dropped := below_baseline(metrics, baseline, TOLERANCE)), dropped
