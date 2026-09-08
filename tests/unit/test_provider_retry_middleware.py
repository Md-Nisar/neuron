from __future__ import annotations

import httpx
import openai
import pytest
from langchain.agents.middleware import ModelRetryMiddleware

from neuron_agent.config.settings import Settings
from neuron_agent.models.factory import _is_retryable_provider_error, provider_retry_middleware

pytestmark = pytest.mark.anyio

_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


class _FakeRequest:
    pass


def _rate_limit_error() -> openai.RateLimitError:
    return openai.RateLimitError(
        "rate limited",
        response=httpx.Response(status_code=429, request=_REQUEST),
        body=None,
    )


def _authentication_error() -> openai.AuthenticationError:
    return openai.AuthenticationError(
        "bad key",
        response=httpx.Response(status_code=401, request=_REQUEST),
        body=None,
    )


def _fast_retry_middleware(max_retries: int) -> ModelRetryMiddleware:
    return ModelRetryMiddleware(
        max_retries=max_retries,
        retry_on=_is_retryable_provider_error,
        on_failure="error",
        initial_delay=0,
    )


async def test_provider_retry_middleware_succeeds_after_transient_failures() -> None:
    middleware = _fast_retry_middleware(max_retries=2)
    attempts = 0

    async def handler(request: object) -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise openai.APIConnectionError(request=_REQUEST)
        return "ok"

    result = await middleware.awrap_model_call(_FakeRequest(), handler)
    assert result == "ok"
    assert attempts == 3


async def test_provider_retry_middleware_raises_immediately_on_non_retryable_error() -> None:
    middleware = _fast_retry_middleware(max_retries=2)
    attempts = 0

    async def handler(request: object) -> str:
        nonlocal attempts
        attempts += 1
        raise _authentication_error()

    with pytest.raises(openai.AuthenticationError):
        await middleware.awrap_model_call(_FakeRequest(), handler)
    assert attempts == 1


async def test_provider_retry_middleware_raises_after_exhausting_retries() -> None:
    middleware = _fast_retry_middleware(max_retries=1)
    attempts = 0

    async def handler(request: object) -> str:
        nonlocal attempts
        attempts += 1
        raise _rate_limit_error()

    with pytest.raises(openai.RateLimitError):
        await middleware.awrap_model_call(_FakeRequest(), handler)
    assert attempts == 2


def test_provider_retry_middleware_uses_settings_max_retries() -> None:
    settings = Settings(env="test", provider_max_retries=4, openai_api_key=None)
    middleware = provider_retry_middleware(settings)
    assert middleware.max_retries == 4
    assert middleware.on_failure == "error"
