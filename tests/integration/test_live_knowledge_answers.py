"""Answers and citations of the live agent on the knowledge corpus (RAG-08.01, part 3).

The corpus is stored as in `test_postgres_knowledge_retrieval.py`, one knowledge base per
dataset user, owned by that user's principal. Every case is then asked through `AgentService`,
the way `/v1/agent` runs it: the configured model, the knowledge tools on Postgres and the
server's citation check. The model's own searches are embedded by the configured provider.

Gates (the backlog's acceptance criteria):
- AC3: at least 90% of answerable cases cite a page or section that holds the answer;
- AC4: every unanswerable case searched and kept no citation (`grounded` false).

Live and billed, so marked `integration` (`make test-integration`); it skips without the model's
key or `APP_TEST_POSTGRES_DSN`. Run it with `APP_DEFAULT_MODEL` set, for example
`nvidia:nvidia/nemotron-3-ultra-550b-a55b`, and lift pytest's 120-second per-test limit with
`-o faulthandler_timeout=7200`: the run takes far longer. Model calls are throttled to the eval
CLI's 30 per minute. An answer cut off by the agent's step limit is a miss; any other error makes
the run inconclusive. With `APP_KNOWLEDGE_EVAL_REPORT` set, the outcome is written to that path:
the report's `retrieval` section, with all four metrics, and the cases that missed.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import jsonschema
import psycopg
import pytest
from pydantic import SecretStr
from scripts.build_knowledge_eval import DATASET, load_vectors
from test_postgres_knowledge_api import _Connections
from test_postgres_knowledge_retrieval import SCHEMA, _Cached, _store
from test_postgres_roles import RoleDatabase, role_db, roles  # noqa: F401

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import AgentStepLimitError
from neuron_agent.evaluation import (
    DEFAULT_MAX_REQUESTS_PER_MINUTE,
    RequestThrottle,
    throttled_model_calls,
)
from neuron_agent.knowledge.providers import EmbeddingProvider
from neuron_agent.knowledge.retrieval import Retriever
from neuron_agent.retrieval_metrics import (
    Answer,
    Located,
    first_hit_rank,
    is_correct,
    retrieval_report,
)
from neuron_agent.schemas.agent import AgentRequest, AgentResponse
from neuron_agent.security.auth import Principal, principal_owner_key
from neuron_agent.services.agent_service import AgentService

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

ISSUER = "https://neuron-eval.invalid"
PERMISSIONS = frozenset(
    {"agent:invoke", "tools:list_knowledge_bases", "tools:search_knowledge",
     "tools:get_document_excerpt"}
)  # fmt: skip
CITED_CORRECTLY_GATE = 0.9


def _settings(db: RoleDatabase) -> Settings:
    return Settings(
        env="test",
        checkpointer="postgres",
        postgres_dsn=SecretStr(db.app_dsn),
        knowledge_enabled=True,
        auth_mode="jwt",
        auth_issuer=ISSUER,
        auth_audience="neuron-eval",
        auth_jwks_url=f"{ISSUER}/jwks.json",
        identity_hash_key=SecretStr(uuid.uuid4().hex),
        # 84 runs as two users would pass the hourly per-user budget.
        user_token_budget=10_000_000,
    )


def _principal(user: str) -> Principal:
    return Principal(ISSUER, user, PERMISSIONS, None, datetime.now(UTC) + timedelta(hours=4))


async def _texts(db: RoleDatabase, chunk_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn) as conn:
        cursor = await conn.execute(
            "SELECT chunk_id, text FROM knowledge.chunks WHERE chunk_id = ANY(%s)",
            (list(chunk_ids),),
        )
        return dict(await cursor.fetchall())


async def test_answers_cite_the_right_source_and_abstain_without_one(
    live_provider: str,
    role_db: RoleDatabase,  # noqa: F811
) -> None:
    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    index, vectors = load_vectors()
    settings = _settings(role_db)
    assert settings.identity_hash_key is not None
    principals = {user: _principal(user) for user in dataset["users"]}
    owners = {
        user: principal_owner_key(p, settings.identity_hash_key.get_secret_value())
        for user, p in principals.items()
    }
    names = await _store(role_db, dataset, vectors, settings.knowledge_chunk_max_tokens, owners)

    # Search ranks, as in part 2, so the report holds all four metrics.
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
        if case["category"] == "answerable":
            found = await retriever.search(owners[case["as_user"]], case["question"], k=10)
            ranks.append(
                first_hit_rank(
                    case,
                    [
                        Located(
                            names[p.doc_id], p.page_start, p.page_end, tuple(p.headings), p.text
                        )
                        for p in found.passages
                    ],
                )
            )

    # None: the agent hit its step limit without answering, a miss rather than an error.
    replies: dict[str, AgentResponse | None] = {}
    errors: list[str] = []
    service = AgentService(settings)
    await service.startup()
    try:
        with throttled_model_calls(RequestThrottle(DEFAULT_MAX_REQUESTS_PER_MINUTE)):
            for case in dataset["cases"]:
                if case["category"] not in {"answerable", "unanswerable"}:
                    continue
                try:
                    reply = await service.invoke(
                        AgentRequest(message=case["question"]),
                        principal=principals[case["as_user"]],
                    )
                except AgentStepLimitError:
                    replies[case["id"]] = None
                    continue
                except Exception as exc:  # an infrastructure error: the run is inconclusive
                    errors.append(f"{case['id']}: {type(exc).__name__}")
                    continue
                assert isinstance(reply, AgentResponse), case["id"]
                replies[case["id"]] = reply
    finally:
        await service.shutdown()

    cited_ids = {c.chunk_id for r in replies.values() if r for c in r.citations or ()}
    texts = await _texts(role_db, cited_ids)
    answers: list[Answer] = []
    abstained: dict[str, bool] = {}
    cases = {case["id"]: case for case in dataset["cases"]}
    for case_id, done in replies.items():
        case = cases[case_id]
        if case["category"] == "answerable":
            cited = [
                Located(names[c.doc_id], c.page_start, c.page_end, tuple(c.headings),
                        texts[c.chunk_id])
                for c in (done.citations or () if done else ())
            ]  # fmt: skip
            answers.append((case, cited))
        else:
            abstained[case_id] = done is not None and done.grounded is False

    report = retrieval_report(dataset["version"], ranks, answers, list(abstained.values()))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(report, {"$ref": "#/$defs/retrieval", "$defs": schema["$defs"]})
    missed = [case["id"] for case, cited in answers if not any(is_correct(case, c) for c in cited)]
    outcome = {
        "model": settings.default_model,
        "retrieval": report,
        "not_cited_correctly": missed,
        "not_abstained": [i for i, ok in abstained.items() if not ok],
        "step_limit": [i for i, r in replies.items() if r is None],
        "infrastructure_errors": errors,
    }
    if path := os.environ.get("APP_KNOWLEDGE_EVAL_REPORT"):
        with open(path, "w", encoding="utf-8") as out:
            json.dump(outcome, out, indent=2)
            out.write("\n")
    assert not errors, f"inconclusive, rerun: {errors}"
    assert (report["answerable_cases"], report["unanswerable_cases"]) == (64, 12)
    assert report["cited_correctly"] >= CITED_CORRECTLY_GATE, outcome
    assert all(abstained.values()), outcome
