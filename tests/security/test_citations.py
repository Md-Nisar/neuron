"""Server-validated citations (RAG-05.01): only `cite_id`s a knowledge tool returned in the run
survive into the answer, and they resolve to the passage they stand for."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from tests.security.test_knowledge_tools import _CHUNKS, _DOC, _fakes, _results, _run
from tests.security.test_mcp_abuse import _call, _model

from neuron_agent.knowledge import citations
from neuron_agent.observability import metrics

pytestmark = pytest.mark.anyio
__all__ = ["_fakes"]  # the knowledge tools' fakes, autouse here too


def _answer(*cite_ids: str) -> AIMessage:
    return _call("AgentAnswer", answer="From your documents.", confidence=0.9, citations=cite_ids)


@pytest.fixture
def rejected(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    counted: list[int] = []
    monkeypatch.setattr(metrics, "record_citations_rejected", counted.append)
    return counted


async def test_two_valid_citations_are_kept_and_resolve_with_title_and_pages(
    monkeypatch: pytest.MonkeyPatch, rejected: list[int]
) -> None:
    model = _model(monkeypatch, _call("search_knowledge", query="q"), _answer("cite-2", "cite-1"))

    result = await _run(model)

    assert result["answer"].citations == ["cite-2", "cite-1"]
    assert rejected == []
    cited, dropped = citations.validate(result["answer"].citations, _results(model))
    assert dropped == 0
    assert [(c.doc_id, c.chunk_id) for c in cited] == [(_DOC, _CHUNKS[1]), (_DOC, _CHUNKS[0])]
    assert {(c.title, c.page_start, c.page_end, tuple(c.headings)) for c in cited} == {
        ("Title", 1, 2, ("H",))
    }


async def test_a_cite_id_no_tool_returned_is_dropped_and_counted(
    monkeypatch: pytest.MonkeyPatch, rejected: list[int]
) -> None:
    model = _model(
        monkeypatch, _call("search_knowledge", query="q"), _answer("cite-1", "cite-99", "cite-1")
    )

    result = await _run(model)

    assert result["answer"].citations == ["cite-1"]
    assert rejected == [1]


async def test_a_cite_id_copied_from_a_passage_is_dropped(
    monkeypatch: pytest.MonkeyPatch, rejected: list[int]
) -> None:
    model = _model(monkeypatch, _call("search_knowledge", query="quoted"), _answer("a1b2c3d4e5f6"))

    result = await _run(model)

    assert "a1b2c3d4e5f6" in str(_results(model)[0].content)  # the model could see it
    assert result["answer"].citations == []
    assert rejected == [1]


async def test_without_a_knowledge_tool_every_citation_is_dropped(
    monkeypatch: pytest.MonkeyPatch, rejected: list[int]
) -> None:
    model = _model(monkeypatch, _answer("cite-1"))

    result = await _run(model)

    assert result["answer"].citations == []
    assert rejected == [1]


def test_only_successful_knowledge_tool_artifacts_mint_cite_ids() -> None:
    ref: dict[str, Any] = {
        "doc_id": str(uuid.uuid4()),
        "chunk_id": str(uuid.uuid4()),
        "title": "T",
        "headings": [],
        "page_start": None,
        "page_end": None,
    }
    messages = [
        ToolMessage("", tool_call_id="1", name="calculator", artifact={"a": ref}),
        ToolMessage("", tool_call_id="2", name="search_knowledge", artifact={"b": ref}),
        ToolMessage(
            "", tool_call_id="3", name="search_knowledge", artifact={"c": ref}, status="error"
        ),
    ]

    cited, rejected = citations.validate(["a", "b", "c"], messages)

    assert [c.cite_id for c in cited] == ["b"]
    assert rejected == 2
