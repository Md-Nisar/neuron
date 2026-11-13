# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Knowledge API schemas (ADR 0014; RAG-03.01). Names are user text: clients show them as text."""

from __future__ import annotations

import unicodedata
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

# A base's text search language (RAG-09.08): a built-in Postgres text search configuration,
# fixed at creation because every chunk's `tsv` is built with it. `simple` (the default) folds
# case without stemming, so it suits any language; a named one also stems and drops stop words.
KnowledgeLanguage = Literal[
    "simple", "arabic", "armenian", "basque", "catalan", "danish", "dutch", "english",
    "finnish", "french", "german", "greek", "hindi", "hungarian", "indonesian", "irish",
    "italian", "lithuanian", "nepali", "norwegian", "portuguese", "romanian", "russian",
    "serbian", "spanish", "swedish", "tamil", "turkish", "yiddish",
]  # fmt: skip


def _plain_title(value: str) -> str:
    # Imported here: `schemas.agent` imports this module for the data-rights responses.
    from neuron_agent.schemas.agent import plain_title

    return plain_title(value)


class KnowledgeBaseCreate(BaseModel):
    """`POST /v1/knowledge/bases` body."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=200)
    # Where the base's text may be embedded (RAG-02.03); the operator's policy can still forbid
    # `hosted`, which then fails ingestion with `processing_locality_forbidden`.
    processing: Literal["hosted", "self_hosted"] = "hosted"
    language: KnowledgeLanguage = "simple"

    @field_validator("name")
    @classmethod
    def _plain_name(cls, value: str) -> str:
        return _plain_title(value)


class KnowledgeBaseUpdate(BaseModel):
    """`PATCH /v1/knowledge/bases/{kb_id}` body: a rename."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=200)

    @field_validator("name")
    @classmethod
    def _plain_name(cls, value: str) -> str:
        return _plain_title(value)


# A role as the token carries it (RAG-09.02): no control characters, no outer spaces.
_ROLE_PATTERN = r"^[^\x00-\x1f\x7f\s](?:[^\x00-\x1f\x7f]*[^\x00-\x1f\x7f\s])?$"
MAX_ROLE_GRANTS = 50


class KnowledgeGrant(BaseModel):
    """One role grant on a base (RAG-09.03)."""

    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1, max_length=200, pattern=_ROLE_PATTERN)
    access: Literal["read", "write", "admin"]

    @field_validator("role")
    @classmethod
    def _visible(cls, value: str) -> str:
        # Unicode controls, format (zero-width, bidi) and unassigned characters too: the role is
        # shown in the editor and written to the audit log.
        if any(unicodedata.category(char).startswith("C") for char in value):
            raise ValueError("the role has an invisible or control character")
        return value


class KnowledgeGrants(BaseModel):
    """`GET` and `PUT /v1/knowledge/bases/{kb_id}/grants`: every role grant of the base. A `PUT`
    replaces them all; a role left out loses its access. The owner's own access is not listed and
    cannot be changed."""

    model_config = ConfigDict(extra="forbid")

    grants: list[KnowledgeGrant] = Field(max_length=MAX_ROLE_GRANTS)

    @field_validator("grants")
    @classmethod
    def _one_per_role(cls, value: list[KnowledgeGrant]) -> list[KnowledgeGrant]:
        if len({grant.role for grant in value}) != len(value):
            raise ValueError("each role may appear once")
        return value


class KnowledgeBase(BaseModel):
    kb_id: uuid.UUID
    name: str
    processing: Literal["hosted", "self_hosted"]
    language: KnowledgeLanguage
    created_at: datetime
    # The caller's access (RAG-09.03), so a client offers only what the server would allow:
    # `owner` alone deletes the base; `admin` renames it and manages its grants.
    access: Literal["owner", "admin", "write", "read"]


DocumentStatus = Literal["queued", "parsing", "embedding", "ready", "failed"]


