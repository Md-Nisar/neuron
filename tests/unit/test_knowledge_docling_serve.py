"""`DoclingServeParser` against a recorded docling-serve reply (RAG-02.02 AC1, AC2, AC3).

The recording is Docling's JSON for NIST CSWP 29, a corpus PDF, in docling-serve's reply
envelope (`tests/fixtures/knowledge/recorded/README.md`). Every test runs without docling-serve.
"""

from __future__ import annotations

import gzip
import json
import re
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import anyio
import httpx2
import pytest

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge.docling_serve import DoclingServeParser
from neuron_agent.knowledge.parsing import PDF, Limits, ParseError

pytestmark = pytest.mark.anyio

_FIXTURES = Path(__file__).parents[1] / "fixtures"
_RECORDED = _FIXTURES / "knowledge" / "recorded" / "nist-cswp-29.docling.json.gz"
_LIMITS = Limits(max_bytes=50_000_000, max_pages=2_000, max_page_chars=50_000)
_Handler = Callable[[httpx2.Request], Any]


def _parser(handler: _Handler, *, timeout: float = 5, max_response: int = 50_000_000) -> Any:
    return DoclingServeParser(
        "http://docling:5001",
        timeout_seconds=timeout,
        max_response_bytes=max_response,
        transport=httpx2.MockTransport(handler),
    )


def _replay(request: httpx2.Request) -> httpx2.Response:
    return httpx2.Response(200, content=gzip.decompress(_RECORDED.read_bytes()))


def _reply(texts: list[dict[str, Any]], **document: Any) -> bytes:
    content = {
        "version": "1.8.0",
        "body": {"children": [{"$ref": f"#/texts/{i}"} for i in range(len(texts))]},
        "texts": texts,
        "pages": {"1": {"size": {"width": 600.0, "height": 800.0}}},
        **document,
    }
    return json.dumps({"status": "success", "document": {"json_content": content}}).encode()


def _norm(text: str) -> str:
    """As the spike scored Docling: soft hyphens, ligatures, quotes and spacing ignored."""
    text = text.replace("­", "").replace("ﬁ", "fi").replace("’", "'")
    return re.sub(r"\s+", " ", text).lower().strip()


async def test_a_corpus_pdf_keeps_its_pages_and_headings() -> None:
    parsed = await _parser(_replay).parse(b"%PDF-1.7", PDF, _LIMITS)
    assert parsed.page_count == 32
    assert parsed.parser_version.startswith("docling/")
    pages: dict[int | None, str] = defaultdict(str)
    for block in parsed.blocks:
        pages[block.page] += " " + _norm(block.text)
    data = json.loads((_FIXTURES / "knowledge_cases.json").read_text("utf-8"))
    checked = 0
    for case in data["cases"]:
        for source in case.get("expected_sources", []):
            if source["document"] == "nist-cswp-29":
                evidence = _norm(case["evidence"])
                assert any(evidence in pages[page] for page in source["pages"]), case["id"]
                checked += 1
    assert checked == 5
    headings = [block for block in parsed.blocks if block.kind == "heading"]
    assert len(headings) >= 20
    assert all(block.level and block.page for block in headings)
    assert any(block.kind == "table" for block in parsed.blocks)


async def test_bytes_are_posted_as_a_file_with_the_page_cap() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return _replay(request)

    await _parser(handler).parse(b"%PDF-1.7 the bytes", PDF, _LIMITS)
    (request,) = seen
    assert (request.method, request.url.path) == ("POST", "/v1/convert/file")
    body = request.content
    assert b"%PDF-1.7 the bytes" in body
    assert b'name="to_formats"\r\n\r\njson' in body
    assert b'name="page_range"\r\n\r\n2001' in body
    assert b"sources" not in body  # never a URL for docling-serve to fetch


async def _slow(request: httpx2.Request) -> httpx2.Response:
    await anyio.sleep(5)
    return _replay(request)


def _raise(error: type[Exception]) -> _Handler:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise error("refused", request=request)  # type: ignore[call-arg]

    return handler


async def _chunks() -> AsyncIterator[bytes]:
    for _ in range(10):
        yield b"x" * 400_000


