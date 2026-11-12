# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Embedding provider and processing locality (ADR 0014 K3, K8; RAG-02.03).

`EmbeddingProvider` wraps LangChain `Embeddings` with what ingestion and retrieval need to trust
the vectors before anything is written: batching, a count, dimension and finite-value check, and
retries for transient provider failures only. Errors carry a stable `code` and never the
provider's message, which can echo request text.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Awaitable, Callable, Sequence
from functools import partial

import openai
import structlog
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from neuron_agent.config.settings import ProcessingLocality, ProcessingPolicy, Settings
from neuron_agent.errors.base import AppError, ConfigurationError, ErrorContext
from neuron_agent.persistence.migrations import KnowledgeProfile

logger = structlog.get_logger(__name__)

# The same endpoint the chat model factory uses (`models/factory.py`).
_NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

# Retried with backoff; anything else from the provider is terminal. An exhausted account is
# reported as a 429 too, but it never clears on retry.
_RETRYABLE = (
    openai.APIConnectionError,  # includes APITimeoutError
    openai.RateLimitError,
    openai.InternalServerError,
)
_QUOTA_MARKERS = frozenset({"insufficient_quota", "credit_balance_exhausted"})
_BACKOFF_BASE_SECONDS = 0.5
_BACKOFF_MAX_SECONDS = 8.0


class EmbeddingError(AppError):
    """Embedding failed; `code` is the stable value stored as a document's `error_code`."""

    context = ErrorContext(code="embedding_error", http_status=502, user_visible=False)

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


def ensure_processing_allowed(
    kb_processing: ProcessingLocality,
    provider_locality: ProcessingLocality,
    policy: ProcessingPolicy,
) -> None:
    """Refuse to embed a knowledge base's text where its setting or the policy forbids it."""
    if provider_locality == "self_hosted":
        return
    if kb_processing == "hosted" and policy == "allow_hosted":
        return
    raise EmbeddingError("processing_locality_forbidden")


