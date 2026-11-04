# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""PDF and Office parsing through docling-serve (ADR 0014 K2; RAG-02.02).

The worker posts the file's bytes, never a URL, to docling-serve's `/v1/convert/file` and asks
for Docling's JSON. The call has a total deadline and a cap on the response size, and the reply
is read as untrusted input: only the fields used here are validated, then `validate_output`
applies the same schema and caps as every other parser. docling-serve runs without network
egress (reference stack), so the models in its image are all it has.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Annotated, Literal

import anyio
import httpx2
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from neuron_agent.config.settings import Settings
from neuron_agent.knowledge.parsing import (
    DOCX,
    PDF,
    PPTX,
    XLSX,
    Limits,
    ParsedDocument,
    ParseError,
    validate_output,
)

_CONVERT = "/v1/convert/file"
# Running heads and page numbers repeat on every page; they are not content.
_SKIPPED = frozenset({"page_header", "page_footer"})
_KINDS = {"list_item": "list", "code": "code"}
# One spelling per item, so a reply cannot alias an item under many references.
_REF = re.compile(r"#/(texts|tables|groups|pictures)/(0|[1-9][0-9]{0,8})")
# Transient: the service is down, busy or restarting. A 500 or a reset mid-reply is not
# retried, because a file that crashes the converter would crash it again.
_RETRYABLE_STATUS = frozenset({408, 429, 502, 503, 504})
_Coordinate = Annotated[float, Field(allow_inf_nan=False)]


class _Box(BaseModel):
    l: _Coordinate  # noqa: E741 - Docling's names
    t: _Coordinate
    r: _Coordinate
    b: _Coordinate
    coord_origin: Literal["TOPLEFT", "BOTTOMLEFT"] = "TOPLEFT"


class _Prov(BaseModel):
    page_no: int = Field(ge=1)
    bbox: _Box | None = None


class _Ref(BaseModel):
    cref: str = Field(alias="$ref")


class _Node(BaseModel):
    children: list[_Ref] = []


class _Text(_Node):
    label: str
    text: str = ""
    level: int = Field(default=1, ge=1, le=100)
    prov: list[_Prov] = []


class _Cell(BaseModel):
    text: str = ""
    start_row_offset_idx: int = Field(ge=0)
    start_col_offset_idx: int = Field(ge=0)


class _TableData(BaseModel):
    table_cells: list[_Cell] = []


class _Table(_Node):
    data: _TableData = _TableData()
    prov: list[_Prov] = []


class _Size(BaseModel):
    height: _Coordinate


class _Page(BaseModel):
    size: _Size


class _Document(BaseModel):
    """The parts of a `DoclingDocument` this parser reads; anything else is ignored."""

    model_config = ConfigDict(extra="ignore")

    version: str = Field(min_length=1, max_length=16, pattern=r"^[0-9A-Za-z.\-]+$")
    body: _Node
    groups: list[_Node] = []
    texts: list[_Text] = []
    tables: list[_Table] = []
    pictures: list[_Node] = []
    pages: dict[str, _Page] = {}


class _Content(BaseModel):
    json_content: _Document


class _Reply(BaseModel):
    status: str
    document: _Content


