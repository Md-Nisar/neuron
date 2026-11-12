"""RAG-02.03: embedding provider, settings validation and processing locality."""

from __future__ import annotations

import math
from collections.abc import Sequence

import httpx
import openai
import pytest
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from pydantic import ValidationError
from tests.conftest import PRODUCTION_PROFILE

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import ConfigurationError
from neuron_agent.knowledge.providers import (
    EmbeddingError,
    EmbeddingProvider,
    FakeEmbeddings,
    create_embedding_provider,
    ensure_processing_allowed,
)

pytestmark = pytest.mark.anyio

_REQUEST = httpx.Request("POST", "https://embeddings.example.test/v1/embeddings")


def _status_error(status: int, code: str | None = None) -> openai.APIStatusError:
    body = {"error": {"message": "secret document text", "code": code, "type": code}}
    response = httpx.Response(status, request=_REQUEST, json=body)
    error_class = {
        400: openai.BadRequestError,
        401: openai.AuthenticationError,
        429: openai.RateLimitError,
    }.get(status, openai.InternalServerError)
    return error_class("secret document text", response=response, body=body["error"])


class _Scripted(Embeddings):
    """Replays one outcome per call: an exception to raise or vectors to return."""

    def __init__(self, outcomes: list[Exception | list[list[float]]]) -> None:
        self.outcomes = outcomes
        self.calls: list[list[str]] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def aembed_query(self, text: str) -> list[float]:
        return (await self.aembed_documents([text]))[0]


def _provider(
    outcomes: list[Exception | list[list[float]]],
    *,
    dimensions: int = 3,
    batch_size: int = 2,
    max_retries: int = 3,
) -> tuple[EmbeddingProvider, _Scripted, list[float]]:
    scripted = _Scripted(outcomes)
    sleeps: list[float] = []

    async def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    provider = EmbeddingProvider(
        scripted,
        scripted,
        dimensions=dimensions,
        locality="self_hosted",
        batch_size=batch_size,
        max_retries=max_retries,
        sleep=sleep,
    )
    return provider, scripted, sleeps


def _vectors(count: int, dimensions: int = 3) -> list[list[float]]:
    return [[0.1] * dimensions for _ in range(count)]


def _production(env: str = "production", **overrides: object) -> Settings:
    return Settings(
        env=env,  # type: ignore[arg-type]
        auth_mode="jwt",
        auth_issuer="https://issuer.example.test",
        auth_audience="neuron-api",
        auth_jwks_url="https://issuer.example.test/.well-known/jwks.json",
        identity_hash_key="x" * 32,
        openai_api_key="sk-test",
        **{**PRODUCTION_PROFILE, **overrides},
    )


@pytest.fixture(autouse=True)
def _no_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("NVIDIA_API_KEY", "APP_NVIDIA_API_KEY", "APP_KNOWLEDGE_EMBEDDING_API_KEY"):
        monkeypatch.delenv(name, raising=False)


# AC1: policy self_hosted_only refuses a hosted provider in staging and production.


@pytest.mark.parametrize("env", ["staging", "production"])
def test_self_hosted_only_refuses_nvidia_at_startup(env: str) -> None:
    overrides = {"knowledge_processing_policy": "self_hosted_only", "nvidia_api_key": "nvapi-x"}
    with pytest.raises(ValidationError, match="self_hosted_only forbids the hosted nvidia"):
        _production(env, **overrides)


def test_self_hosted_only_refuses_openai_compatible_without_declared_locality() -> None:
    with pytest.raises(ValidationError, match="forbids the hosted openai_compatible"):
        _production(
            knowledge_processing_policy="self_hosted_only",
            knowledge_embedding_provider="openai_compatible",
            knowledge_embedding_base_url="https://api.openai.example.test/v1",
        )


def test_self_hosted_only_accepts_a_declared_self_hosted_server() -> None:
    settings = _production(
        knowledge_processing_policy="self_hosted_only",
        knowledge_embedding_provider="openai_compatible",
        knowledge_embedding_base_url="https://tei:443/v1",
        knowledge_embedding_locality="self_hosted",
    )
    assert settings.knowledge_embedding_locality_effective == "self_hosted"


def test_defaults_leave_an_existing_production_profile_valid() -> None:
    settings = _production()
    assert settings.knowledge_processing_policy == "allow_hosted"
    assert settings.knowledge_embedding_dimensions == 1024


def test_nvidia_cannot_be_declared_self_hosted() -> None:
    with pytest.raises(ValidationError, match="NVIDIA's API catalog is hosted"):
        Settings(env="test", knowledge_embedding_locality="self_hosted")


def test_fake_provider_is_refused_in_production() -> None:
    with pytest.raises(ValidationError, match="fake is refused"):
        _production(knowledge_embedding_provider="fake")


