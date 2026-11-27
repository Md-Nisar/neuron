"""The live system on the hard-question set (RAG-13.02), with the stage profile (RAG-14.01).

The set's documents (`tests/fixtures/knowledge/hard/`) are parsed and chunked as ingestion does
and embedded by the configured model, in one knowledge base of their own. Then:

1. Retrieval: every case's question is searched as the knowledge tool searches (hybrid, the
   reranker on), 50 candidates deep. Per category: complete recall@5 and @10 (every required
   source in the top k) and MRR (the first source found). A follow-up is also searched by its
   human-written standalone rewrite.
2. Answers: every case is asked through `AgentService`, as `/v1/agent` runs it, `trials` times
   (`APP_KNOWLEDGE_EVAL_TRIALS`, default 3). A follow-up's thread starts with its earlier turns.
   A short answer (MuSiQue, 2WikiMultihopQA, FRAMES) is graded by `grade_answer` against the
   benchmark's answer and aliases; a long-form one (MTRAG, ClapNQ) is correct when it cites a
   passage that holds a required source. An unanswerable case must abstain.
3. Every failure is classified (`classify_failure`), from the passages the agent's own searches
   returned and from step 1.

Not a gate: the outcome is written to `APP_KNOWLEDGE_EVAL_REPORT` (case ids and metrics, no
text), and the spans of every answer to `APP_KNOWLEDGE_EVAL_SPANS` for
`scripts/knowledge_profile.py`. `APP_KNOWLEDGE_HARD_VECTORS` names a file that keeps the
passage vectors between runs, and `APP_KNOWLEDGE_HARD_CASES` (ids, comma-separated) runs only
those cases. Live and billed (`integration`): run it with `APP_DEFAULT_MODEL`
set and `-o faulthandler_timeout=14400`.
"""

from __future__ import annotations

import gzip
import json
import os
import statistics
import struct
import time
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import anyio
import psycopg
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import SecretStr
from scripts.build_knowledge_eval import key
from scripts.knowledge_profile import dump
from test_postgres_knowledge_api import _Connections
from test_postgres_knowledge_tables import _knowledge_db
from test_postgres_roles import RoleDatabase, role_db, roles  # noqa: F401

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import AgentStepLimitError
from neuron_agent.evaluation import (
    DEFAULT_MAX_REQUESTS_PER_MINUTE,
    RequestThrottle,
    throttled_model_calls,
)
from neuron_agent.knowledge.chunking import chunk_document
from neuron_agent.knowledge.ingest import _INSERT_CHUNK, _INSERT_EMBEDDING, _passage, _vector
from neuron_agent.knowledge.parsing import MARKDOWN, Limits, PlainTextParser, parse_document
from neuron_agent.knowledge.providers import create_embedding_provider
from neuron_agent.knowledge.reranking import create_reranker
from neuron_agent.knowledge.retrieval import MAX_K, Retriever
from neuron_agent.observability import telemetry
from neuron_agent.persistence.migrations import KNOWLEDGE_PROFILE_ID
from neuron_agent.retrieval_metrics import (
    PERFECT,
    Located,
    classify_failure,
    complete_rank,
    first_rank,
    grade_answer,
    holds,
    mean_reciprocal_rank,
    recall_at_k,
    source_ranks,
)
from neuron_agent.schemas.agent import AgentRequest, AgentResponse
from neuron_agent.security.auth import Principal, principal_owner_key
from neuron_agent.services.agent_service import AgentService

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

HARD = Path("tests/fixtures/knowledge/hard")
ISSUER = "https://neuron-eval.invalid"
PERMISSIONS = frozenset(
    {"agent:invoke", "tools:list_knowledge_bases", "tools:search_knowledge",
     "tools:get_document_excerpt"}
)  # fmt: skip
K = 5
# Two calls a search (query embedding, rerank) at 30 calls a minute.
SECONDS_PER_SEARCH = 4.0
LONG_FORM = {"mtrag", "clapnq"}


def _settings(db: RoleDatabase, nvidia_key: str) -> Settings:
    return Settings(
        env="test",
        checkpointer="postgres",
        postgres_dsn=SecretStr(db.app_dsn),
        knowledge_enabled=True,
        knowledge_embedding_provider="nvidia",
        knowledge_reranker_timeout_seconds=15,
        nvidia_api_key=SecretStr(nvidia_key),
        auth_mode="jwt",
        auth_issuer=ISSUER,
        auth_audience="neuron-eval",
        auth_jwks_url=f"{ISSUER}/jwks.json",
        identity_hash_key=SecretStr(uuid.uuid4().hex),
        user_token_budget=10_000_000,  # the most allowed, per hour
    )


