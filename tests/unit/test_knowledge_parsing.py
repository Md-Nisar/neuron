"""Input checks, output validation and the plain-text parser (RAG-02.02; ADR 0014 K2)."""

from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path
from typing import Any

import pytest

from neuron_agent.knowledge import parsing
from neuron_agent.knowledge.parsing import (
    DOCX,
    MARKDOWN,
    PDF,
    TEXT,
    XLSX,
    Limits,
    ParseError,
    PlainTextParser,
    accepted_type,
    check_input,
    parse_document,
    validate_output,
)

pytestmark = pytest.mark.anyio

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NAN = float("nan")
_LIMITS = Limits(max_bytes=1_000_000, max_pages=10, max_page_chars=2_000)


def _zip(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _types(*content_types: str) -> bytes:
    overrides = "".join(
        f'<Override PartName="/p{i}" ContentType="{t}"/>' for i, t in enumerate(content_types)
    )
    return f"<Types>{overrides}</Types>".encode()


_MAIN = DOCX + ".main+xml"
_DOCX = {"[Content_Types].xml": _types(_MAIN), "word/document.xml": b"<w:document/>"}


def _dupes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in _DOCX.items():
            archive.writestr(name, content)
        archive.writestr("Word/Document.xml", b"<w:document/>")
    return buffer.getvalue()


_VBA = "application/vnd.ms-office.vbaProject"
_DOCM = "application/vnd.ms-word.document.macroEnabled.main+xml"
_DOTX = "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml"


def _code(data: bytes, declared: str, limits: Limits = _LIMITS) -> str:
    with pytest.raises(ParseError) as caught:
        check_input(data, declared, limits)
    assert caught.value.retryable is False
    return caught.value.code


def test_supported_files_pass_as_the_type_their_content_shows() -> None:
    assert check_input(b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF", PDF, _LIMITS) == PDF
    assert check_input(_zip(_DOCX), DOCX, _LIMITS) == DOCX
    assert check_input("# Café\n".encode(), MARKDOWN, _LIMITS) == MARKDOWN
    assert check_input(b"plain", TEXT, _LIMITS) == TEXT


def _short(value: object) -> str | None:
    """Bytes ids by length: pytest puts the id in an environment variable, capped on Windows."""
    return f"{len(value)}-bytes" if isinstance(value, bytes) else None


@pytest.mark.parametrize(
    ("data", "declared", "code"),
    [
        (b"", TEXT, "empty_file"),
        (b"x" * 1_000_001, TEXT, "file_too_large"),
        (b"MZ\x90\x00", "application/x-msdownload", "unsupported_media_type"),
        # An encrypted PDF names its Encrypt dictionary in the trailer.
        (b"%PDF-1.7\ntrailer\n<< /Root 1 0 R /Encrypt 5 0 R >>\n%%EOF", PDF, "encrypted_pdf"),
        (b"%PDF-1.7\n%%EOF", TEXT, "media_type_mismatch"),
        (b"plain text", PDF, "media_type_mismatch"),
        (b"\xff\xfe\x00b\x00i\x00n", TEXT, "media_type_mismatch"),
        (_zip({"notes.txt": b"hello"}), TEXT, "archive_refused"),
        (_zip({"notes.txt": b"hello"}), DOCX, "archive_refused"),
        (b"PK\x03\x04 not really a zip", DOCX, "archive_refused"),
        (_zip({**_DOCX, "word/vbaProject.bin": b"\x00"}), DOCX, "macro_refused"),
        (
            _zip({"[Content_Types].xml": _types(XLSX + ".main+xml"), "xl/x.xml": b"<w/>"}),
            DOCX,
            "media_type_mismatch",
        ),
        # Macros are found by content type and part name, whatever the part is called.
        (
            _zip({**_DOCX, "[Content_Types].xml": _types(_MAIN, _VBA), "word/x.bin": b"\x00"}),
            DOCX,
            "macro_refused",
        ),
        (_zip({**_DOCX, "[Content_Types].xml": _types(_DOCM)}), DOCX, "macro_refused"),
        (_zip({**_DOCX, "word/activeX/activeX1.xml": b"<ax/>"}), DOCX, "macro_refused"),
        (_zip({**_DOCX, "word/vbaProjec%74.bin": b"\x00"}), DOCX, "macro_refused"),
        (_zip({**_DOCX, "[Content_Types].xml": _types(_DOTX)}), DOCX, "media_type_mismatch"),
        # Character references or UTF-16 could hide a content type from the byte checks.
        (
            _zip(
                {
                    **_DOCX,
                    "[Content_Types].xml": _types(_MAIN).replace(
                        b"<Types>",
                        b'<Types><Default Extension="bin" ContentType="&#x61;pplication/x"/>',
                    ),
                }
            ),
            DOCX,
            "archive_refused",
        ),
        (
            _zip({**_DOCX, "[Content_Types].xml": _types(_MAIN).decode().encode("utf-16")}),
            DOCX,
            "archive_refused",
        ),
        # Two names one reader may treat as one part.
        (_dupes(), DOCX, "archive_refused"),
        (b"%PDF-1.7\ntrailer\n<< /Encrypt\x005 0 R >>", PDF, "encrypted_pdf"),
        # PDF names may spell any character as #xx.
        (b"%PDF-1.7\ntrailer\n<< /#45ncrypt 5 0 R >>", PDF, "encrypted_pdf"),
        (b"%PDF-1.7\ntrailer\n<< /En#63rypt 5 0 R >>", PDF, "encrypted_pdf"),
    ],
    ids=_short,
)
def test_unsafe_or_mislabelled_files_are_refused_before_parsing(
    data: bytes, declared: str, code: str
) -> None:
    assert _code(data, declared) == code


def test_a_zip_bomb_is_refused_by_its_inflated_size() -> None:
    # 10 MB of zeros deflates to about 10 KB: far past the 100:1 ratio.
    bomb = _zip({**_DOCX, "word/media/zeros.bin": bytes(10_000_000)})
    assert len(bomb) < 100_000
    assert _code(bomb, DOCX, Limits(max_bytes=200_000, max_pages=10, max_page_chars=2_000)) == (
        "decompression_limit"
    )


def test_a_zip_bomb_split_across_members_is_refused_by_its_total() -> None:
    # Each member is under the per-member cap; only the total and the ratio give it away.
    parts = {f"word/media/zeros{n}.bin": bytes(190_000) for n in range(5)}
    bomb = _zip({**_DOCX, **parts})
    assert _code(bomb, DOCX, Limits(max_bytes=200_000, max_pages=10, max_page_chars=2_000)) == (
        "decompression_limit"
    )


def test_zip_entries_are_counted_before_the_directory_is_read() -> None:
    many = _zip({**_DOCX, **{f"word/media/{i}.xml": b"" for i in range(10_001)}})
    assert _code(many, DOCX, Limits(10_000_000, 10, 2_000)) == "decompression_limit"


def test_unusual_compression_and_oversized_members_are_refused() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_BZIP2) as archive:
        for name, content in _DOCX.items():
            archive.writestr(name, content)
    assert _code(buffer.getvalue(), DOCX) == "archive_refused"
    big = _zip({**_DOCX, "word/document.xml": b"<w/>" * 300_000})  # 1.2 MB inflated
    assert _code(big, DOCX) == "decompression_limit"


def test_errors_carry_only_a_code() -> None:
    secret = b"%PDF-1.7 confidential-salary-table /Encrypt"
    with pytest.raises(ParseError) as caught:
        check_input(secret, PDF, _LIMITS)
    assert str(caught.value) == "encrypted_pdf"


def _doc(*blocks: dict[str, Any], page_count: int | None = None) -> dict[str, Any]:
    return {"parser_version": "test/1", "page_count": page_count, "blocks": list(blocks)}


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ({"parser_version": "x", "blocks": []}, "parser_output_invalid"),
        (_doc({"kind": "image", "text": "x"}), "parser_output_invalid"),
        (_doc({"kind": "text", "text": "x", "page": 0}, page_count=1), "parser_output_invalid"),
        (_doc({"kind": "text", "text": "x", "script": "y"}), "parser_output_invalid"),
        (_doc({"kind": "text", "text": "x", "page": 3}, page_count=2), "parser_output_invalid"),
        ("not a document", "parser_output_invalid"),
        (_doc({"kind": "text", "text": "x", "page": 1}, page_count=11), "too_many_pages"),
        (_doc({"kind": "text", "text": "x" * 2_001, "page": 1}, page_count=1), "page_too_long"),
        (_doc({"kind": "text", "text": "x" * 20_001}), "page_too_long"),
        (_doc({"kind": "text", "text": "a\x00b"}), "parser_output_invalid"),
        (_doc({"kind": "text", "text": "x", "bbox": [0, 0, NAN, 1]}), "parser_output_invalid"),
        (_doc(*({"kind": "text", "text": "x"} for _ in range(2_001))), "too_many_blocks"),
    ],
)
def test_parser_output_is_validated_against_the_schema_and_caps(raw: Any, code: str) -> None:
    with pytest.raises(ParseError) as caught:
        validate_output(raw, _LIMITS)
    assert caught.value.code == code


