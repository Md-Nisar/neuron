# Copyright 2026 Md Nisar Ahmed
# SPDX-License-Identifier: Apache-2.0

"""Optional rerankers over the fused candidates (ADR 0014 K6; RAG-09.01).

A reranker reorders the passages hybrid search already found for the caller; it never adds one,
so authorisation stays in the retriever's SQL. Errors carry a stable `code` and never the
provider's message, which can echo the query or passages. The retriever falls back to the RRF
order on any error or timeout and says so with `reranked: false`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Protocol

import httpx2
from pydantic import BaseModel, ConfigDict, ValidationError

from neuron_agent.config.settings import ProcessingLocality, Settings
from neuron_agent.errors.base import AppError, ConfigurationError, ErrorContext

# NVIDIA's retrieval API (not the OpenAI-compatible `integrate` host), one path per model.
_NVIDIA_RERANK_URL = "https://ai.api.nvidia.com/v1/retrieval/{model}/reranking"
_MAX_RESPONSE_BYTES = 1_000_000


class RerankError(AppError):
    """Reranking failed; the search keeps its RRF order."""

    context = ErrorContext(code="rerank_error", http_status=502, user_visible=False)

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Reranker(Protocol):
    """Scores passages against a query; returns (index into `texts`, score), best first."""

    locality: ProcessingLocality

    async def rerank(self, query: str, texts: Sequence[str]) -> list[tuple[int, float]]: ...


class _Ranking(BaseModel):
    model_config = ConfigDict(extra="ignore")
    index: int
    logit: float


class _Reply(BaseModel):
    model_config = ConfigDict(extra="ignore")
    rankings: list[_Ranking]


class NvidiaReranker:
    """NVIDIA's hosted reranking API (`nvidia/llama-nemotron-rerank-vl-1b-v2` by default)."""

    locality: ProcessingLocality = "hosted"

    def __init__(
        self,
        model: str,
        api_key: str,
        *,
        timeout_seconds: float,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._model = model
        # NVIDIA spells dots as underscores in the path. Keep the replace: with the settings
        # pattern (no `/` beyond one, no `?`, `#` or `%`), it is what keeps `.` and `..`
        # segments out of the URL, so the model name can only ever name a path under the host.
        self._url = _NVIDIA_RERANK_URL.format(model=model.replace(".", "_"))
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._transport = transport

    async def rerank(self, query: str, texts: Sequence[str]) -> list[tuple[int, float]]:
        body = {
            "model": self._model,
            "query": {"text": query},
            "passages": [{"text": text} for text in texts],
            "truncate": "END",
        }
        async with httpx2.AsyncClient(
            transport=self._transport,
            timeout=httpx2.Timeout(self._timeout),
            trust_env=False,
            follow_redirects=False,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Accept": "application/json",
                "Accept-Encoding": "identity",  # the cap counts the bytes received
            },
        ) as client:
            try:
                async with client.stream("POST", self._url, json=body) as response:
                    if response.status_code != 200:
                        raise RerankError("rerank_failed")
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content += chunk
                        if len(content) > _MAX_RESPONSE_BYTES:
                            raise RerankError("rerank_output_invalid")
            except httpx2.TimeoutException:
                raise RerankError("rerank_timeout") from None
            except httpx2.HTTPError:
                raise RerankError("rerank_unavailable") from None
        try:
            rankings = _Reply.model_validate_json(bytes(content)).rankings
        except ValidationError:
            raise RerankError("rerank_output_invalid") from None
        return _checked([(r.index, r.logit) for r in rankings], len(texts))


def _checked(order: list[tuple[int, float]], count: int) -> list[tuple[int, float]]:
    """Every passage exactly once, finite scores, best first; anything else is invalid."""
    if sorted(index for index, _ in order) != list(range(count)) or not all(
        math.isfinite(score) for _, score in order
    ):
        raise RerankError("rerank_output_invalid")
    return sorted(order, key=lambda pair: -pair[1])


def create_reranker(settings: Settings) -> Reranker | None:
    """The configured reranker, or None for `none`."""
    name = settings.knowledge_reranker_effective
    if name == "none":
        return None
    key = settings.nvidia_api_key
    if key is None or not key.get_secret_value():
        raise ConfigurationError("the nvidia reranker needs NVIDIA_API_KEY")
    return NvidiaReranker(
        settings.knowledge_reranker_model,
        key.get_secret_value(),
        timeout_seconds=settings.knowledge_reranker_timeout_seconds,
    )