@pytest.mark.parametrize(
    "url",
    [
        None,
        "ftp://tei/v1",
        "https://user:pass@tei.example.test/v1",
        "https://tei.example.test/v1?key=x",
        "tei:80",
    ],
)
def test_openai_compatible_needs_a_plain_http_url(url: str | None) -> None:
    with pytest.raises(ValidationError, match="APP_KNOWLEDGE_EMBEDDING_BASE_URL") as caught:
        Settings(
            env="test",
            knowledge_embedding_provider="openai_compatible",
            knowledge_embedding_base_url=url,
        )
    assert "pass" not in str(caught.value)
    assert "key=x" not in str(caught.value)


def test_a_keyed_embedding_server_needs_https_in_production() -> None:
    with pytest.raises(ValidationError, match="must use https"):
        _production(
            knowledge_embedding_provider="openai_compatible",
            knowledge_embedding_base_url="http://tei.internal/v1",
            knowledge_embedding_api_key="tei-key",
        )


def test_production_needs_https_for_the_embedding_server_even_without_a_key() -> None:
    """Audit L-10: document text must not cross the network in clear text in production."""
    with pytest.raises(ValidationError, match="must use https in production"):
        _production(
            knowledge_embedding_provider="openai_compatible",
            knowledge_embedding_base_url="http://tei:80/v1",
            knowledge_embedding_locality="self_hosted",
        )


@pytest.mark.parametrize("env", ["development", "test"])
def test_local_and_ci_may_reach_the_embedding_server_over_http(env: str) -> None:
    settings = Settings(
        env=env,  # type: ignore[arg-type]
        knowledge_embedding_provider="openai_compatible",
        knowledge_embedding_base_url="http://tei:80/v1",
    )
    assert settings.knowledge_embedding_base_url == "http://tei:80/v1"


def test_dimensions_above_halfvec_hnsw_limit_are_refused() -> None:
    with pytest.raises(ValidationError):
        Settings(env="test", knowledge_embedding_dimensions=4001)


@pytest.mark.parametrize(
    ("kb", "provider", "policy", "allowed"),
    [
        ("hosted", "hosted", "allow_hosted", True),
        ("self_hosted", "self_hosted", "allow_hosted", True),
        ("hosted", "self_hosted", "self_hosted_only", True),
        ("self_hosted", "hosted", "allow_hosted", False),
        ("hosted", "hosted", "self_hosted_only", False),
        ("self_hosted", "unknown", "allow_hosted", False),
    ],
)
def test_processing_locality_check(kb: str, provider: str, policy: str, allowed: bool) -> None:
    if allowed:
        ensure_processing_allowed(kb, provider, policy)  # type: ignore[arg-type]
        return
    with pytest.raises(EmbeddingError) as caught:
        ensure_processing_allowed(kb, provider, policy)  # type: ignore[arg-type]
    assert caught.value.code == "processing_locality_forbidden"


# AC2: wrong dimension, count or non-finite values fail the batch and return nothing.


async def test_wrong_dimension_fails_and_returns_no_vectors() -> None:
    provider, _, _ = _provider([_vectors(2), _vectors(1, dimensions=4)])
    result: list[list[float]] | None = None
    with pytest.raises(EmbeddingError) as caught:
        result = await provider.embed_documents(["a", "b", "c"])
    assert caught.value.code == "embedding_dimension_mismatch"
    assert result is None


@pytest.mark.parametrize(
    ("vectors", "code"),
    [
        ([[0.1, 0.2, 0.3]], "embedding_count_mismatch"),
        ([[0.1, math.nan, 0.3], [0.1, 0.2, 0.3]], "embedding_non_finite"),
        ([[0.1, math.inf, 0.3], [0.1, 0.2, 0.3]], "embedding_non_finite"),
    ],
)
async def test_invalid_vectors_fail_with_a_stable_code(
    vectors: list[list[float]], code: str
) -> None:
    provider, _, _ = _provider([vectors])
    with pytest.raises(EmbeddingError) as caught:
        await provider.embed_documents(["a", "b"])
    assert caught.value.code == code


async def test_documents_are_embedded_in_batches() -> None:
    provider, scripted, _ = _provider([_vectors(2), _vectors(2), _vectors(1)])
    vectors = await provider.embed_documents(["a", "b", "c", "d", "e"])
    assert len(vectors) == 5
    assert scripted.calls == [["a", "b"], ["c", "d"], ["e"]]


# AC3: 429 and 5xx are retried with backoff; 400 is terminal.


@pytest.mark.parametrize(
    "error",
    [
        _status_error(429),
        _status_error(500),
        _status_error(503),
        openai.APIConnectionError(request=_REQUEST),
        openai.APITimeoutError(request=_REQUEST),
    ],
)
async def test_transient_errors_are_retried_with_backoff(error: Exception) -> None:
    provider, scripted, sleeps = _provider([error, error, _vectors(1)])
    assert await provider.embed_documents(["a"]) == _vectors(1)
    assert len(scripted.calls) == 3
    assert sleeps == [0.5, 1.0]