async def _chunks(documents: Sequence[dict[str, Any]], settings: Settings) -> dict[str, list[Any]]:
    limits = Limits.from_settings(settings)
    out = {}
    for doc in documents:
        data = f"# {doc['title']}\n\n{doc['text']}".encode()
        parsed = await parse_document(data, MARKDOWN, limits, [PlainTextParser()])
        out[doc["id"]] = chunk_document(parsed, settings.knowledge_chunk_max_tokens)
    return out


async def _vectors(texts: dict[str, str], settings: Settings) -> dict[str, Sequence[float]]:
    """Each passage's vector, from `APP_KNOWLEDGE_HARD_VECTORS` when it holds them."""
    width = settings.knowledge_embedding_dimensions
    path = Path(p) if (p := os.environ.get("APP_KNOWLEDGE_HARD_VECTORS")) else None
    known: dict[str, Sequence[float]] = {}
    if path and path.exists():
        stored = json.loads(gzip.decompress(path.read_bytes()))
        if stored["model"] == settings.knowledge_embedding_model:
            known = {
                k: struct.unpack(f"<{width}e", bytes.fromhex(v)) for k, v in stored["v"].items()
            }
    missing = [k for k in texts if k not in known]
    provider = create_embedding_provider(settings)
    for start in range(0, len(missing), 64):
        batch = missing[start : start + 64]
        for k, vector in zip(
            batch, await provider.embed_documents([texts[k] for k in batch]), strict=True
        ):
            known[k] = tuple(vector)
    if path and missing:
        body = {k: struct.pack(f"<{width}e", *v).hex() for k, v in known.items()}
        model = settings.knowledge_embedding_model
        path.write_bytes(gzip.compress(json.dumps({"model": model, "v": body}).encode()))
    return known


async def _store(
    db: RoleDatabase, documents: Sequence[dict[str, Any]], owner: str, settings: Settings
) -> tuple[uuid.UUID, dict[uuid.UUID, str], dict[uuid.UUID, str]]:
    """The documents in one knowledge base of `owner`'s; returns it, doc_id -> fixture id and
    chunk_id -> text."""
    chunks = await _chunks(documents, settings)
    texts = {key("passage", _passage(c)): _passage(c) for cs in chunks.values() for c in cs}
    vectors = await _vectors(texts, settings)
    await _knowledge_db(db)
    kb, names, chunk_texts = uuid.uuid4(), {}, {}
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO knowledge.bases (kb_id, owner_key, name, profile_id)"
            " VALUES (%s, %s, 'hard', %s)",
            (kb, owner, KNOWLEDGE_PROFILE_ID),
        )
        await conn.execute(
            "INSERT INTO knowledge.grants (kb_id, subject_type, subject, access, granted_by)"
            " VALUES (%s, 'owner', %s, 'admin', %s)",
            (kb, owner, owner),
        )
        for doc in documents:
            doc_id = uuid.uuid4()
            names[doc_id] = doc["id"]
            body = doc["text"].encode()
            await conn.execute(
                "INSERT INTO knowledge.documents (doc_id, kb_id, uploaded_by, title, mime_type,"
                " size_bytes, sha256, blob_key, status) VALUES (%s, %s, %s, %s, %s, %s,"
                " encode(sha256(%s), 'hex'), 'k', 'ready')",
                (doc_id, kb, owner, doc["title"], MARKDOWN, len(body), body),
            )
            ids = [uuid.uuid4() for _ in chunks[doc["id"]]]
            chunk_texts.update({i: c.text for i, c in zip(ids, chunks[doc["id"]], strict=True)})
            async with conn.cursor() as cursor:
                await cursor.executemany(
                    _INSERT_CHUNK,
                    [
                        (i, doc_id, kb, c.ordinal, c.text, list(c.headings),
                         c.page_start, c.page_end, c.token_count, "simple")
                        for i, c in zip(ids, chunks[doc["id"]], strict=True)
                    ],
                )  # fmt: skip
                await cursor.executemany(
                    _INSERT_EMBEDDING,
                    [
                        (i, KNOWLEDGE_PROFILE_ID, kb,
                         _vector(vectors[key("passage", _passage(c))]))
                        for i, c in zip(ids, chunks[doc["id"]], strict=True)
                    ],
                )  # fmt: skip
        await conn.execute("ANALYZE")
    return kb, names, chunk_texts


