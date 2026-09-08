from __future__ import annotations

import httpx
import openai
import pytest
from langchain.agents.structured_output import StructuredOutputValidationError
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import (
    AgentExecutionError,
    ConfigurationError,
    ProviderError,
    ProviderTimeoutError,
    RateLimitError,
)
from neuron_agent.errors.base import StructuredOutputError as AppStructuredOutputError
from neuron_agent.models.factory import (
    agent_invocation_config,
    classify_agent_error,
    create_chat_model,
)

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


def test_agent_invocation_config_uses_max_agent_iterations() -> None:
    settings = Settings(
        env="test", max_agent_iterations=5, tool_timeout_seconds=20, openai_api_key=None
    )
    assert agent_invocation_config(settings) == {"recursion_limit": 5, "timeout": 20}


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


def test_classify_agent_error_maps_structured_output_failure() -> None:
    error = StructuredOutputValidationError(
        tool_name="AgentAnswer",
        source=ValueError("bad structured output"),
        ai_message=AIMessage(content="not structured"),
    )
    assert isinstance(classify_agent_error(error), AppStructuredOutputError)


def test_classify_agent_error_falls_back_to_agent_execution_error() -> None:
    assert isinstance(classify_agent_error(RuntimeError("boom")), AgentExecutionError)
