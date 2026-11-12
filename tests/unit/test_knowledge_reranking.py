"""The NVIDIA reranker adapter and the reranker settings (RAG-09.01)."""

from __future__ import annotations

import json
from typing import Any

import httpx2
import pytest
from pydantic import ValidationError
from tests.conftest import PRODUCTION_PROFILE

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import ConfigurationError
from neuron_agent.knowledge.reranking import NvidiaReranker, RerankError, create_reranker

pytestmark = pytest.mark.anyio

_PROVIDER_TEXT = "confidential passage text"


@pytest.fixture(autouse=True)
def _no_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("NVIDIA_API_KEY", "APP_NVIDIA_API_KEY", "APP_KNOWLEDGE_RERANKER"):
        monkeypatch.delenv(name, raising=False)


def _reranker(handler: Any) -> NvidiaReranker:
    return NvidiaReranker(
        "nvidia/llama-nemotron-rerank-vl-1b-v2",
        "nvapi-test",
        timeout_seconds=2.0,
        transport=httpx2.MockTransport(handler),
    )


async def test_it_sends_the_query_and_passages_and_returns_the_best_first() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        rankings = [
            {"index": 1, "logit": 2.5},
            {"index": 0, "logit": -1.0},
            {"index": 2, "logit": 0},
        ]
        return httpx2.Response(200, json={"rankings": rankings})

    order = await _reranker(handler).rerank("what is zero trust", ["a", "b", "c"])

    assert order == [(1, 2.5), (2, 0.0), (0, -1.0)]
    [request] = seen
    assert str(request.url) == (
        "https://ai.api.nvidia.com/v1/retrieval/nvidia/llama-nemotron-rerank-vl-1b-v2/reranking"
    )
    assert request.headers["authorization"] == "Bearer nvapi-test"
    assert json.loads(request.content) == {
        "model": "nvidia/llama-nemotron-rerank-vl-1b-v2",
        "query": {"text": "what is zero trust"},
        "passages": [{"text": "a"}, {"text": "b"}, {"text": "c"}],
        "truncate": "END",
    }


@pytest.mark.parametrize(
    ("model", "path"),
    [
        ("nvidia/llama-3.2-nv-rerankqa-1b-v2", "nvidia/llama-3_2-nv-rerankqa-1b-v2"),
        # Dots become underscores, so no `.` or `..` segment reaches the path.
        ("a/..", "a/__"),
        ("../..", "__/__"),
    ],
)
async def test_the_model_names_one_path_under_nvidias_host(model: str, path: str) -> None:
    urls: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        urls.append(str(request.url))
        return httpx2.Response(200, json={"rankings": [{"index": 0, "logit": 1}]})

    reranker = NvidiaReranker(
        model, "k", timeout_seconds=2.0, transport=httpx2.MockTransport(handler)
    )
    await reranker.rerank("q", ["one"])
    assert urls == [f"https://ai.api.nvidia.com/v1/retrieval/{path}/reranking"]


async def test_a_reply_over_the_cap_is_refused() -> None:
    big = b'{"rankings": [' + b" " * 1_000_001 + b"]}"
    with pytest.raises(RerankError) as caught:
        await _reranker(lambda _: httpx2.Response(200, content=big)).rerank("q", ["one"])
    assert caught.value.code == "rerank_output_invalid"


