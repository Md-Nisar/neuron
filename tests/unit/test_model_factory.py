from __future__ import annotations

import httpx
import openai
import pytest
from langchain.agents.structured_output import StructuredOutputValidationError
from langchain_core.messages import AIMessage
from langgraph.errors import GraphRecursionError
from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import (
    AgentExecutionError,
    ConfigurationError,
    ProviderError,
    ProviderQuotaError,
    ProviderTimeoutError,
    RateLimitError,
    ToolExecutionError,
)
from neuron_agent.errors.base import StructuredOutputError as AppStructuredOutputError
from neuron_agent.models.factory import (
    _is_retryable_provider_error,
    agent_invocation_config,
    classify_agent_error,
    create_chat_model,
    create_main_agent,
    get_retry_attempts,
    reset_retry_attempts,
)
from neuron_agent.tools import calculator, utc_now

_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")


def test_create_chat_model_configures_openai_model_limits() -> None:
    settings = Settings(
        env="production",
        default_model="openai:gpt-5.4-mini",
        request_timeout_seconds=60,
        tool_timeout_seconds=20,
        max_output_tokens=2000,
        openai_api_key=SecretStr("test-key"),
    )
    model = create_chat_model(settings)
    assert model.model_name == "gpt-5.4-mini"
    assert model.request_timeout == 60
    assert model.max_tokens == 2000


def test_create_chat_model_disables_sdk_level_retries() -> None:
    settings = Settings(env="production", openai_api_key=SecretStr("test-key"))
    model = create_chat_model(settings)
    assert model.max_retries == 0


def test_agent_invocation_config_uses_max_agent_iterations_and_run_id() -> None:
    settings = Settings(env="test", max_agent_iterations=5, openai_api_key=None)
    run_id = "12345678-1234-5678-1234-567812345678"
    config = agent_invocation_config(settings, run_id=run_id)
    assert config["recursion_limit"] == 5
    assert str(config["run_id"]) == run_id


def test_classify_agent_error_passes_through_app_errors() -> None:
    error = ToolExecutionError("tool timed out")
    assert classify_agent_error(error) is error


def test_create_chat_model_rejects_unsupported_provider() -> None:
    settings = Settings(
        env="production",
        default_model="anthropic:claude",
        openai_api_key=SecretStr("test-key"),
    )
    with pytest.raises(ConfigurationError):
        create_chat_model(settings)


def test_create_chat_model_rejects_malformed_model_identifier() -> None:
    settings = Settings(
        env="production",
        default_model="not-a-valid-identifier",
        openai_api_key=SecretStr("test-key"),
    )
    with pytest.raises(ConfigurationError):
        create_chat_model(settings)


def _quota_error(**body: str) -> openai.RateLimitError:
    response = httpx.Response(status_code=429, request=_REQUEST)
    return openai.RateLimitError("no credits remaining", response=response, body=body)


@pytest.mark.parametrize(
    "body",
    [
        {"type": "insufficient_quota", "code": "credit_balance_exhausted"},
        {"type": "insufficient_quota", "code": "insufficient_quota"},
    ],
)
def test_quota_errors_are_not_retried_and_classified_distinctly(body: dict[str, str]) -> None:
    error = _quota_error(**body)
    assert _is_retryable_provider_error(error) is False
    classified = classify_agent_error(error)
    assert isinstance(classified, ProviderQuotaError)
    assert classified.context.retryable is False
    assert "no API credit" in str(classified)


def test_rate_limit_without_quota_marker_is_still_retried() -> None:
    error = _quota_error(type="requests", code="rate_limit_exceeded")
    assert _is_retryable_provider_error(error) is True
    assert isinstance(classify_agent_error(error), RateLimitError)


def test_classify_agent_error_maps_rate_limit() -> None:
    response = httpx.Response(status_code=429, request=_REQUEST)
    error = openai.RateLimitError("rate limited", response=response, body=None)
    assert isinstance(classify_agent_error(error), RateLimitError)


def test_classify_agent_error_maps_timeout() -> None:
    error = openai.APITimeoutError(request=_REQUEST)
    assert isinstance(classify_agent_error(error), ProviderTimeoutError)


