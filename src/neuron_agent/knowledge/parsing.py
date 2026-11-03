# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Document parsing for ingestion (ADR 0014 K2; RAG-02.02).

Every uploaded file is untrusted. `check_input` runs before any parser sees the bytes: it sniffs
the real type from the content, enforces the byte cap, and refuses encrypted PDFs, archives,
macro-enabled Office files and zip bombs. A parser returns a `ParsedDocument`, which
`validate_output` checks against the schema and the page and character caps, so a parser bug or
a hostile file cannot hand the pipeline more than it allows. Errors carry a stable `code` (the
document's `error_code`) and never file content or a file name.

`PlainTextParser` handles `.txt` and `.md` in the worker. Plain text has no page provenance, so
form feeds (RFC-style page breaks) split pages; without one, blocks have no page.
"""

from __future__ import annotations

import asyncio
import io
import re
import struct
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Annotated, Literal, Protocol
from urllib.parse import unquote

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import AppError, ErrorContext

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
TEXT = "text/plain"
MARKDOWN = "text/markdown"
SUPPORTED = frozenset({PDF, DOCX, XLSX, PPTX, TEXT, MARKDOWN})
# The main part's content type: exactly the non-macro, non-template document for each format.
_OOXML_MAIN = {kind: f'ContentType="{kind}.main+xml"'.encode() for kind in (DOCX, XLSX, PPTX)}
# Active content, by content type or part name (lowercased, percent-decoded).
_OOXML_ACTIVE = (b"vbaproject", b"macroenabled", b"macrosheet", b"activex")

# A zip's directory and sizes are attacker-written; these bound what a parser would inflate.
_MAX_ZIP_MEMBERS = 10_000
_MAX_COMPRESSION_RATIO = 100
_MAX_INFLATE_FACTOR = 4  # inflated size, as a multiple of the byte cap
_MAX_CONTENT_TYPES_BYTES = 1_000_000
_BLOCKS_PER_PAGE = 200  # the block cap is this times the page cap


def _pdf_name(name: str) -> bytes:
    """A regex for a PDF name in any spelling: each character may be written as `#xx`."""
    spelled = b"".join(
        b"(?:" + re.escape(char.encode()) + b"|#(?i:" + f"{ord(char):02x}".encode() + b"))"
        for char in name
    )
    return b"/" + spelled + rb"(?=[\x00\s/<>\[\]()%{}]|\Z)"


_ENCRYPT = re.compile(_pdf_name("Encrypt"))


class ParseError(AppError):
    """Parsing refused or failed. `retryable` is False for anything a retry cannot change."""

    context = ErrorContext(code="parse_error", http_status=422, user_visible=False)

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


_Coordinate = Annotated[float, Field(allow_inf_nan=False)]


class Block(BaseModel):
    """One unit of extracted text, in reading order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["heading", "text", "table", "list", "code"]
    # No NUL: Postgres text cannot store it.
    text: str = Field(min_length=1, pattern=r"^[^\x00]*$")
    # 1-based; None where the format has no pages (Markdown, text without form feeds).
    page: int | None = Field(default=None, ge=1)
    level: int | None = Field(default=None, ge=1, le=6)  # headings only
    bbox: tuple[_Coordinate, _Coordinate, _Coordinate, _Coordinate] | None = None


class ParsedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    parser_version: str = Field(min_length=1, max_length=64)
    page_count: int | None = Field(default=None, ge=1)
    blocks: tuple[Block, ...] = Field(min_length=1)


@dataclass(frozen=True)
class Limits:
    max_bytes: int
    max_pages: int
    max_page_chars: int

    @property
    def max_blocks(self) -> int:
        return self.max_pages * _BLOCKS_PER_PAGE

    @property
    def max_chars(self) -> int:
        return self.max_pages * self.max_page_chars

    @classmethod
    def from_settings(cls, settings: Settings) -> Limits:
        return cls(
            max_bytes=settings.knowledge_parse_max_bytes,
            max_pages=settings.knowledge_parse_max_pages,
            max_page_chars=settings.knowledge_parse_max_page_chars,
        )


class DocumentParser(Protocol):
    """Turns checked bytes of one supported media type into a validated `ParsedDocument`.

    Called only through `parse_document`, which runs `check_input` first.
    """

    media_types: frozenset[str]

    async def parse(self, data: bytes, media_type: str, limits: Limits) -> ParsedDocument: ...


async def parse_document(
    data: bytes, declared: str, limits: Limits, parsers: Iterable[DocumentParser]
) -> ParsedDocument:
    """The one entry point: check the bytes, then parse them with the parser for their type."""
    media_type = await asyncio.to_thread(check_input, data, declared, limits)
    for parser in parsers:
        if media_type in parser.media_types:
            return await parser.parse(data, media_type, limits)
    raise ParseError("unsupported_media_type")


def sniff(data: bytes) -> str | None:
    """The media type the content itself shows, or None when it is not one Neuron supports.

    Text is told apart from Markdown by the declared type only, in `check_input`.
    """
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"PK\x03\x04"):
        return "application/zip"
    if b"\x00" in data:
        return None
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return TEXT


