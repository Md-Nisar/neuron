"""Typed API and structured-output schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentRequest(BaseModel):
    """Agent invocation request."""

    message: str = Field(min_length=1, max_length=12_000)
    thread_id: str | None = Field(default=None, max_length=255)
    user_id: str | None = Field(default=None, max_length=128)


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