def test_classify_agent_error_maps_authentication_failure() -> None:
    response = httpx.Response(status_code=401, request=_REQUEST)
    error = openai.AuthenticationError("bad key", response=response, body=None)
    assert isinstance(classify_agent_error(error), ConfigurationError)


def test_classify_agent_error_maps_generic_provider_error() -> None:
    error = openai.APIConnectionError(request=_REQUEST)
    assert isinstance(classify_agent_error(error), ProviderError)


def test_classify_agent_error_maps_internal_server_error() -> None:
    response = httpx.Response(status_code=500, request=_REQUEST)
    error = openai.InternalServerError("internal error", response=response, body=None)
    assert isinstance(classify_agent_error(error), ProviderError)


def test_classify_agent_error_maps_structured_output_failure() -> None:
    error = StructuredOutputValidationError(
        tool_name="AgentAnswer",
        source=ValueError("bad structured output"),
        ai_message=AIMessage(content="not structured"),
    )
    assert isinstance(classify_agent_error(error), AppStructuredOutputError)


def test_classify_agent_error_falls_back_to_agent_execution_error() -> None:
    assert isinstance(classify_agent_error(RuntimeError("boom")), AgentExecutionError)


def test_classify_agent_error_maps_recursion_limit_exceeded() -> None:
    error = GraphRecursionError("Recursion limit of 5 reached")
    assert isinstance(classify_agent_error(error), AgentExecutionError)


@pytest.mark.parametrize(
    "error",
    [
        openai.APIConnectionError(request=_REQUEST),
        openai.APITimeoutError(request=_REQUEST),
        openai.RateLimitError(
            "rate limited",
            response=httpx.Response(status_code=429, request=_REQUEST),
            body=None,
        ),
        openai.InternalServerError(
            "internal error",
            response=httpx.Response(status_code=500, request=_REQUEST),
            body=None,
        ),
    ],
)
def test_is_retryable_provider_error_accepts_transient_failures(error: Exception) -> None:
    assert _is_retryable_provider_error(error) is True


@pytest.mark.parametrize(
    "error",
    [
        openai.AuthenticationError(
            "bad key",
            response=httpx.Response(status_code=401, request=_REQUEST),
            body=None,
        ),
        openai.BadRequestError(
            "bad request",
            response=httpx.Response(status_code=400, request=_REQUEST),
            body=None,
        ),
        ConfigurationError("malformed config"),
        RuntimeError("unexpected bug"),
    ],
)
def test_is_retryable_provider_error_rejects_non_transient_failures(error: Exception) -> None:
    assert _is_retryable_provider_error(error) is False


def test_retry_attempts_counts_only_retryable_errors() -> None:
    reset_retry_attempts()
    assert get_retry_attempts() == 0

    _is_retryable_provider_error(openai.APIConnectionError(request=_REQUEST))
    assert get_retry_attempts() == 1

    _is_retryable_provider_error(ConfigurationError("malformed config"))
    assert get_retry_attempts() == 1

    _is_retryable_provider_error(openai.APIConnectionError(request=_REQUEST))
    assert get_retry_attempts() == 2

    reset_retry_attempts()
    assert get_retry_attempts() == 0


@pytest.mark.anyio
async def test_fake_chat_model_tolerates_create_agent_tool_binding() -> None:
    """Regression test: `create_agent` always calls `model.bind_tools(...)`, even when
    `create_chat_model` falls back to the fake model because no provider key is set.
    The base fake model's `bind_tools` raises `NotImplementedError`, which previously
    crashed every `/v1/agent/invoke` call made without credentials configured."""
    settings = Settings(env="test", openai_api_key=None)
    agent = create_main_agent(settings, tools=[utc_now, calculator])

    result = await agent.ainvoke(
        {"messages": [AIMessage(content="hi")]}, config={"recursion_limit": 5}
    )

    assert result["messages"][-1].content == "Local test response."


def test_agent_invocation_config_omits_missing_run_id() -> None:
    config = agent_invocation_config(Settings(env="test"), run_id=None)
    assert "run_id" not in config
    assert config["recursion_limit"] == 5
