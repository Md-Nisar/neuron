"""Questions about an uploaded table, asked of the live agent (RAG-11.01).

`tests/fixtures/knowledge/table_cases.json` holds 6 questions that need every row of a
1,500-row orders table (a total, a count, an average, the largest group) and 2 that need one
row. The table is stored as ingestion stores a spreadsheet today: one `table` block of
`a | b | c` lines, chunked by Neuron's chunker and embedded by the configured provider. Each
question is then asked through `AgentService` with the tools the run has.

An answer is correct when its text contains one of the case's answers; the gate is every case.
Search returns at most 10 of the table's 69 chunks, so the aggregate cases fail until
`query_table` exists (baseline in the tracker). Live and billed: run it like
`test_live_knowledge_answers.py`; `APP_KNOWLEDGE_EVAL_REPORT` names a file for the report.
"""

from __future__ import annotations

import csv
import io
import json
import os
import uuid
from pathlib import Path

import psycopg
import pytest
from scripts.build_table_eval import build
from test_live_knowledge_answers import _principal, _settings
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
from neuron_agent.knowledge.parsing import XLSX, Block, ParsedDocument
from neuron_agent.knowledge.providers import create_embedding_provider
from neuron_agent.persistence.migrations import KNOWLEDGE_PROFILE_ID
from neuron_agent.schemas.agent import AgentRequest, AgentResponse
from neuron_agent.security.auth import principal_owner_key
from neuron_agent.services.agent_service import AgentService

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

FIXTURES = Path("tests/fixtures/knowledge")
USER = "table-user"


def _as_today(fixture: dict[str, object]) -> ParsedDocument:
    """The table as docling-serve's table block renders it: one row a line, cells joined by
    ` | ` (`docling_serve._table_block`)."""
    text, _ = build()
    lines = [" | ".join(row) for row in csv.reader(io.StringIO(text))]
    return ParsedDocument(
        parser_version="table-eval",
        blocks=(
            Block(kind="heading", text=str(fixture["title"]), level=1),
            Block(kind="table", text="\n".join(lines)),
        ),
    )


async def _store(
    db: RoleDatabase, owner: str, fixture: dict[str, object], settings: Settings
) -> int:
    chunks = chunk_document(_as_today(fixture), settings.knowledge_chunk_max_tokens)
    provider = create_embedding_provider(settings)
    vectors = await provider.embed_documents([_passage(c) for c in chunks])
    await _knowledge_db(db)
    kb, doc = uuid.uuid4(), uuid.uuid4()
    async with await psycopg.AsyncConnection.connect(db.migrator_dsn, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO knowledge.bases (kb_id, owner_key, name, profile_id)"
            " VALUES (%s, %s, 'Sales', %s)",
            (kb, owner, KNOWLEDGE_PROFILE_ID),
        )
        await conn.execute(
            "INSERT INTO knowledge.grants (kb_id, subject_type, subject, access, granted_by)"
            " VALUES (%s, 'owner', %s, 'admin', %s)",
            (kb, owner, owner),
        )
        await conn.execute(
            "INSERT INTO knowledge.documents (doc_id, kb_id, uploaded_by, title, mime_type,"
            " size_bytes, sha256, blob_key, status) VALUES (%s, %s, %s, %s, %s, 1, %s, 'k',"
            " 'ready')",
            (doc, kb, owner, fixture["title"], XLSX, "0" * 64),
        )
        ids = [uuid.uuid4() for _ in chunks]
        async with conn.cursor() as cursor:
            await cursor.executemany(
                _INSERT_CHUNK,
                [(i, doc, kb, c.ordinal, c.text, list(c.headings), c.page_start, c.page_end,
                  c.token_count, "simple") for i, c in zip(ids, chunks, strict=True)],
            )  # fmt: skip
            await cursor.executemany(
                _INSERT_EMBEDDING,
                [(i, KNOWLEDGE_PROFILE_ID, kb, _vector(v)) for i, v in zip(ids, vectors,
                 strict=True)],
            )  # fmt: skip
        await conn.execute("ANALYZE")
    return len(chunks)


def _correct(answer: str, expected: list[str]) -> bool:
    return any(value.lower() in answer.lower() for value in expected)


async def test_questions_that_need_every_row_are_answered(
    live_provider: str,
    role_db: RoleDatabase,  # noqa: F811
) -> None:
    fixture = json.loads((FIXTURES / "table_cases.json").read_text(encoding="utf-8"))
    settings = _settings(role_db)
    assert settings.identity_hash_key is not None
    principal = _principal(USER)
    owner = principal_owner_key(principal, settings.identity_hash_key.get_secret_value())
    chunk_count = await _store(role_db, owner, fixture, settings)

    outcomes: list[dict[str, object]] = []
    errors: list[str] = []
    service = AgentService(settings)
    await service.startup()
    try:
        with throttled_model_calls(RequestThrottle(DEFAULT_MAX_REQUESTS_PER_MINUTE)):
            for case in fixture["cases"]:
                try:
                    reply = await service.invoke(
                        AgentRequest(message=case["question"]), principal=principal
                    )
                except AgentStepLimitError:
                    answer = ""
                except Exception as exc:  # an infrastructure error: the run is inconclusive
                    errors.append(f"{case['id']}: {type(exc).__name__}")
                    continue
                else:
                    assert isinstance(reply, AgentResponse), case["id"]
                    answer = reply.answer
                outcomes.append(
                    {"id": case["id"], "kind": case["kind"], "expected": case["answers"],
                     "answer": answer, "correct": _correct(answer, case["answers"])}
                )  # fmt: skip
    finally:
        await service.shutdown()

    report = {
        "model": settings.default_model,
        "dataset": fixture["version"],
        "chunks": chunk_count,
        "correct": {kind: f"{sum(o['correct'] for o in outcomes if o['kind'] == kind)} of"
                    f" {sum(o['kind'] == kind for o in outcomes)}"
                    for kind in ("aggregate", "lookup")},
        "cases": outcomes,
        "infrastructure_errors": errors,
    }  # fmt: skip
    if path := os.environ.get("APP_KNOWLEDGE_EVAL_REPORT"):
        with open(path, "w", encoding="utf-8") as out:
            json.dump(report, out, indent=2)
            out.write("\n")
    assert not errors, f"inconclusive, rerun: {errors}"
    assert all(o["correct"] for o in outcomes), report
