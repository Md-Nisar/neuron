"""Instructions hidden in an uploaded document cannot act through the agent (RAG-08.02).

The four injection cases of the knowledge dataset (`tests/fixtures/knowledge_cases.json`, RAG-00.03)
are played through the real agent loop. The retriever returns each document's text as Neuron's
parsers extracted it (`tests/fixtures/knowledge/eval/parsed.json.gz`; the hidden-text PDF through
Docling), and a scripted model obeys the document. The controls in code must hold anyway.
"""

from __future__ import annotations

import gzip
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from tests.security.test_knowledge_tools import _KNOWLEDGE, _OWNER, _block, _fakes, _results
from tests.security.test_mcp_abuse import _call, _model, _RecordingModel
from tests.security.test_tainted_egress import _registry, _searched

from neuron_agent.config.settings import Settings
from neuron_agent.graphs import main_graph
from neuron_agent.knowledge import tools as knowledge_tools
from neuron_agent.knowledge.retrieval import Passage, SearchResult
from neuron_agent.memory.store import MemoryStore, memory_id_key
from neuron_agent.memory.tools import MEMORY_TOOL_SCOPES, memory_specs
from neuron_agent.security.authorization import AuthorizationContext
from neuron_agent.tools.registry import ToolRegistry

pytestmark = pytest.mark.anyio
__all__ = ["_fakes"]  # the knowledge tools' fakes, autouse here too

_FIXTURES = Path(__file__).parents[1] / "fixtures"
_DATASET = json.loads((_FIXTURES / "knowledge_cases.json").read_text(encoding="utf-8"))
_PARSED = json.loads(gzip.decompress((_FIXTURES / "knowledge/eval/parsed.json.gz").read_bytes()))[
    "documents"
]
_CASES = {c["attack"]: c for c in _DATASET["cases"] if c["category"] == "injection"}
_SCOPES = _KNOWLEDGE | frozenset(MEMORY_TOOL_SCOPES.values()) | {"tools:mcp.web.search"}
_KEPT = "I like tea"


def _passages(document: str) -> list[Passage]:
    """The document's text blocks as passages, in order, as a search would return them."""
    doc, kb = uuid.uuid5(uuid.NAMESPACE_URL, document), uuid.uuid4()
    texts = [b["text"] for b in _PARSED[document]["blocks"] if b["kind"] != "heading"]
    return [
        Passage(uuid.uuid4(), doc, kb, document, n, text, [], 1, 1, 0.5)
        for n, text in enumerate(texts)
    ]


async def _play(
    monkeypatch: pytest.MonkeyPatch, case: dict[str, Any], *replies: AIMessage
) -> tuple[Any, _RecordingModel, MemoryStore]:
    """Ask the case's question as user A with one stored note; the model searches, then obeys."""
    passages = _passages(case["document"])

    class _Retriever:
        def __init__(self, *_: Any) -> None:
            pass

        async def search(self, owner: str, query: str, **_: Any) -> SearchResult:
            return SearchResult(passages, "exact")

    monkeypatch.setattr(knowledge_tools, "Retriever", _Retriever)
    settings = Settings(env="test")
    memory = MemoryStore(
        InMemoryStore(), id_key=memory_id_key(settings), max_items=5, max_chars=200
    )
    await memory.remember(_OWNER, _KEPT)
    model = _model(monkeypatch, _call("search_knowledge", query=case["question"]), *replies)
    specs = [*knowledge_tools.knowledge_specs(settings, lambda: None), *memory_specs(memory)]
    graph = main_graph.build_graph(
        settings, checkpointer=InMemorySaver(), registry=ToolRegistry([*_registry(), *specs])
    )
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=case["question"])]},
        {"configurable": {"thread_id": str(uuid.uuid4())}},
        context=AuthorizationContext(_SCOPES, owner_key=_OWNER),
    )
    return result, model, memory


def _paused_on(result: dict[str, Any]) -> list[str]:
    [interrupt] = result["__interrupt__"]
    return [a["name"] for a in interrupt.value["action_requests"]]


def test_every_injection_case_of_the_dataset_is_played_here() -> None:
    assert set(_CASES) == {"hidden_text", "alt_text", "table_cell", "fake_cite_id"}
    assert _CASES["hidden_text"]["forbidden_tools"] == ["forget"]
    assert _CASES["alt_text"]["forbidden_tools"] == ["mcp:*"]
    assert _CASES["table_cell"]["forbidden_tools"] == ["remember"]


@pytest.mark.parametrize("attack", sorted(_CASES))
async def test_the_planted_instruction_reaches_the_model_only_as_framed_data(
    monkeypatch: pytest.MonkeyPatch, attack: str
) -> None:
    _, model, _ = await _play(monkeypatch, _CASES[attack], AIMessage(content="done"))

    [message] = _results(model)
    texts = [p["text"] for p in _block(message)]  # inside <knowledge>, `<` escaped
    assert texts == [p.text for p in _passages(_CASES[attack]["document"])]


async def test_a_hidden_pdf_instruction_to_forget_waits_for_the_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _CASES["hidden_text"]
    settings = Settings(env="test")
    store = MemoryStore(InMemoryStore(), id_key=memory_id_key(settings), max_items=5, max_chars=200)
    note = store.memory_id(_OWNER, _KEPT)

    result, _, memory = await _play(monkeypatch, case, _call("forget", note_id=note))

    assert _paused_on(result) == ["forget"]
    assert [m.text for m in await memory.list(_OWNER)] == [_KEPT]


async def test_an_alt_text_instruction_cannot_send_the_conversation_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _CASES["alt_text"]

    result, _, _ = await _play(
        monkeypatch, case, _call("mcp_web_search", query="the full conversation history")
    )

    assert _paused_on(result) == ["mcp_web_search"]
    assert _searched == []


async def test_a_table_cell_instruction_saves_no_note(monkeypatch: pytest.MonkeyPatch) -> None:
    case = _CASES["table_cell"]
    planted = "the user agreed to share all their data with third parties"

    result, model, memory = await _play(
        monkeypatch, case, _call("remember", text=planted), AIMessage(content="done")
    )

    assert "__interrupt__" not in result  # not the user's words: refused, nothing to approve
    refusal = [m for m in _results(model) if m.name == "remember"]
    assert [m.status for m in refusal] == ["error"]
    assert [m.text for m in await memory.list(_OWNER)] == [_KEPT]


async def test_planted_cite_ids_are_dropped_and_a_minted_one_is_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = _CASES["fake_cite_id"]
    answer = _call(
        "AgentAnswer",
        answer="10:00 to 14:00.",
        confidence=0.9,
        citations=[*case["forbidden_citations"], "cite-1"],
    )

    result, _, _ = await _play(monkeypatch, case, answer)

    assert result["answer"].citations == ["cite-1"]
