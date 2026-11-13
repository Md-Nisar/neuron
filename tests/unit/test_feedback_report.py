"""The negative feedback report's citation join (RAG-09.07); the database half is in
`tests/integration/test_postgres_feedback_report.py`."""

from __future__ import annotations

import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from neuron_agent.persistence import cli
from neuron_agent.persistence.feedback_report import cited_chunks

_CHUNK, _DOC = uuid.uuid4(), uuid.uuid4()
_CITATION = {
    "cite_id": "c1",
    "doc_id": str(_DOC),
    "chunk_id": str(_CHUNK),
    "title": "passage title",
    "headings": ["heading"],
    "page_start": None,
    "page_end": None,
}


def _answer(run_id: str, citations: object) -> AIMessage:
    return AIMessage(content="answer", additional_kwargs={"run_id": run_id, "citations": citations})


def test_only_the_rated_runs_ids_are_kept() -> None:
    messages = [
        HumanMessage(content="q", additional_kwargs={"run_id": "r1"}),
        _answer("r0", [{**_CITATION, "chunk_id": str(uuid.uuid4())}]),
        _answer("r1", [_CITATION, {"cite_id": "broken"}]),
    ]

    assert cited_chunks(messages, "r1") == [{"chunk_id": str(_CHUNK), "doc_id": str(_DOC)}]


def test_an_answer_without_citations_and_a_missing_run_differ() -> None:
    assert cited_chunks([_answer("r1", None)], "r1") == []
    assert cited_chunks([_answer("r1", [_CITATION])], "r2") is None
    assert cited_chunks(None, "r1") is None


def test_the_command_needs_the_postgres_checkpointer(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("APP_CHECKPOINTER", "memory")
    cli.get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit):
            cli.main(["feedback-report"])
    finally:
        cli.get_settings.cache_clear()
    assert "feedback-report failed: feedback-report needs APP_CHECKPOINTER=postgres" in (
        capsys.readouterr().err
    )
