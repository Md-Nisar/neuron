"""The negative feedback report joins a thumbs-down to its run's citations (RAG-09.07)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import anyio
import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.persistence import cli
from neuron_agent.persistence.feedback_report import negative_feedback_report
from neuron_agent.schemas.agent import AgentRequest
from neuron_agent.services.agent_service import AgentService

pytestmark = [pytest.mark.integration, pytest.mark.postgres, pytest.mark.anyio]

_TEXT = "lighthouse-private-passage"


def _citation(chunk: uuid.UUID, doc: uuid.UUID) -> dict[str, Any]:
    return {
        "cite_id": "c1",
        "doc_id": str(doc),
        "chunk_id": str(chunk),
        "title": f"{_TEXT} title",
        "headings": [f"{_TEXT} heading"],
        "page_start": 1,
        "page_end": 1,
    }


async def _answer(service: AgentService, user: str, citations: list[dict[str, Any]] | None):
    """A real run of the fake model, then the citations the graph would stamp on it."""
    response = await service.invoke(AgentRequest(message=f"{_TEXT} question", user_id=user))
    config: dict[str, Any] = {"configurable": {"thread_id": response.thread_id}}
    answer = (await service.graph.aget_state(config)).values["messages"][-1]
    if citations is not None:
        stamped = {**answer.additional_kwargs, "citations": citations}
        await service.graph.aupdate_state(
            config,
            {
                "messages": [
                    AIMessage(id=answer.id, content=answer.content, additional_kwargs=stamped)
                ]
            },
        )
    assert response.run_id is not None
    return response.thread_id, response.run_id


async def test_a_thumbs_down_lists_the_cited_chunks_and_the_run_and_no_text(
    database: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = Settings(env="test", checkpointer="postgres", postgres_dsn=SecretStr(database))
    service = AgentService(settings)
    await service.startup()
    chunks = [uuid.uuid4(), uuid.uuid4()]
    doc = uuid.uuid4()
    try:
        cited = await _answer(service, "alice", [_citation(c, doc) for c in chunks])
        liked = await _answer(service, "alice", [_citation(uuid.uuid4(), doc)])
        uncited = await _answer(service, "bob", None)
        await service.submit_feedback(*cited, -1, "inaccurate", "alice")
        await service.submit_feedback(*liked, 1, "helpful", "alice")
        await service.submit_feedback(*uncited, -1, None, "bob")
        report = await negative_feedback_report(service._persistence)
    finally:
        await service.shutdown()

    assert (report["negative_runs"], report["answer_missing"]) == (2, 0)
    [run] = report["cited_runs"]
    assert (run["run_id"], run["thread_id"], run["reason"]) == (cited[1], cited[0], "inaccurate")
    assert run["chunks"] == [{"chunk_id": str(c), "doc_id": str(doc)} for c in chunks]

    # The operator command prints the same report, and nothing in it is query or chunk text.
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_CHECKPOINTER", "postgres")
    monkeypatch.setenv("APP_POSTGRES_DSN", database)
    cli.get_settings.cache_clear()
    try:
        await anyio.to_thread.run_sync(cli.main, ["feedback-report"])  # it runs its own loop
    finally:
        cli.get_settings.cache_clear()
    printed = capsys.readouterr().out
    assert (
        json.loads(printed[printed.index('{\n  "negative_runs"') :])["cited_runs"]
        == report["cited_runs"]
    )
    assert _TEXT not in printed
    assert "alice" not in printed