async def _search(retriever: Retriever, owner: str, query: str) -> tuple[list[Any], bool]:
    """Up to `MAX_K` passages, retried once if the embedding or the reranker fell back."""
    for _ in range(2):
        started = time.monotonic()
        result = await retriever.search(owner, query, k=MAX_K)
        await anyio.sleep(max(0.0, SECONDS_PER_SEARCH - (time.monotonic() - started)))
        if result.reranked and result.path != "none":
            break
    return result.passages, result.reranked and result.path != "none"


def _expected_facts(case: dict[str, Any]) -> list[dict[str, Any]]:
    answer = case["answer"]
    return [{"vital": True, "any": [answer["text"], *answer["aliases"]]}]


async def _ask(
    service: AgentService, principal: Principal, owner: str, case: dict[str, Any]
) -> AgentResponse | None:
    """The reply, or None at the step limit."""
    thread_id: str | None = None
    if turns := case.get("turns"):
        thread_id = str(uuid.uuid4())
        history = [
            HumanMessage(t["text"]) if t["role"] == "user" else AIMessage(t["text"]) for t in turns
        ]
        await service.graph.aupdate_state(
            {"configurable": {"thread_id": thread_id}},
            {"messages": history, "owner_key": owner},
            as_node="agent",
        )
    try:
        reply = await service.invoke(
            AgentRequest(message=case["question"], thread_id=thread_id), principal=principal
        )
    except AgentStepLimitError:
        return None
    assert isinstance(reply, AgentResponse)
    return reply