@pytest.mark.parametrize(
    ("handler", "code", "retryable"),
    [
        (_slow, "parser_timeout", False),
        (_raise(httpx2.ReadTimeout), "parser_timeout", False),
        (_raise(httpx2.ConnectError), "parser_unavailable", True),
        (_raise(httpx2.ConnectTimeout), "parser_unavailable", True),
        (lambda r: httpx2.Response(503), "parser_unavailable", True),
        (lambda r: httpx2.Response(429), "parser_unavailable", True),
        # A file that crashes the converter, or kills it mid-reply, would do it again.
        (lambda r: httpx2.Response(500), "parser_failed", False),
        (_raise(httpx2.RemoteProtocolError), "parser_failed", False),
        (
            lambda r: httpx2.Response(200, headers=[(b"content-length", b"\xb2")], content=b"{}"),
            "parser_output_invalid",
            False,
        ),
        (lambda r: httpx2.Response(422), "parser_failed", False),
        (
            lambda r: httpx2.Response(200, content=b'{"status": "success"}'),
            "parser_output_invalid",
            False,
        ),
        (
            lambda r: httpx2.Response(200, content=_reply([]).replace(b"success", b"failure")),
            "parser_failed",
            False,
        ),
        (
            lambda r: httpx2.Response(
                200, content=_reply([], body={"children": [{"$ref": "#/texts/9"}]})
            ),
            "parser_output_invalid",
            False,
        ),
        (
            lambda r: httpx2.Response(200, content=b"x" * 3_000_000),
            "parser_output_too_large",
            False,
        ),
        (lambda r: httpx2.Response(200, content=_chunks()), "parser_output_too_large", False),
    ],
    ids=[
        "deadline",
        "read-timeout",
        "connect",
        "connect-timeout",
        "503",
        "429",
        "500",
        "reset",
        "odd-length-header",
        "422",
        "schema",
        "failure",
        "ref",
        "length",
        "stream",
    ],
)
async def test_parser_failures_have_stable_codes(
    handler: _Handler, code: str, retryable: bool
) -> None:
    parser = _parser(handler, timeout=0.5, max_response=2_000_000)
    with pytest.raises(ParseError) as caught:
        await parser.parse(b"%PDF", PDF, _LIMITS)
    assert (caught.value.code, caught.value.retryable) == (code, retryable)


async def test_a_document_past_the_page_cap_is_refused() -> None:
    parser, limits = _parser(_replay), Limits(50_000_000, 10, 50_000)
    with pytest.raises(ParseError, match="too_many_pages"):
        await parser.parse(b"%PDF", PDF, limits)


async def test_running_heads_are_dropped_and_boxes_are_measured_from_the_top() -> None:
    box = {"l": 10.0, "t": 700.0, "r": 200.0, "b": 650.0, "coord_origin": "BOTTOMLEFT"}
    texts = [
        {"label": "page_header", "text": "NIST CSWP 29", "prov": [{"page_no": 1, "bbox": box}]},
        {
            "label": "section_header",
            "text": "1. Scope",
            "level": 1,
            "prov": [{"page_no": 1, "bbox": box}],
        },
        {"label": "list_item", "text": "an item", "prov": [{"page_no": 1}]},
    ]
    reply = _reply(texts)
    parsed = await _parser(lambda r: httpx2.Response(200, content=reply)).parse(
        b"%PDF", PDF, _LIMITS
    )
    heading, item = parsed.blocks
    assert (heading.kind, heading.text, heading.level, heading.page) == (
        "heading",
        "1. Scope",
        2,
        1,
    )
    assert heading.bbox == (10.0, 100.0, 200.0, 150.0)
    assert (item.kind, item.bbox) == ("list", None)


async def test_a_reference_cycle_is_walked_once() -> None:
    groups = [{"children": [{"$ref": "#/groups/0"}, {"$ref": "#/texts/0"}]}]
    reply = _reply(
        [{"label": "text", "text": "once", "prov": [{"page_no": 1}]}],
        body={"children": [{"$ref": "#/groups/0"}, {"$ref": "#/texts/0"}]},
        groups=groups,
    )
    parsed = await _parser(lambda r: httpx2.Response(200, content=reply)).parse(
        b"%PDF", PDF, _LIMITS
    )
    assert [block.text for block in parsed.blocks] == ["once"]


@pytest.mark.parametrize(
    "ref", ["groups/0", "#/groups/00", "#/texts/\u00b2", "#/texts/" + "1" * 5_000, "#/other/0"]
)
async def test_one_spelling_per_reference(ref: str) -> None:
    """An item has one reference, so it cannot be expanded again under another spelling."""
    reply = _reply(
        [{"label": "text", "text": "once", "prov": [{"page_no": 1}]}],
        body={"children": [{"$ref": "#/groups/0"}]},
        groups=[{"children": [{"$ref": "#/texts/0"}, {"$ref": ref}]}],
    )
    parser = _parser(lambda r: httpx2.Response(200, content=reply))
    with pytest.raises(ParseError, match="parser_output_invalid"):
        await parser.parse(b"%PDF", PDF, _LIMITS)


def test_the_parser_url_has_no_credentials() -> None:
    with pytest.raises(ValueError, match="knowledge_parser_url"):
        Settings(env="test", knowledge_parser_url="http://user:secret@docling:5001")


def test_the_parser_needs_its_url() -> None:
    unset = Settings(env="test")
    with pytest.raises(ParseError, match="parser_not_configured"):
        DoclingServeParser.from_settings(unset)
    parser = DoclingServeParser.from_settings(
        Settings(env="test", knowledge_parser_url="http://docling:5001")
    )
    assert PDF in parser.media_types