async def test_form_feeds_give_text_its_pages() -> None:
    text = b"Intro line\n\nSecond paragraph\fPage two text\f\fLast page"
    parsed = await PlainTextParser().parse(text, TEXT, _LIMITS)
    assert parsed.page_count == 4
    assert [(b.page, b.text) for b in parsed.blocks] == [
        (1, "Intro line"),
        (1, "Second paragraph"),
        (2, "Page two text"),
        (4, "Last page"),
    ]
    assert parsed.parser_version == PlainTextParser.version


async def test_markdown_headings_but_not_fenced_code() -> None:
    text = b"# Title\n\nBody text\n\n```\n# not a heading\n```\n\n### Deep ###\nmore"
    parsed = await PlainTextParser().parse(text, MARKDOWN, _LIMITS)
    assert [(b.kind, b.text, b.level, b.page) for b in parsed.blocks] == [
        ("heading", "Title", 1, None),
        ("text", "Body text", None, None),
        ("code", "```\n# not a heading\n```", None, None),
        ("heading", "Deep", 3, None),
        ("text", "more", None, None),
    ]
    # In a .txt file a leading `#` is just text.
    plain = await PlainTextParser().parse(b"# Title", TEXT, _LIMITS)
    assert plain.blocks[0].kind == "text"


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"a\f" * 11, "too_many_pages"),  # counted before anything is built
        (b"a\n\n" * 2_001, "too_many_blocks"),  # 200 blocks per page
    ],
    ids=_short,
)
async def test_page_and_block_bombs_are_refused(data: bytes, code: str) -> None:
    parser = PlainTextParser()
    with pytest.raises(ParseError, match=code):
        await parser.parse(data, TEXT, _LIMITS)