class EmbeddingProvider:
    """Validated, batched and retried embeddings for one index profile's dimensions."""

    def __init__(
        self,
        documents: Embeddings,
        queries: Embeddings,
        *,
        dimensions: int,
        locality: ProcessingLocality,
        batch_size: int,
        max_retries: int,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        profile: KnowledgeProfile | None = None,
    ) -> None:
        self._documents = documents
        self._queries = queries
        self.dimensions = dimensions
        # The index profile these vectors belong to; unset, the default model at `dimensions`.
        self.profile = profile or KnowledgeProfile(dimensions=dimensions)
        if self.profile.dimensions != dimensions:
            raise ValueError("the profile's dimensions differ from the provider's")
        self.locality = locality
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._sleep = sleep

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed passages. All batches are checked before any vector is returned."""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = list(texts[start : start + self._batch_size])
            result = await self._call(partial(self._documents.aembed_documents, batch))
            vectors.extend(self._checked(result, expected=len(batch)))
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        """Embed a search query (NVIDIA models embed queries and passages differently)."""
        result = await self._call(lambda: self._queries.aembed_query(text))
        return self._checked([result], expected=1)[0]

    async def _call[T](self, request: Callable[[], Awaitable[T]]) -> T:
        for attempt in range(self._max_retries + 1):
            # The error is raised outside the `except` block, so the provider's exception (whose
            # message and body can echo document text) is not even kept as `__context__`.
            try:
                return await request()
            except _RETRYABLE as exc:
                if _is_quota(exc):
                    error = EmbeddingError("embedding_quota_exhausted")
                elif attempt == self._max_retries:
                    error = EmbeddingError("embedding_provider_unavailable", retryable=True)
                else:
                    logger.warning(
                        "embedding_retry", error_type=type(exc).__name__, retry_attempt=attempt + 1
                    )
                    continue_after = min(_BACKOFF_BASE_SECONDS * 2**attempt, _BACKOFF_MAX_SECONDS)
                    error = None
            except openai.APIStatusError:
                # 400, 401, 403, 404, 422: the same request can never succeed.
                error = EmbeddingError("embedding_provider_rejected")
            except Exception:  # noqa: BLE001 - parsing and client errors can echo the text
                error = EmbeddingError("embedding_provider_error")
            if error is not None:
                raise error
            await self._sleep(continue_after)
        raise AssertionError("unreachable")  # pragma: no cover

    def _checked(self, vectors: list[list[float]], *, expected: int) -> list[list[float]]:
        if len(vectors) != expected:
            raise EmbeddingError("embedding_count_mismatch")
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise EmbeddingError("embedding_dimension_mismatch")
            if not all(math.isfinite(value) for value in vector):
                raise EmbeddingError("embedding_non_finite")
        return vectors


class FakeEmbeddings(Embeddings):
    """Deterministic unit vectors from a hash of the text; no network, no numpy."""

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        digest = b""
        counter = 0
        while len(digest) < self.dimensions:
            digest += hashlib.sha256(f"{counter}:{text}".encode()).digest()
            counter += 1
        values = [byte / 255.0 - 0.5 for byte in digest[: self.dimensions]]
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]


def _is_quota(exc: Exception) -> bool:
    return isinstance(exc, openai.RateLimitError) and bool(_QUOTA_MARKERS & {exc.code, exc.type})


def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Build the configured provider; the fake one in development/test without credentials."""
    provider = settings.knowledge_embedding_provider
    dimensions = settings.knowledge_embedding_dimensions
    if provider == "nvidia":
        api_key = settings.provider_api_key("nvidia")
        base_url: str | None = _NVIDIA_BASE_URL
    else:
        api_key = settings.knowledge_embedding_api_key
        base_url = settings.knowledge_embedding_base_url
    if provider == "fake" or (
        provider == "nvidia" and api_key is None and settings.env in {"development", "test"}
    ):
        fake = FakeEmbeddings(dimensions)
        return _provider(settings, fake, fake, "self_hosted")
    if provider == "nvidia" and api_key is None:
        raise ConfigurationError("NVIDIA_API_KEY is required for the nvidia embedding provider")

    def client(input_type: str) -> OpenAIEmbeddings:
        options: dict[str, object] = {}
        if provider == "nvidia":
            # NVIDIA's API refuses a request without `input_type`.
            options["model_kwargs"] = {"extra_body": {"input_type": input_type}}
        return OpenAIEmbeddings(
            model=settings.knowledge_embedding_model,
            openai_api_base=base_url,
            # The client refuses to start without a key; a keyless self-hosted server ignores it.
            openai_api_key=api_key or SecretStr("unused"),
            dimensions=dimensions,
            # Send raw text: tiktoken counts are not this model's tokens.
            check_embedding_ctx_length=False,
            chunk_size=settings.knowledge_embedding_batch_size_effective,
            request_timeout=settings.knowledge_embedding_timeout_seconds,
            max_retries=0,
            **options,
        )

    return _provider(
        settings,
        client("passage"),
        client("query"),
        settings.knowledge_embedding_locality_effective,
    )


def _provider(
    settings: Settings, documents: Embeddings, queries: Embeddings, locality: ProcessingLocality
) -> EmbeddingProvider:
    return EmbeddingProvider(
        documents,
        queries,
        dimensions=settings.knowledge_embedding_dimensions,
        locality=locality,
        batch_size=settings.knowledge_embedding_batch_size_effective,
        max_retries=settings.knowledge_embedding_max_retries,
        profile=KnowledgeProfile(
            provider=settings.knowledge_embedding_provider,
            model=settings.knowledge_embedding_model,
            dimensions=settings.knowledge_embedding_dimensions,
        ),
    )


def create_reindex_embedding_provider(settings: Settings) -> EmbeddingProvider | None:
    """The re-index model's provider (RAG-09.04), or None when no re-index model is set."""
    reindex = settings.knowledge_reindex_settings()
    return None if reindex is None else create_embedding_provider(reindex)


def provider_for(
    profile: KnowledgeProfile, *providers: EmbeddingProvider | None
) -> EmbeddingProvider | None:
    """The configured provider that embeds into `profile`'s vector space, if any."""
    return next((p for p in providers if p is not None and p.profile == profile), None)
