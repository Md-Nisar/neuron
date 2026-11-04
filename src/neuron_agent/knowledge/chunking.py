# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Chunks from a parsed document, following its headings (ADR 0014; RAG-02.04).

Every parser returns the same `ParsedDocument`, so one chunker serves PDF, Office, Markdown and
text. A heading closes the chunk before it and sets the heading path of the ones after it;
blocks under one heading fill a chunk up to `max_tokens`, and a block too long for one chunk is
split at line breaks, then spaces, then characters. Tokens are estimated, not counted: the
worker has no tokenizer file and no egress to fetch one. One token per three UTF-8 bytes is above
what embedding tokenizers count for Latin-script text (about four bytes a token); a CJK
character can be more than one token, which the default leaves room for below the model's
context.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass

from neuron_agent.knowledge.parsing import ParsedDocument

_BYTES_PER_TOKEN = 3
_MAX_HEADING_CHARS = 300  # a heading is stored on every chunk under it
_JOIN = "\n\n"
_LINES = re.compile(r"[^\n]*\n|[^\n]+")
_WORDS = re.compile(r"\S+\s*|\s+")


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    text: str
    headings: tuple[str, ...]
    page_start: int | None
    page_end: int | None
    token_count: int


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text.encode("utf-8")) / _BYTES_PER_TOKEN)


def chunk_document(document: ParsedDocument, max_tokens: int) -> list[Chunk]:
    """The document's chunks in reading order, each at most `max_tokens` (estimated)."""
    budget = max_tokens * _BYTES_PER_TOKEN
    chunks: list[Chunk] = []
    path: list[tuple[int, str]] = []
    pending: list[tuple[str, int | None]] = []
    size = 0  # UTF-8 bytes of the pending text joined

    def flush() -> None:
        nonlocal size
        if pending:
            pages = [page for _, page in pending if page is not None]
            text = _JOIN.join(text for text, _ in pending)
            chunks.append(
                Chunk(
                    ordinal=len(chunks),
                    text=text,
                    headings=tuple(heading for _, heading in path),
                    page_start=min(pages, default=None),
                    page_end=max(pages, default=None),
                    token_count=estimate_tokens(text),
                )
            )
            pending.clear()
            size = 0

    for block in document.blocks:
        if block.kind == "heading":
            flush()
            level = block.level or 1
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, block.text[:_MAX_HEADING_CHARS]))
            continue
        for piece in _pieces(block.text, budget):
            length = len(piece.encode("utf-8"))
            if pending and size + len(_JOIN) + length > budget:
                flush()
            size += (len(_JOIN) if pending else 0) + length
            pending.append((piece, block.page))
    flush()
    return chunks


def _pieces(text: str, budget: int) -> Iterator[str]:
    """The text, or parts of it that each fit `budget` bytes."""
    if len(text.encode("utf-8")) <= budget:
        yield text
        return
    for part in _split(text, budget, (_LINES, _WORDS)):
        if part := part.strip():
            yield part


def _split(text: str, budget: int, patterns: tuple[re.Pattern[str], ...]) -> Iterator[str]:
    """Greedy: whole units of the first pattern while they fit, finer ones for a unit that does
    not, and single characters last (one character is at most 4 bytes, below any budget)."""
    units = patterns[0].findall(text) if patterns else list(text)
    current: list[str] = []
    size = 0
    for unit in units:
        length = len(unit.encode("utf-8"))
        if size + length <= budget:
            current.append(unit)
            size += length
            continue
        if current:
            yield "".join(current)
            current, size = [], 0
        if length <= budget:
            current, size = [unit], length
        else:
            yield from _split(unit, budget, patterns[1:])
    if current:
        yield "".join(current)
