"""Typed API and structured-output schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AgentRequest(BaseModel):
    """Agent invocation request."""

    model_config = ConfigDict(extra="forbid")

    # max_length is the absolute ceiling (matches Settings.max_prompt_chars upper
    # bound); the actually configured limit is enforced by validate_user_message.
    message: str = Field(min_length=1, max_length=200_000)
    thread_id: str | None = Field(default=None, max_length=255)
    user_id: str | None = Field(default=None, max_length=128)

    @field_validator("thread_id")
    @classmethod
    def require_uuid_thread_id(cls, value: str | None) -> str | None:
        """Thread IDs are server-minted UUIDs; normalize to the canonical lowercase form."""
        if value is None:
            return None
        try:
            return str(uuid.UUID(value))
        except ValueError as exc:
            raise ValueError("thread_id must be a UUID") from exc


class AgentAnswer(BaseModel):
    """Structured response contract for application consumers."""

    answer: str = Field(min_length=1)
    used_tools: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class AgentResponse(BaseModel):
    """HTTP response payload."""

    request_id: str
    thread_id: str
    answer: str
    used_tools: list[str]
    confidence: float


class ThreadMessage(BaseModel):
    """One conversation turn as exposed to clients."""

    role: Literal["user", "assistant"]
    content: str


class ThreadHistoryResponse(BaseModel):
    """A page of a thread's conversation, oldest first."""

    thread_id: str
    messages: list[ThreadMessage]
    total: int
    limit: int
    offset: int


class UserThreadSummary(BaseModel):
    """Privacy-safe thread listing item without conversation content."""

    thread_id: str
    created_at: datetime
    updated_at: datetime
    message_count: int


class UserThreadsResponse(BaseModel):
    """One page of the authenticated caller's thread summaries."""

    threads: list[UserThreadSummary]
    total: int
    limit: int
    offset: int


class ExportedThread(BaseModel):
    """A thread page in a caller's data export."""

    thread_id: str
    created_at: datetime
    updated_at: datetime
    message_total: int
    messages: list[ThreadMessage]


class UserDataExportResponse(BaseModel):
    """Paginated conversation export, with independent thread/message offsets."""

    threads: list[ExportedThread]
    total_threads: int
    limit: int
    offset: int
    message_limit: int
    message_offset: int
    has_more_messages: bool


class UserDataErasureResponse(BaseModel):
    """Result of an idempotent erase-all request."""

    erased_count: int
    skipped_busy_count: int
