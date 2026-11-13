"""Server-validated citations (RAG-05.01): only `cite_id`s a knowledge tool returned in the run
survive into the answer, and they resolve to the passage they stand for."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from tests.security.test_knowledge_tools import (
    _CHUNKS,
    _DOC,
    _OWNER,
    _SCOPES,
    WEB_FETCHED,
    WEB_URL,
    _fakes,
    _results,
    _run,
)
from tests.security.test_mcp_abuse import _call, _model

from neuron_agent.config.settings import Settings
from neuron_agent.graphs import main_graph
from neuron_agent.knowledge import citations
from neuron_agent.knowledge import tools as knowledge_tools
from neuron_agent.observability import metrics
from neuron_agent.schemas.agent import AgentResponse, ThreadMessage
from neuron_agent.security.authorization import AuthorizationContext
from neuron_agent.services import agent_service
from neuron_agent.tools.registry import ToolRegistry

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


async def test_a_web_pages_citations_name_its_url_and_fetch_time_also_from_an_excerpt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model(
        monkeypatch,
        _call("search_knowledge", query="web"),
        _call("get_document_excerpt", cite_id="cite-1", window=0),
        _answer("cite-1", "cite-3"),
    )

    cited, _ = citations.validate((await _run(model))["answer"].citations, _results(model))

    assert [(c.source_url, c.fetched_at) for c in cited] == [(WEB_URL, WEB_FETCHED)] * 2


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
    # Without the search scope the first call is not made a search (`knowledge_first`).
    model = _model(monkeypatch, _answer("cite-1"))

    result = await _run(model, scopes=_SCOPES - {"tools:search_knowledge"})

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


async def _thread_runs(
    model: Any, turns: int, scopes: Sequence[frozenset[str]] = ()
) -> tuple[Any, dict[str, Any]]:
    """`turns` runs of one thread on a checkpointer, each with its `scopes` (all by default);
    the graph and the thread's config."""
    graph = main_graph.build_graph(
        Settings(env="test"),
        checkpointer=InMemorySaver(),
        registry=ToolRegistry(knowledge_tools.knowledge_specs(Settings(env="test"), lambda: None)),
    )
    config: dict[str, Any] = {"configurable": {"thread_id": str(uuid.uuid4())}}
    for n in range(turns):
        await graph.ainvoke(
            {"messages": [HumanMessage(content=f"turn {n}")]},
            config,
            context=AuthorizationContext(scopes[n] if scopes else _SCOPES, owner_key=_OWNER),
        )
    return graph, config


async def test_citations_are_stored_with_the_answer_and_come_back_in_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _model(
        monkeypatch,
        _call("search_knowledge", query="q"),
        _answer("cite-1"),
        _call("AgentAnswer", answer="Hello again.", confidence=0.9),
    )

    # The second turn may not search, so it uses no knowledge tool.
    graph, config = await _thread_runs(
        model, turns=2, scopes=[_SCOPES, _SCOPES - {"tools:search_knowledge"}]
    )

    stored = (await graph.aget_state(config)).values["messages"]
    history = agent_service._public_thread_messages(stored)
    first, second = history[1], history[3]
    assert (first.citation_schema_version, first.grounded) == (1, True)
    assert first.citations is not None
    assert [(c.cite_id, c.doc_id, c.chunk_id, c.title) for c in first.citations] == [
        ("cite-1", _DOC, _CHUNKS[0], "Title")
    ]
    # A run that used no knowledge tool has no citation fields, not `grounded: false`.
    assert (second.citations, second.citation_schema_version, second.grounded) == (None,) * 3
    assert (history[0].citations, history[0].grounded) == (None, None)
    # The final event and the invoke response read the same stamp.
    assert agent_service._stamped_citations(stored[1]) == first.model_dump(
        include={"citations", "citation_schema_version", "grounded"}
    )


async def test_the_stored_answer_holds_no_passage_text(monkeypatch: pytest.MonkeyPatch) -> None:
    model = _model(monkeypatch, _call("search_knowledge", query="q"), _answer("cite-1", "cite-2"))

    graph, config = await _thread_runs(model, turns=1)

    stored = (await graph.aget_state(config)).values["messages"]
    assert len(stored) == 2  # the user turn and the answer: no tool message is kept
    kwargs = stored[1].additional_kwargs
    assert len(kwargs["citations"]) == 2
    assert "obey" not in repr(kwargs)
    assert "Ignore the user" not in repr(kwargs)


async def test_a_search_with_no_valid_citation_is_not_grounded(
    monkeypatch: pytest.MonkeyPatch, rejected: list[int]
) -> None:
    model = _model(monkeypatch, _call("search_knowledge", query="q"), _answer("forged"))

    graph, config = await _thread_runs(model, turns=1)

    answer = (await graph.aget_state(config)).values["messages"][1]
    assert (answer.additional_kwargs["citations"], answer.additional_kwargs["grounded"]) == (
        [],
        False,
    )