class KnowledgeDocument(BaseModel):
    """A document's metadata and processing status. `title` is user text."""

    doc_id: uuid.UUID
    kb_id: uuid.UUID
    title: str
    mime_type: str
    size_bytes: int
    page_count: int | None
    # The stage: `queued`, `parsing`, `embedding`, then `ready` or `failed` (RAG-02.04).
    status: DocumentStatus
    # A stable code when `failed` (README, "Knowledge files"); never a message.
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentsResponse(BaseModel):
    """A page of a knowledge base's live documents, oldest first."""

    documents: list[KnowledgeDocument]
    total: int
    limit: int
    offset: int


class ExportedKnowledgeBase(KnowledgeBase):
    """A live base in the caller's data export, with its live documents' metadata (RAG-07.01).
    File contents are not exported; each file downloads through its own route."""

    documents: list[KnowledgeDocument]


class KnowledgeErasureResponse(BaseModel):
    """`DELETE /v1/me/knowledge`: the caller's bases and documents tombstoned now, and whether
    any of their rows or files is still stored. The worker's purge removes them; until it has,
    `complete` is false, and repeating the request is safe (RAG-07.01)."""

    erased_base_count: int
    erased_document_count: int
    purge_pending: bool

    @computed_field  # type: ignore[prop-decorator]
    @property
    def complete(self) -> bool:
        return not self.purge_pending


class DocumentAccepted(BaseModel):
    """`202` for an upload: a new document, the first one of a repeated `Idempotency-Key`, or
    the base's existing copy of the same content. Poll `status_url` for its status."""

    doc_id: uuid.UUID
    kb_id: uuid.UUID
    status: DocumentStatus
    status_url: str


TITLE_MAX = 300


def document_title(title: str | None, filename: str | None) -> str:
    """A given title, else the file name without its folders, else a default. Raises ValueError
    for a given title that is not plain text of 1 to 300 characters."""
    if title is not None:
        if any(unicodedata.category(c)[0] == "C" for c in title if c not in "\t\n\r"):
            raise ValueError("title contains control or invisible characters")
        text = " ".join(title.split())
        if not 1 <= len(text) <= TITLE_MAX:
            raise ValueError(f"title must be 1 to {TITLE_MAX} characters")
        return text
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if unicodedata.category(c)[0] != "C")
    return " ".join(name.split())[:TITLE_MAX] or "Untitled document"


class KnowledgeBasesResponse(BaseModel):
    """The caller's live knowledge bases, oldest first (at most the per-user limit)."""

    bases: list[KnowledgeBase]


class ChunkPassage(BaseModel):
    """A passage of a document's extracted text, shown as text: never the original markup."""

    chunk_id: uuid.UUID
    ordinal: int
    text: str
    headings: list[str]
    page_start: int | None
    page_end: int | None


class KnowledgeChunk(ChunkPassage):
    """`GET /v1/knowledge/documents/{doc_id}/chunks/{chunk_id}`: the passage behind a citation
    and, on request, its neighbours in document order (RAG-03.04)."""

    doc_id: uuid.UUID
    kb_id: uuid.UUID
    neighbours: list[ChunkPassage]


class KnowledgeSearchRequest(BaseModel):
    """`POST /v1/knowledge/search` body (RAG-03.05). `kb_ids` narrows the search to those of the
    caller's bases; an id that is not one of them is ignored, as an unknown one is."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=500)
    kb_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=10)
    limit: int = Field(default=5, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class KnowledgeSearchHit(ChunkPassage):
    """A passage found by search, as text. `title` is user text; `score` orders hits only."""

    doc_id: uuid.UUID
    kb_id: uuid.UUID
    title: str
    score: float


class KnowledgeSearchResponse(BaseModel):
    """The best passages first; `no_relevant_results` when there are none."""

    status: Literal["ok", "no_relevant_results"]
    results: list[KnowledgeSearchHit]
    # True when a reranker ordered the results (RAG-09.01); false with none or after a fallback.
    reranked: bool = False