def check_input(data: bytes, declared: str, limits: Limits) -> str:
    """Return the media type to parse as, or raise `ParseError` before any parser runs."""
    if not data:
        raise ParseError("empty_file")
    if len(data) > limits.max_bytes:
        raise ParseError("file_too_large")
    if declared not in SUPPORTED:
        raise ParseError("unsupported_media_type")
    sniffed = sniff(data)
    if sniffed == PDF and declared == PDF:
        # The trailer, or a cross-reference stream's dictionary (never compressed), names the
        # Encrypt dictionary, which may not sit in an object stream (ISO 32000-1 7.5.7, 7.5.8),
        # so a conforming encrypted PDF shows the name in its raw bytes, in some spelling. With
        # an empty user password a parser could still read it, so the file is refused. The same
        # bytes inside a content stream refuse a readable file: failing closed.
        if _ENCRYPT.search(data):
            raise ParseError("encrypted_pdf")
        return PDF
    if sniffed == "application/zip":
        _check_office_zip(data, declared, limits)
        return declared
    if sniffed == TEXT and declared in {TEXT, MARKDOWN}:
        return declared
    raise ParseError("media_type_mismatch")


def _zip_entries(data: bytes) -> int:
    """An upper bound on the entries, from the end-of-central-directory record, before parsing.

    The larger of the declared count and what the directory's size could hold (46 bytes is the
    smallest entry), so a record that understates the count is still caught.
    """
    eocd = data.rfind(b"PK\x05\x06", max(0, len(data) - 65_557))
    if eocd < 0 or len(data) < eocd + 22:
        raise ParseError("archive_refused")
    entries, directory_size = struct.unpack_from("<HI", data, eocd + 10)
    return max(int(entries), int(directory_size) // 46)  # 0xFFFF (ZIP64) is over the cap


def _check_office_zip(data: bytes, declared: str, limits: Limits) -> None:
    """An OOXML file is a zip; any other zip, active content or a zip bomb is refused.

    Sizes come from the zip's directory, which the uploader wrote. They bound what a reader that
    honours them (Python's `zipfile`, docling) would inflate; the parser runs in its own
    container all the same.
    """
    main = _OOXML_MAIN.get(declared)
    if main is None:
        raise ParseError("archive_refused")
    if _zip_entries(data) > _MAX_ZIP_MEMBERS:
        raise ParseError("decompression_limit")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > _MAX_ZIP_MEMBERS:
                raise ParseError("decompression_limit")
            _check_members(members, len(data), limits)
            if "[Content_Types].xml" not in {member.filename for member in members}:
                raise ParseError("archive_refused")
            with archive.open("[Content_Types].xml") as file:
                content_types = file.read(_MAX_CONTENT_TYPES_BYTES + 1)
    except (zipfile.BadZipFile, ValueError, EOFError, NotImplementedError):
        raise ParseError("archive_refused") from None
    if len(content_types) > _MAX_CONTENT_TYPES_BYTES:
        raise ParseError("decompression_limit")
    # Character references, a DTD's entities or another encoding (UTF-16 has NULs) could spell a
    # content type the byte checks below would not see; without them, bytes read as the XML does.
    if any(token in content_types for token in (b"&#", b"<!", b"\x00")):
        raise ParseError("archive_refused")
    names = b"\n".join(unquote(m.filename).lower().encode() for m in members)
    if any(marker in content_types.lower() or marker in names for marker in _OOXML_ACTIVE):
        raise ParseError("macro_refused")
    if main not in content_types:
        raise ParseError("media_type_mismatch")


def _check_members(members: list[zipfile.ZipInfo], size: int, limits: Limits) -> None:
    # Two names one reader may treat as the same part (case, %xx, a leading slash) are refused:
    # this check and the parser must see the same file.
    normalised = {unquote(m.filename).replace("\\", "/").lstrip("/").casefold() for m in members}
    if len(normalised) != len(members):
        raise ParseError("archive_refused")
    for member in members:
        if member.flag_bits & 0x1:
            raise ParseError("archive_refused")  # an encrypted member
        if member.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise ParseError("archive_refused")  # Office uses only these two
        if member.file_size > limits.max_bytes:
            raise ParseError("decompression_limit")
    inflated = sum(member.file_size for member in members)
    if (
        inflated > _MAX_COMPRESSION_RATIO * size
        or inflated > _MAX_INFLATE_FACTOR * limits.max_bytes
    ):
        raise ParseError("decompression_limit")


def validate_output(raw: object, limits: Limits) -> ParsedDocument:
    """Check a parser's output against the schema and the page, block and character caps."""
    if isinstance(raw, dict) and len(raw.get("blocks") or ()) > limits.max_blocks:
        raise ParseError("too_many_blocks")
    try:
        document = ParsedDocument.model_validate(raw)
    except ValidationError:
        raise ParseError("parser_output_invalid") from None
    if len(document.blocks) > limits.max_blocks:
        raise ParseError("too_many_blocks")
    pages = {block.page for block in document.blocks if block.page is not None}
    page_count = document.page_count or 0
    if max(page_count, len(pages)) > limits.max_pages:
        raise ParseError("too_many_pages")
    if any(page > page_count for page in pages):
        raise ParseError("parser_output_invalid")
    chars: dict[int | None, int] = {}
    for block in document.blocks:
        chars[block.page] = chars.get(block.page, 0) + len(block.text)
    if sum(chars.values()) > limits.max_chars:
        raise ParseError("page_too_long")
    if any(count > limits.max_page_chars for page, count in chars.items() if page is not None):
        raise ParseError("page_too_long")
    return document


# Linear: no backtracking tail. Trailing `#`s and spaces are stripped with str.rstrip.
_HEADING = re.compile(r"(#{1,6})[ \t]+(\S.*)")
_FENCE = re.compile(r"(```|~~~)")


class PlainTextParser:
    """`.txt` and `.md` in the worker, without docling-serve."""

    media_types = frozenset({TEXT, MARKDOWN})
    version = "plain-text/1"

    async def parse(self, data: bytes, media_type: str, limits: Limits) -> ParsedDocument:
        return await asyncio.to_thread(self._parse, data, media_type, limits)

    def _parse(self, data: bytes, media_type: str, limits: Limits) -> ParsedDocument:
        try:
            text = data.decode("utf-8-sig").replace("\r\n", "\n")
        except UnicodeDecodeError:
            raise ParseError("media_type_mismatch") from None
        # Counted before splitting, so a form-feed bomb builds nothing.
        page_total = text.count("\f") + 1
        if page_total > limits.max_pages:
            raise ParseError("too_many_pages")
        paged = page_total > 1
        blocks: list[dict[str, object]] = []
        for number, page in enumerate(text.split("\f"), start=1):
            for block in _blocks(page, markdown=media_type == MARKDOWN):
                if len(blocks) == limits.max_blocks:
                    raise ParseError("too_many_blocks")
                blocks.append({**block, "page": number if paged else None})
        return validate_output(
            {
                "parser_version": self.version,
                "page_count": page_total if paged else None,
                "blocks": blocks,
            },
            limits,
        )


def _flush(paragraph: list[str], kind: str = "text") -> Iterator[dict[str, object]]:
    body = "\n".join(paragraph).strip()
    paragraph.clear()
    if body:
        yield {"kind": kind, "text": body}


def _heading(line: str) -> dict[str, object] | None:
    match = _HEADING.fullmatch(line.rstrip())
    title = match[2].rstrip(" \t#") if match else ""
    return {"kind": "heading", "text": title, "level": len(match[1])} if match and title else None


def _blocks(page: str, *, markdown: bool) -> Iterator[dict[str, object]]:
    paragraph: list[str] = []
    fenced = False
    for line in page.split("\n"):
        if markdown and _FENCE.match(line):
            # An opening fence ends the paragraph before it; a closing one ends the code block.
            if fenced:
                paragraph.append(line)
            yield from _flush(paragraph, "code" if fenced else "text")
            if not fenced:
                paragraph.append(line)
            fenced = not fenced
        elif fenced:
            paragraph.append(line)
        elif markdown and (heading := _heading(line)):
            yield from _flush(paragraph)
            yield heading
        elif not line.strip():
            yield from _flush(paragraph)
        else:
            paragraph.append(line)
    yield from _flush(paragraph, "code" if fenced else "text")