@pytest.mark.parametrize(
    ("reply", "code"),
    [
        (httpx2.Response(500, text=_PROVIDER_TEXT), "rerank_failed"),
        (httpx2.Response(401, json={"detail": _PROVIDER_TEXT}), "rerank_failed"),
        (httpx2.Response(200, text="not json " + _PROVIDER_TEXT), "rerank_output_invalid"),
        # A passage missing, repeated, out of range, or a score that is not finite.
        (
            httpx2.Response(200, json={"rankings": [{"index": 0, "logit": 1}]}),
            "rerank_output_invalid",
        ),
        (
            httpx2.Response(200, json={"rankings": [{"index": 0, "logit": 1}] * 2}),
            "rerank_output_invalid",
        ),
        (
            httpx2.Response(
                200, json={"rankings": [{"index": 0, "logit": 1}, {"index": 5, "logit": 1}]}
            ),
            "rerank_output_invalid",
        ),
        (
            httpx2.Response(
                200,
                content=b'{"rankings": [{"index": 0, "logit": NaN}, {"index": 1, "logit": 1}]}',
            ),
            "rerank_output_invalid",
        ),
    ],
)
async def test_bad_replies_are_stable_codes_without_provider_text(
    reply: httpx2.Response, code: str
) -> None:
    with pytest.raises(RerankError) as caught:
        await _reranker(lambda _: reply).rerank("q", ["one", "two"])
    assert caught.value.code == code
    assert _PROVIDER_TEXT not in str(caught.value)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (httpx2.ReadTimeout("slow"), "rerank_timeout"),
        (httpx2.ConnectError(_PROVIDER_TEXT), "rerank_unavailable"),
    ],
)
async def test_transport_failures_are_stable_codes(error: Exception, code: str) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise error

    with pytest.raises(RerankError) as caught:
        await _reranker(handler).rerank("q", ["one"])
    assert caught.value.code == code
    assert _PROVIDER_TEXT not in str(caught.value)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        # The eval showed a gain, so NVIDIA embeddings with a key rerank by default.
        ({"nvidia_api_key": "nvapi-test"}, "nvidia"),
        ({}, "none"),
        (
            {
                "nvidia_api_key": "nvapi-test",
                "knowledge_embedding_provider": "openai_compatible",
                "knowledge_embedding_base_url": "http://tei:80/v1",
                "knowledge_embedding_locality": "self_hosted",
            },
            "none",
        ),
        ({"nvidia_api_key": "nvapi-test", "knowledge_reranker": "none"}, "none"),
        ({"knowledge_reranker": "nvidia"}, "nvidia"),
    ],
)
def test_the_default_reranker(overrides: dict[str, Any], expected: str) -> None:
    assert Settings(env="test", **overrides).knowledge_reranker_effective == expected


def test_create_reranker_builds_the_configured_one() -> None:
    assert create_reranker(Settings(env="test")) is None
    reranker = create_reranker(Settings(env="test", nvidia_api_key="nvapi-test"))
    assert isinstance(reranker, NvidiaReranker)
    assert reranker.locality == "hosted"
    with pytest.raises(ConfigurationError):
        create_reranker(Settings(env="test", knowledge_reranker="nvidia"))


def _self_hosted_production(env: str, **overrides: Any) -> Settings:
    """A valid staging/production profile with self-hosted embeddings and `self_hosted_only`."""
    return Settings(
        auth_mode="jwt",
        auth_issuer="https://issuer.example.test",
        auth_audience="neuron-api",
        auth_jwks_url="https://issuer.example.test/.well-known/jwks.json",
        identity_hash_key="x" * 32,
        openai_api_key="sk-test",
        **{
            **PRODUCTION_PROFILE,
            "env": env,
            "knowledge_embedding_provider": "openai_compatible",
            "knowledge_embedding_base_url": "https://tei.example.test/v1",
            "knowledge_embedding_locality": "self_hosted",
            "knowledge_processing_policy": "self_hosted_only",
            **overrides,
        },
    )


@pytest.mark.parametrize("env", ["staging", "production"])
def test_self_hosted_only_refuses_the_hosted_reranker(env: str) -> None:
    """AC3: with a self-hosted policy, a hosted reranker fails settings validation."""
    assert _self_hosted_production(env).knowledge_reranker_effective == "none"
    with pytest.raises(ValidationError, match="forbids the hosted nvidia reranker"):
        _self_hosted_production(env, knowledge_reranker="nvidia", nvidia_api_key="nvapi-test")


def test_development_may_try_the_hosted_reranker_under_any_policy() -> None:
    settings = Settings(
        env="development",
        knowledge_reranker="nvidia",
        knowledge_processing_policy="self_hosted_only",
    )
    # Retrieval still keeps each base's passages away from it (the policy check per search).
    assert settings.knowledge_reranker_effective == "nvidia"


@pytest.mark.parametrize("model", ["llama", "nvidia/x?y=1", "../etc/passwd", "nvidia/a/b"])
def test_the_model_name_cannot_change_the_url_path(model: str) -> None:
    with pytest.raises(ValidationError):
        Settings(env="test", knowledge_reranker_model=model)
