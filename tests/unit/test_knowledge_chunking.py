"""`chunk_document`: heading paths, token budget, splitting, pages (RAG-02.04)."""

from __future__ import annotations

import gzip
import json
import re
import time
from pathlib import Path
from typing import Any

import anyio
import httpx2
import pytest

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge.chunking import chunk_document, estimate_tokens
from neuron_agent.knowledge.docling_serve import DoclingServeParser
from neuron_agent.knowledge.parsing import PDF, Block, Limits, ParsedDocument

_FIXTURES = Path(__file__).parents[1] / "fixtures"


def _doc(*blocks: Block) -> ParsedDocument:
    return ParsedDocument(parser_version="test/1", blocks=blocks)


def _h(text: str, level: int) -> Block:
    return Block(kind="heading", text=text, level=level)


def _t(text: str, page: int | None = None) -> Block:
    return Block(kind="text", text=text, page=page)


def test_headings_set_the_path_of_the_chunks_under_them() -> None:
    chunks = chunk_document(
        _doc(
            _h("A", 1),
            _t("a"),
            _h("B", 2),
            _t("b"),
            _h("C", 2),
            _t("c"),
            _h("D", 1),
            _t("d"),
        ),
        max_tokens=100,
    )
    assert [(chunk.headings, chunk.text) for chunk in chunks] == [
        (("A",), "a"),
        (("A", "B"), "b"),
        (("A", "C"), "c"),
        (("D",), "d"),
    ]
    assert [chunk.ordinal for chunk in chunks] == [0, 1, 2, 3]


def test_blocks_under_one_heading_share_a_chunk_up_to_the_budget() -> None:
    blocks = [_t("x" * 90, page=page) for page in (1, 1, 2, 3)]  # 30 tokens each
    chunks = chunk_document(_doc(*blocks), max_tokens=70)
    assert [chunk.text.count("x") for chunk in chunks] == [180, 180]
    assert [(chunk.page_start, chunk.page_end) for chunk in chunks] == [(1, 1), (2, 3)]
    assert all(chunk.token_count == estimate_tokens(chunk.text) <= 70 for chunk in chunks)


@pytest.mark.parametrize(
    "text",
    [
        "\n".join(f"row {i} | cell | cell" for i in range(500)),  # lines
        " ".join(["word"] * 3_000),  # spaces
        "é" * 5_000,  # neither, and two bytes a character
        "𝔁" * 5_000,  # four bytes a character
    ],
    ids=["lines", "words", "characters", "astral"],
)
def test_a_long_block_is_split_without_losing_text(text: str) -> None:
    chunks = chunk_document(_doc(_t(text, page=4)), max_tokens=50)
    assert len(chunks) > 1
    assert all(chunk.token_count <= 50 for chunk in chunks)
    assert all(chunk.page_start == chunk.page_end == 4 for chunk in chunks)
    joined = "".join(chunk.text for chunk in chunks)
    assert re.sub(r"\s", "", joined) == re.sub(r"\s", "", text)


def test_a_page_of_text_without_spaces_is_split_in_linear_time() -> None:
    started = time.perf_counter()
    chunks = chunk_document(_doc(_t("x" * 200_000)), max_tokens=50)
    assert time.perf_counter() - started < 5  # re-encoding the growing text took minutes
    assert sum(len(chunk.text) for chunk in chunks) == 200_000


def test_headings_alone_make_no_chunk() -> None:
    assert chunk_document(_doc(_h("Title", 1), _h("Section", 2)), max_tokens=100) == []


def test_a_long_heading_is_cut_on_the_chunks() -> None:
    (chunk,) = chunk_document(_doc(_h("H" * 1_000, 1), _t("body")), max_tokens=100)
    assert chunk.headings == ("H" * 300,)


def test_the_corpus_pdf_chunks_keep_their_headings_and_pages() -> None:
    def replay(request: httpx2.Request) -> httpx2.Response:
        recorded = _FIXTURES / "knowledge" / "recorded" / "nist-cswp-29.docling.json.gz"
        return httpx2.Response(200, content=gzip.decompress(recorded.read_bytes()))

    parser = DoclingServeParser(
        "http://docling:5001",
        timeout_seconds=5,
        max_response_bytes=50_000_000,
        transport=httpx2.MockTransport(replay),
    )
    parsed = anyio.run(parser.parse, b"%PDF", PDF, Limits(50_000_000, 2_000, 50_000))
    max_tokens = Settings(env="test").knowledge_chunk_max_tokens
    chunks = chunk_document(parsed, max_tokens)
    assert all(0 < chunk.token_count <= max_tokens for chunk in chunks)
    assert all(chunk.page_start and chunk.page_end for chunk in chunks)
    assert sum(1 for chunk in chunks if chunk.headings) / len(chunks) > 0.9
    data: dict[str, Any] = json.loads((_FIXTURES / "knowledge_cases.json").read_text("utf-8"))
    found = 0
    for case in data["cases"]:
        for source in case.get("expected_sources", []):
            if source["document"] == "nist-cswp-29":
                evidence = _norm(case["evidence"])
                hits = [chunk for chunk in chunks if evidence in _norm(chunk.text)]
                found += 1
                assert hits, case["id"]
                assert any(chunk.page_start in source["pages"] for chunk in hits), case["id"]
    assert found == 5


def _norm(text: str) -> str:
    text = text.replace("­", "").replace("ﬁ", "fi").replace("’", "'")
    return re.sub(r"\s+", " ", text).lower().strip()