class DoclingServeParser:
    """PDF, DOCX, XLSX and PPTX through docling-serve, without OCR models leaving its image."""

    media_types = frozenset({PDF, DOCX, XLSX, PPTX})

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float,
        max_response_bytes: int,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url
        self._timeout = timeout_seconds
        self._max_response = max_response_bytes
        self._transport = transport

    @classmethod
    def from_settings(cls, settings: Settings) -> DoclingServeParser:
        if settings.knowledge_parser_url is None:
            raise ParseError("parser_not_configured")
        return cls(
            settings.knowledge_parser_url,
            timeout_seconds=settings.knowledge_parser_timeout_seconds,
            max_response_bytes=settings.knowledge_parser_max_response_bytes,
        )

    async def parse(self, data: bytes, media_type: str, limits: Limits) -> ParsedDocument:
        try:
            with anyio.fail_after(self._timeout):
                body = await self._convert(data, media_type, limits)
        except TimeoutError:
            # The same file would time out again: the document fails, the job is not retried.
            raise ParseError("parser_timeout") from None
        return await anyio.to_thread.run_sync(self._normalise, body, limits)

    async def _convert(self, data: bytes, media_type: str, limits: Limits) -> bytes:
        form = {
            "to_formats": "json",
            "do_ocr": "true",
            "table_mode": "accurate",
            "image_export_mode": "placeholder",
            # One page past the cap, so a longer document is refused rather than cut short.
            "page_range": ["1", str(limits.max_pages + 1)],
            # docling-serve stops first, so it does not keep converting after the client gives up.
            "document_timeout": str(self._timeout * 0.9),
        }
        async with httpx2.AsyncClient(
            base_url=self._base_url,
            transport=self._transport,
            timeout=httpx2.Timeout(self._timeout),
            trust_env=False,
            follow_redirects=False,
            headers={"Accept-Encoding": "identity"},  # the cap counts the bytes received
        ) as client:
            try:
                async with client.stream(
                    "POST", _CONVERT, data=form, files={"files": ("document", data, media_type)}
                ) as response:
                    if response.status_code in _RETRYABLE_STATUS:
                        raise ParseError("parser_unavailable", retryable=True)
                    if response.status_code != 200:
                        raise ParseError("parser_failed")
                    return await self._read(response)
            except (httpx2.ConnectError, httpx2.ConnectTimeout):
                raise ParseError("parser_unavailable", retryable=True) from None
            except httpx2.TimeoutException:
                raise ParseError("parser_timeout") from None
            except httpx2.HTTPError:
                raise ParseError("parser_failed") from None

    async def _read(self, response: httpx2.Response) -> bytes:
        declared = response.headers.get("content-length", "")
        if re.fullmatch(r"[0-9]{1,18}", declared) and int(declared) > self._max_response:
            raise ParseError("parser_output_too_large")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body += chunk
            if len(body) > self._max_response:
                raise ParseError("parser_output_too_large")
        return bytes(body)

    @staticmethod
    def _normalise(body: bytes, limits: Limits) -> ParsedDocument:
        try:
            reply = _Reply.model_validate_json(body)
        except ValidationError:
            raise ParseError("parser_output_invalid") from None
        if reply.status != "success":
            raise ParseError("parser_failed")  # a partial conversion would cite missing pages
        document = reply.document.json_content
        blocks: list[dict[str, object]] = []
        for block in _walk(document):
            if len(blocks) == limits.max_blocks:
                raise ParseError("too_many_blocks")
            blocks.append(block)
        return validate_output(
            {
                "parser_version": f"docling/{document.version}",
                "page_count": len(document.pages) or None,
                "blocks": blocks,
            },
            limits,
        )


def _walk(document: _Document) -> Iterator[dict[str, object]]:
    """Blocks in reading order: the body's tree of references, depth first, each item once.

    A loop with its own stack, so a hostile reply cannot nest deeper than Python recurses.
    """
    seen: set[tuple[str, int]] = set()
    stack = [iter(document.body.children)]
    while stack:
        child = next(stack[-1], None)
        if child is None:
            stack.pop()
            continue
        key = _key(child.cref)
        if key in seen:
            continue  # a cycle or a repeated reference: each item is expanded once
        seen.add(key)
        item = _resolve(document, key)
        block = None
        if isinstance(item, _Text):
            block = _text_block(document, item)
        elif isinstance(item, _Table):
            block = _table_block(document, item)
        if block is not None:
            yield block
        stack.append(iter(item.children))


def _key(cref: str) -> tuple[str, int]:
    if not (match := _REF.fullmatch(cref)):
        raise ParseError("parser_output_invalid")
    return match[1], int(match[2])


def _resolve(document: _Document, key: tuple[str, int]) -> _Node:
    collection, index = key
    items: dict[str, list[_Text] | list[_Table] | list[_Node]] = {
        "texts": document.texts,
        "tables": document.tables,
        "groups": document.groups,
        "pictures": document.pictures,
    }
    if index >= len(items[collection]):
        raise ParseError("parser_output_invalid")
    return items[collection][index]


def _text_block(document: _Document, item: _Text) -> dict[str, object] | None:
    text = item.text.strip()
    if not text or item.label in _SKIPPED:
        return None
    block: dict[str, object] = {"kind": _KINDS.get(item.label, "text"), "text": text}
    if item.label == "title":
        block |= {"kind": "heading", "level": 1}
    elif item.label == "section_header":
        block |= {"kind": "heading", "level": min(item.level + 1, 6)}
    return block | _where(document, item.prov)


def _table_block(document: _Document, item: _Table) -> dict[str, object] | None:
    rows: dict[int, dict[int, str]] = {}
    for cell in item.data.table_cells:
        rows.setdefault(cell.start_row_offset_idx, {})[cell.start_col_offset_idx] = cell.text
    text = "\n".join(
        " | ".join(row[col].strip() for col in sorted(row)) for _, row in sorted(rows.items())
    ).strip()
    return {"kind": "table", "text": text} | _where(document, item.prov) if text else None


def _where(document: _Document, prov: list[_Prov]) -> dict[str, object]:
    """The first location's page, and its box with the origin at the top left."""
    if not prov:
        return {}
    first = prov[0]
    where: dict[str, object] = {"page": first.page_no}
    box, page = first.bbox, document.pages.get(str(first.page_no))
    if box is not None and box.coord_origin == "TOPLEFT":
        where["bbox"] = (box.l, box.t, box.r, box.b)
    elif box is not None and page is not None:
        where["bbox"] = (box.l, page.size.height - box.t, box.r, page.size.height - box.b)
    return where
