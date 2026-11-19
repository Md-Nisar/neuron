"""Answers and citations of the live agent on the knowledge corpus (RAG-08.01, part 3).

The corpus is stored as in `test_postgres_knowledge_retrieval.py`, one knowledge base per
dataset user, owned by that user's principal. Every case is then asked through `AgentService`,
the way `/v1/agent` runs it: the configured model, the knowledge tools on Postgres and the
server's citation check. The model's own searches are embedded by the configured provider.

Gates (the backlog's acceptance criteria):
- AC3: at least 90% of answerable cases cite a page or section that holds the answer;
- AC4: every unanswerable case searched and kept no citation (`grounded` false).

Reported, not gated: answers graded against each case's `expected_facts` (correct, partially
correct, incorrect, false refusal, hallucination, CRAG score; dataset 1.3.0), with 95% Wilson
intervals. `APP_KNOWLEDGE_EVAL_TRIALS` (default 1) repeats every case and pools the trials. With
`APP_KNOWLEDGE_EVAL_JUDGE_MODEL` set (a model identifier such as `nvidia:<model>`, ideally from
another family than the answering model), a judge also scores claim-level faithfulness and
citation support (`evaluation_judge`); its verdicts are written out for human labelling, and it
becomes a gate only once it agrees with people (Cohen's kappa of at least 0.6).

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
from neuron_agent.evaluation_judge import JudgeError, Judgement, faithfulness_report, judge_answer
from neuron_agent.knowledge.providers import EmbeddingProvider
from neuron_agent.knowledge.retrieval import Retriever
from neuron_agent.models.factory import create_chat_model
from neuron_agent.retrieval_metrics import (
    MISSING,
    Answer,
    Grade,
    Located,
    answer_report,
    first_hit_rank,
    grade_answer,
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
    contexts: dict[str, list[str]] = {}  # the judge's retrieved context, per answerable case
    for case in dataset["cases"]:
        if case["category"] == "answerable":
            found = await retriever.search(owners[case["as_user"]], case["question"], k=10)
            contexts[case["id"]] = [p.text for p in found.passages]
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

    # Keyed by (trial, case id). None: the agent hit its step limit without answering, a miss
    # rather than an error.
    trials = int(os.environ.get("APP_KNOWLEDGE_EVAL_TRIALS", "1"))
    replies: dict[tuple[int, str], AgentResponse | None] = {}
    errors: list[str] = []
    service = AgentService(settings)
    await service.startup()
    try:
        with throttled_model_calls(RequestThrottle(DEFAULT_MAX_REQUESTS_PER_MINUTE)):
            for trial in range(1, trials + 1):
                for case in dataset["cases"]:
                    if case["category"] not in {"answerable", "unanswerable"}:
                        continue
                    key = (trial, case["id"])
                    try:
                        reply = await service.invoke(
                            AgentRequest(message=case["question"]),
                            principal=principals[case["as_user"]],
                        )
                    except AgentStepLimitError:
                        replies[key] = None
                        continue
                    except Exception as exc:  # an infrastructure error: the run is inconclusive
                        errors.append(f"{trial}/{case['id']}: {type(exc).__name__}")
                        continue
                    assert isinstance(reply, AgentResponse), key
                    replies[key] = reply
    finally:
        await service.shutdown()

    cited_ids = {c.chunk_id for r in replies.values() if r for c in r.citations or ()}
    texts = await _texts(role_db, cited_ids)
    answers: list[Answer] = []
    abstained: dict[tuple[int, str], bool] = {}
    grades: dict[tuple[int, str], Grade] = {}
    cases = {case["id"]: case for case in dataset["cases"]}
    for key, done in replies.items():
        case = cases[key[1]]
        refused = done is None or (done.grounded is False and not done.citations)
        if case["category"] == "answerable":
            cited = [
                Located(names[c.doc_id], c.page_start, c.page_end, tuple(c.headings),
                        texts[c.chunk_id])
                for c in (done.citations or () if done else ())
            ]  # fmt: skip
            answers.append((case, cited))
            grades[key] = grade_answer(case, done.answer if done else "", refused)
        else:
            abstained[key] = done is not None and done.grounded is False

    faithfulness, judged = await _judge(settings, cases, replies, grades, texts, contexts)
    report = retrieval_report(dataset["version"], ranks, answers, list(abstained.values()))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.validate(report, {"$ref": "#/$defs/retrieval", "$defs": schema["$defs"]})
    missed = sorted(
        {case["id"] for case, cited in answers if not any(is_correct(case, c) for c in cited)}
    )
    outcome = {
        "model": settings.default_model,
        "retrieval": report,
        "not_cited_correctly": missed,
        "not_abstained": [f"{t}/{i}" for (t, i), ok in abstained.items() if not ok],
        "step_limit": [f"{t}/{i}" for (t, i), r in replies.items() if r is None],
        "infrastructure_errors": errors,
        "trials": trials,
        "answers": answer_report(list(grades.values()), list(abstained.values())),
        "graded": [
            {"trial": t, "case": i, "question_type": cases[i]["question_type"], "label": g.label}
            for (t, i), g in grades.items()
        ],
        "faithfulness": faithfulness,
        "judged": judged,
    }
    if path := os.environ.get("APP_KNOWLEDGE_EVAL_REPORT"):
        with open(path, "w", encoding="utf-8") as out:
            json.dump(outcome, out, indent=2)
            out.write("\n")
    assert not errors, f"inconclusive, rerun: {errors}"
    assert (report["answerable_cases"], report["unanswerable_cases"]) == (64, 12 * trials)
    jsonschema.validate(outcome["answers"], {"$ref": "#/$defs/answers", "$defs": schema["$defs"]})
    assert report["cited_correctly"] >= CITED_CORRECTLY_GATE, outcome
    assert all(abstained.values()), outcome


async def _judge(
    settings: Settings,
    cases: dict[str, dict[str, object]],
    replies: dict[tuple[int, str], AgentResponse | None],
    grades: dict[tuple[int, str], Grade],
    texts: dict[uuid.UUID, str],
    contexts: dict[str, list[str]],
) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    """Claim-level faithfulness of the answered answerable cases, when
    `APP_KNOWLEDGE_EVAL_JUDGE_MODEL` names a judge; (None, []) otherwise. Returns the report
    section and each answer's verdicts, for human labelling."""
    judge_model = os.environ.get("APP_KNOWLEDGE_EVAL_JUDGE_MODEL")
    if not judge_model:
        return None, []
    model = create_chat_model(settings, judge_model)
    judgements: list[Judgement] = []
    judged: list[dict[str, object]] = []
    judge_errors = 0
    with throttled_model_calls(RequestThrottle(DEFAULT_MAX_REQUESTS_PER_MINUTE)):
        for (trial, case_id), grade in grades.items():
            done = replies[(trial, case_id)]
            if grade.label == MISSING or done is None:
                continue
            cited = [texts[c.chunk_id] for c in done.citations or () if c.chunk_id in texts]
            try:
                judgement = await judge_answer(
                    model, str(cases[case_id]["question"]), done.answer, cited, contexts[case_id]
                )
            except JudgeError:
                judge_errors += 1
                continue
            judgements.append(judgement)
            judged.append(
                {
                    "trial": trial,
                    "case": case_id,
                    "answer": done.answer,
                    "claims": [c.model_dump() for c in judgement.claims],
                }
            )
    return faithfulness_report(judgements, judge_model, judge_errors), judged