def _rate(values: Sequence[bool]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


async def test_the_hard_set_baseline(
    live_provider: str,
    live_nvidia_key: str,
    role_db: RoleDatabase,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = json.loads((HARD / "cases.json").read_text(encoding="utf-8"))
    documents = json.loads(gzip.decompress((HARD / dataset["documents_file"]).read_bytes()))
    settings = _settings(role_db, str(live_nvidia_key))
    assert settings.knowledge_reranker_effective == "nvidia"
    assert settings.identity_hash_key is not None
    principal = Principal(
        ISSUER, "hard", PERMISSIONS, None, datetime.now(UTC) + timedelta(hours=12)
    )
    owner = principal_owner_key(principal, settings.identity_hash_key.get_secret_value())
    _, names, chunk_texts = await _store(role_db, documents["documents"], owner, settings)
    retriever = Retriever(
        settings,
        lambda: _Connections(role_db.app_dsn),  # type: ignore[arg-type,return-value]
        create_embedding_provider(settings),
        create_reranker(settings),
    )
    cases = dataset["cases"]
    if only := os.environ.get("APP_KNOWLEDGE_HARD_CASES"):  # a comma-separated subset, to debug
        cases = [c for c in cases if c["id"] in only.split(",")]

    # 1. Retrieval.
    ranks: dict[str, list[int | None]] = {}
    standalone: dict[str, list[int | None]] = {}
    degraded: list[str] = []
    for case in cases:
        if case["category"] == "unanswerable":
            continue
        for query, into in [(case["question"], ranks)] + (
            [(case["standalone"], standalone)] if "standalone" in case else []
        ):
            passages, ok = await _search(retriever, owner, query)
            if not ok:
                degraded.append(case["id"])
            located = [Located(names[p.doc_id], text=p.text) for p in passages]
            into[case["id"]] = source_ranks(case["required_sources"], located)

    # 2. Answers, with every span captured.
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(telemetry, "tracer", lambda: provider.get_tracer(__name__))
    # Every passage the agent's own searches return, for the case being asked.
    seen: list[Any] = []
    search = Retriever.search

    async def recorded(self: Retriever, *args: Any, **kwargs: Any) -> Any:
        result = await search(self, *args, **kwargs)
        seen.extend(result.passages)
        return result

    monkeypatch.setattr(Retriever, "search", recorded)
    trials = int(os.environ.get("APP_KNOWLEDGE_EVAL_TRIALS", "3"))
    runs: list[dict[str, Any]] = []
    errors: list[str] = []
    service = AgentService(settings)
    await service.startup()
    try:
        with throttled_model_calls(RequestThrottle(DEFAULT_MAX_REQUESTS_PER_MINUTE)):
            for trial in range(1, trials + 1):
                for case in cases:
                    started = time.monotonic()
                    seen.clear()
                    try:
                        reply = await _ask(service, principal, owner, case)
                    except Exception as exc:  # an infrastructure error: recorded, not scored
                        errors.append(f"{trial}/{case['id']}: {type(exc).__name__}")
                        continue
                    runs.append(_score(case, trial, reply, seen, names, chunk_texts, ranks,
                                       standalone, time.monotonic() - started))  # fmt: skip
    finally:
        await service.shutdown()
    if path := os.environ.get("APP_KNOWLEDGE_EVAL_SPANS"):
        dump(exporter.get_finished_spans(), Path(path))

    report = _report(dataset, cases, ranks, standalone, runs, settings, trials)
    report |= {"degraded_searches": sorted(set(degraded)), "infrastructure_errors": errors}
    if path := os.environ.get("APP_KNOWLEDGE_EVAL_REPORT"):
        Path(path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    assert len(runs) + len(errors) == trials * len(cases)


def _score(
    case: dict[str, Any],
    trial: int,
    reply: AgentResponse | None,
    found: list[Any],
    names: dict[uuid.UUID, str],
    chunk_texts: dict[uuid.UUID, str],
    ranks: dict[str, list[int | None]],
    standalone: dict[str, list[int | None]],
    seconds: float,
) -> dict[str, Any]:
    """One run's verdict: ids, labels and counts only."""
    abstained = reply is None or (reply.grounded is False and not reply.citations)
    run: dict[str, Any] = {
        "trial": trial,
        "case": case["id"],
        "category": case["category"],
        "abstained": abstained,
        "step_limit": reply is None,
        "seconds": round(seconds, 1),
    }
    if case["category"] == "unanswerable":
        return run | {"correct": abstained}
    seen = [Located(names[p.doc_id], text=p.text) for p in found]
    sources = case["required_sources"]
    saw_all = all(any(holds(s, p) for p in seen) for s in sources)
    cited = [
        Located(names[c.doc_id], text=chunk_texts.get(c.chunk_id, "") if c.chunk_id else "")
        for c in (reply.citations or () if reply else ())
    ]
    cites_source = any(holds(s, c) for s in sources for c in cited)
    if case["benchmark"]["source"] in LONG_FORM:
        correct = not abstained and cites_source
    else:
        graded = {**case, "expected_facts": _expected_facts(case)}
        correct = grade_answer(graded, reply.answer if reply else "", abstained).label == PERFECT
    run |= {"correct": correct, "saw_all_sources": saw_all, "cites_a_source": cites_source}
    if not correct:
        run["failure"] = classify_failure(
            abstained=abstained,
            seen=saw_all,
            complete=complete_rank(ranks[case["id"]]),
            k=K,
            standalone_complete=complete_rank(standalone[case["id"]])
            if case["id"] in standalone
            else None,
        )
    return run


def _report(
    dataset: dict[str, Any],
    cases: list[dict[str, Any]],
    ranks: dict[str, list[int | None]],
    standalone: dict[str, list[int | None]],
    runs: list[dict[str, Any]],
    settings: Settings,
    trials: int,
) -> dict[str, Any]:
    categories = sorted({c["category"] for c in cases})
    per: dict[str, Any] = {}
    for category in categories:
        ids = [c["id"] for c in cases if c["category"] == category]
        mine = [r for r in runs if r["category"] == category]
        failures: dict[str, int] = defaultdict(int)
        for r in mine:
            if "failure" in r:
                failures[r["failure"]] += 1
        entry: dict[str, Any] = {
            "cases": len(ids),
            "runs": len(mine),
            "correct": _rate([r["correct"] for r in mine]),
            "abstained": _rate([r["abstained"] for r in mine]),
            "failures": dict(sorted(failures.items())),
            "seconds_p50": round(statistics.median(r["seconds"] for r in mine), 1)
            if mine
            else None,
        }
        if category != "unanswerable":
            complete = [complete_rank(ranks[i]) for i in ids]
            first = [first_rank(ranks[i]) for i in ids]
            entry |= {
                "complete_recall_at_5": _rate([r is not None and r <= 5 for r in complete]),
                "complete_recall_at_10": _rate([r is not None and r <= 10 for r in complete]),
                "mrr": round(mean_reciprocal_rank(first) or 0.0, 3),
                "recall_at_5_any_source": recall_at_k(first),
                "saw_all_sources": _rate([r["saw_all_sources"] for r in mine]),
            }
            if category == "follow_up":
                rewritten = [complete_rank(standalone[i]) for i in ids]
                entry["complete_recall_at_5_standalone"] = _rate(
                    [r is not None and r <= 5 for r in rewritten]
                )
        per[category] = entry
    return {
        "dataset_version": dataset["version"],
        "model": settings.default_model,
        "embedding_model": settings.knowledge_embedding_model,
        "reranker_model": settings.knowledge_reranker_model,
        "trials": trials,
        "k": K,
        "categories": per,
        "runs": runs,
    }