async def test_retries_are_bounded() -> None:
    provider, scripted, sleeps = _provider([_status_error(503)] * 3, max_retries=2)
    with pytest.raises(EmbeddingError) as caught:
        await provider.embed_documents(["a"])
    assert caught.value.code == "embedding_provider_unavailable"
    assert caught.value.retryable
    assert len(scripted.calls) == 3
    assert len(sleeps) == 2


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (_status_error(400), "embedding_provider_rejected"),
        (_status_error(401), "embedding_provider_rejected"),
        (_status_error(429, code="insufficient_quota"), "embedding_quota_exhausted"),
    ],
)
async def test_terminal_errors_are_not_retried(error: Exception, code: str) -> None:
    provider, scripted, sleeps = _provider([error, _vectors(1)])
    with pytest.raises(EmbeddingError) as caught:
        await provider.embed_documents(["a"])
    assert caught.value.code == code
    assert not caught.value.retryable
    assert len(scripted.calls) == 1
    assert sleeps == []


async def test_provider_messages_are_not_carried_by_the_error() -> None:
    provider, _, _ = _provider([_status_error(400)])
    with pytest.raises(EmbeddingError) as caught:
        await provider.embed_documents(["a"])
    assert "secret" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "error",
    [
        ValueError("secret document text"),
        KeyError("secret document text"),
        openai.APIResponseValidationError(
            response=httpx.Response(200, request=_REQUEST), body={"secret": "document text"}
        ),
    ],
)
async def test_unexpected_client_errors_are_sanitised_and_terminal(error: Exception) -> None:
    provider, scripted, _ = _provider([error, _vectors(1)])
    with pytest.raises(EmbeddingError) as caught:
        await provider.embed_documents(["a"])
    assert caught.value.code == "embedding_provider_error"
    assert caught.value.__context__ is None
    assert "secret" not in repr(caught.value)
    assert len(scripted.calls) == 1


# AC4: development and test without credentials use the fake provider, with no network call.


@pytest.mark.parametrize("env", ["development", "test"])
async def test_without_credentials_the_fake_provider_is_used(
    env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(*_: object, **__: object) -> None:
        raise AssertionError("network call attempted")

    monkeypatch.setattr(httpx.AsyncClient, "send", no_network)
    monkeypatch.setattr(httpx.Client, "send", no_network)
    provider = create_embedding_provider(Settings(env=env))  # type: ignore[arg-type]

    assert isinstance(provider._documents, FakeEmbeddings)
    assert provider.locality == "self_hosted"
    first = await provider.embed_documents(["alpha", "beta"])
    assert first == await provider.embed_documents(["alpha", "beta"])
    assert len(first[0]) == 1024
    assert len(await provider.embed_query("alpha")) == 1024
    assert first[0] != first[1]
    assert math.isclose(math.fsum(value * value for value in first[0]), 1.0)


def test_nvidia_without_a_key_is_a_configuration_error_outside_development() -> None:
    settings = Settings(env="test").model_copy(update={"env": "staging"})
    with pytest.raises(ConfigurationError):
        create_embedding_provider(settings)


def test_nvidia_clients_send_input_type_and_dimensions() -> None:
    provider = create_embedding_provider(Settings(env="test", nvidia_api_key="nvapi-test"))
    documents, queries = provider._documents, provider._queries
    assert isinstance(documents, OpenAIEmbeddings)
    assert isinstance(queries, OpenAIEmbeddings)
    assert documents.model_kwargs == {"extra_body": {"input_type": "passage"}}
    assert queries.model_kwargs == {"extra_body": {"input_type": "query"}}
    assert documents.dimensions == 1024
    assert documents.max_retries == 0
    assert documents.openai_api_base == "https://integrate.api.nvidia.com/v1"
    assert provider.locality == "hosted"


@pytest.mark.parametrize(
    ("overrides", "batch"),
    [
        # NVIDIA's catalog answers 500 to any batch of 2 or more real-size chunks (#480).
        ({"nvidia_api_key": "nvapi-test"}, 1),
        ({"nvidia_api_key": "nvapi-test", "knowledge_embedding_batch_size": 8}, 8),
        (
            {
                "knowledge_embedding_provider": "openai_compatible",
                "knowledge_embedding_base_url": "http://tei:80/v1",
                "knowledge_embedding_locality": "self_hosted",
            },
            32,
        ),
    ],
)
def test_the_batch_size_defaults_to_one_for_nvidia_only(
    overrides: dict[str, object], batch: int
) -> None:
    provider = create_embedding_provider(Settings(env="test", **overrides))  # type: ignore[arg-type]
    assert provider._batch_size == batch
    assert isinstance(provider._documents, OpenAIEmbeddings)
    assert provider._documents.chunk_size == batch


def test_openai_compatible_client_uses_the_configured_server() -> None:
    settings = Settings(
        env="test",
        knowledge_embedding_provider="openai_compatible",
        knowledge_embedding_base_url="http://tei:80/v1",
        knowledge_embedding_locality="self_hosted",
    )
    provider = create_embedding_provider(settings)
    documents: Sequence[object] = [provider._documents, provider._queries]
    for client in documents:
        assert isinstance(client, OpenAIEmbeddings)
        assert client.openai_api_base == "http://tei:80/v1"
        assert client.model_kwargs == {}
    assert provider.locality == "self_hosted"