async def test_a_hostile_heading_line_parses_in_linear_time() -> None:
    line = b"# a" + b" " * 200_000 + b"b"
    started = time.monotonic()
    parsed = await PlainTextParser().parse(line, MARKDOWN, Limits(1_000_000, 10, 300_000))
    assert time.monotonic() - started < 1
    assert parsed.blocks[0].kind == "heading"


async def test_a_byte_order_mark_does_not_hide_the_first_heading() -> None:
    parsed = await PlainTextParser().parse("\ufeff# Title".encode(), MARKDOWN, _LIMITS)
    assert (parsed.blocks[0].kind, parsed.blocks[0].text) == ("heading", "Title")


async def test_parse_document_checks_first_and_needs_a_parser_for_the_type() -> None:
    parsers = [PlainTextParser()]
    parsed = await parse_document(b"# Hi", MARKDOWN, _LIMITS, parsers)
    assert parsed.blocks[0].text == "Hi"
    with pytest.raises(ParseError, match="encrypted_pdf"):
        await parse_document(b"%PDF-1.7 /Encrypt", PDF, _LIMITS, parsers)
    # No PDF parser is configured: refused, not retried.
    with pytest.raises(ParseError, match="unsupported_media_type"):
        await parse_document(b"%PDF-1.7\n%%EOF", PDF, _LIMITS, parsers)


