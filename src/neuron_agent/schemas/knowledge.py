# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Knowledge API schemas (ADR 0014; RAG-03.01). Names are user text: clients show them as text."""

from __future__ import annotations

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


class KnowledgeBasesResponse(BaseModel):
    """The caller's live knowledge bases, oldest first (at most the per-user limit)."""

    bases: list[KnowledgeBase]