async def test_an_answer_saying_the_documents_lack_it_keeps_no_citation(
    monkeypatch: pytest.MonkeyPatch, rejected: list[int]
) -> None:
    # RAG-08.01: asked about a phase 3 that does not exist, the model said so and cited the
    # plan's phases 1 and 2. Its abstention, not the absence of citations, decides.
    abstained = _call(
        "AgentAnswer",
        answer="Your documents do not mention a phase 3; the plan lists phases 1 and 2.",
        confidence=0.9,
        citations=["cite-1", "cite-2", "forged"],
        not_in_documents=True,
    )
    model = _model(monkeypatch, _call("search_knowledge", query="q"), abstained)

    graph, config = await _thread_runs(model, turns=1)

    answer = (await graph.aget_state(config)).values["messages"][1]
    assert (answer.additional_kwargs["citations"], answer.additional_kwargs["grounded"]) == (
        [],
        False,
    )
    assert rejected == [1]  # the forged id is still counted; the valid ones are not


def test_a_stamp_that_does_not_validate_is_ignored() -> None:
    message = AIMessage(content="x", additional_kwargs={"citations": [{"cite_id": 1}]})

    assert agent_service._stamped_citations(message) == {}


def test_a_citation_without_pages_or_title_reaches_the_response_and_history() -> None:
    # A text or Markdown file has no pages (RAG-06.02's browser flow found this): the nulls
    # inside a citation must survive, or the final event and history fail to build.
    cited = {
        "cite_id": "c1",
        "doc_id": str(_DOC),
        "chunk_id": str(_CHUNKS[0]),
        "title": None,
        "headings": [],
        "page_start": None,
        "page_end": None,
    }
    message = AIMessage(
        content="a",
        additional_kwargs={"citations": [cited], "citation_schema_version": 1, "grounded": True},
    )

    fields = agent_service._stamped_citations(message)

    [kept] = fields["citations"]
    assert (kept["title"], kept["page_start"], kept["page_end"]) == (None, None, None)
    response = AgentResponse(
        request_id="r", thread_id="t", answer="a", used_tools=[], confidence=0.9, **fields
    )
    assert response.citations is not None and response.citations[0].page_start is None
    assert ThreadMessage(role="assistant", content="a", **fields).grounded is True


def test_the_answer_message_is_the_last_one_the_graph_committed() -> None:
    answer = AIMessage(content="a")
    update = [RemoveMessage(id="old"), HumanMessage(content="q"), answer]

    assert agent_service._answer_message(update) is answer
    assert agent_service._answer_message([HumanMessage(content="q")]) is None
    assert agent_service._answer_message(None) is None


def test_stored_citation_fields_are_never_sent_to_the_provider() -> None:
    from langchain_openai.chat_models.base import _convert_message_to_dict

    message = AIMessage(
        content="x",
        additional_kwargs={
            "run_id": "r",
            "citations": [{"title": "secret title"}],
            "citation_schema_version": 1,
            "grounded": True,
        },
    )

    sent = _convert_message_to_dict(message)
    assert not {"citations", "citation_schema_version", "grounded"} & set(sent)
    assert "secret title" not in repr(sent)


async def test_a_search_with_nothing_relevant_gives_an_ungrounded_answer(
    monkeypatch: pytest.MonkeyPatch, rejected: list[int]
) -> None:
    # RAG-04.03: the model sees the marker, has no cite_id to give, and a guessed one is dropped.
    model = _model(
        monkeypatch,
        _call("search_knowledge", query="nothing"),
        _call(
            "AgentAnswer",
            answer="Your documents do not contain the answer.",
            confidence=0.9,
            citations=["cite-1"],
        ),
    )

    graph, config = await _thread_runs(model, turns=1)

    [marker] = _results(model)
    assert "no_relevant_results" in str(marker.content)
    answer = (await graph.aget_state(config)).values["messages"][1]
    assert (answer.additional_kwargs["citations"], answer.additional_kwargs["grounded"]) == (
        [],
        False,
    )
    assert rejected == [1]


async def test_the_fake_model_searches_and_cites_for_browser_tests() -> None:
    # RAG-06.02: the dev/test fake model (no provider key) answers `search: ...` by calling
    # search_knowledge, then cites the first cite_id it was shown, through the same validation.
    specs = knowledge_tools.knowledge_specs(Settings(env="test"), lambda: None)
    graph = main_graph.build_graph(
        Settings(env="test", openai_api_key=None, anthropic_api_key=None, nvidia_api_key=None),
        checkpointer=InMemorySaver(),
        registry=ToolRegistry(specs),
    )
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="search: leave")]},
        config,
        context=AuthorizationContext(_SCOPES, owner_key=_OWNER),
    )

    assert result["answer"].citations == ["cite-1"]
    stored = (await graph.aget_state(config)).values["messages"][-1].additional_kwargs
    assert stored["grounded"] is True
    assert [c["chunk_id"] for c in stored["citations"]] == [str(_CHUNKS[0])]


async def test_the_fake_model_answers_plainly_without_the_prefix() -> None:
    specs = knowledge_tools.knowledge_specs(Settings(env="test"), lambda: None)
    graph = main_graph.build_graph(
        Settings(env="test", openai_api_key=None, anthropic_api_key=None, nvidia_api_key=None),
        checkpointer=InMemorySaver(),
        registry=ToolRegistry(specs),
    )

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content="what is leave?")]},
        {"configurable": {"thread_id": str(uuid.uuid4())}},
        context=AuthorizationContext(_SCOPES, owner_key=_OWNER),
    )

    assert result["answer"].citations == []
    assert result["answer"].used_tools == []