def _corpus() -> tuple[dict[str, Any], dict[str, Any]]:
    data = json.loads((_FIXTURES / "knowledge_cases.json").read_text("utf-8"))
    return {d["id"]: d for d in data["documents"]}, data


async def test_corpus_markdown_sections_are_headings() -> None:
    documents, data = _corpus()
    checked = 0
    for case in data["cases"]:
        for source in case.get("expected_sources", []):
            document = documents[source["document"]]
            path = document["source"].get("path")
            if document["media_type"] != MARKDOWN or path is None or "sections" not in source:
                continue
            raw = (_FIXTURES / path).read_bytes()
            assert check_input(raw, MARKDOWN, _LIMITS) == MARKDOWN
            parsed = await PlainTextParser().parse(raw, MARKDOWN, _LIMITS)
            headings = {b.text for b in parsed.blocks if b.kind == "heading"}
            assert set(source["sections"]) <= headings, case["id"]
            checked += 1
    assert checked >= 3


def test_limits_come_from_settings() -> None:
    from neuron_agent.config.settings import Settings

    limits = Limits.from_settings(Settings(env="test", knowledge_parse_max_pages=5))
    assert limits.max_pages == 5
    assert limits.max_bytes == 50_000_000
    assert parsing.SUPPORTED >= {PDF, DOCX, TEXT, MARKDOWN}


@pytest.mark.parametrize(
    ("data", "claimed", "expected"),
    [
        (b"%PDF-1.7\n%%EOF", TEXT, PDF),  # the content decides
        (b"%PDF-1.7\n%%EOF", "application/octet-stream", PDF),
        (_zip(_DOCX), "", DOCX),  # the Office type is found in the content
        (_zip(_DOCX), XLSX, DOCX),
        (b"<div align=center>logo</div>\n# Title\n", MARKDOWN, MARKDOWN),  # Markdown holds HTML
        (b"plain notes", "", TEXT),
        (b"a < b <p", TEXT, TEXT),
    ],
)
def test_an_uploads_type_comes_from_its_content(data: bytes, claimed: str, expected: str) -> None:
    assert accepted_type(data, claimed, _LIMITS) == expected


@pytest.mark.parametrize(
    ("data", "claimed", "code"),
    [
        (b"<!DOCTYPE html><html><script>x</script>", PDF, "unsupported_media_type"),
        (b"\xef\xbb\xbf \n<HTML>", TEXT, "unsupported_media_type"),
        (b" " * 5_000 + b"<html>", TEXT, "unsupported_media_type"),  # past the first 1,024 bytes
        (b"<script\tsrc=x>", TEXT, "unsupported_media_type"),  # any whitespace ends the name
        (b"<svg/onload=x>", TEXT, "unsupported_media_type"),
        (b"<p\nclass=x>", TEXT, "unsupported_media_type"),
        (b"<!DOCTYPE\thtml>", TEXT, "unsupported_media_type"),
        (b"<svg onload=x>", "image/svg+xml", "unsupported_media_type"),
        (b"<?xml version='1.0'?><a/>", TEXT, "unsupported_media_type"),
        (b"\x89PNG\r\n\x1a\n", "image/png", "unsupported_media_type"),
        (_zip({"a.txt": b"x"}), DOCX, "archive_refused"),
        (b"", TEXT, "empty_file"),
    ],
)
def test_an_upload_of_another_type_is_refused(data: bytes, claimed: str, code: str) -> None:
    with pytest.raises(ParseError) as caught:
        accepted_type(data, claimed, _LIMITS)
    assert caught.value.code == code
