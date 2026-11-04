# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Knowledge API schemas (ADR 0014; RAG-03.01). Names are user text: clients show them as text."""

from __future__ import annotations

import unicodedata
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from neuron_agent.schemas.agent import plain_title


class KnowledgeBaseCreate(BaseModel):
    """`POST /v1/knowledge/bases` body."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=200)
    # Where the base's text may be embedded (RAG-02.03); the operator's policy can still forbid
    # `hosted`, which then fails ingestion with `processing_locality_forbidden`.
    processing: Literal["hosted", "self_hosted"] = "hosted"

    @field_validator("name")
    @classmethod
    def _plain_name(cls, value: str) -> str:
        return plain_title(value)


class KnowledgeBaseUpdate(BaseModel):
    """`PATCH /v1/knowledge/bases/{kb_id}` body: a rename."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=200)

    @field_validator("name")
    @classmethod
    def _plain_name(cls, value: str) -> str:
        return plain_title(value)


class KnowledgeBase(BaseModel):
    kb_id: uuid.UUID
    name: str
    processing: Literal["hosted", "self_hosted"]
    created_at: datetime


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
