from __future__ import annotations

from pydantic import SecretStr

from neuron_agent.config.settings import Settings
from neuron_agent.models.factory import agent_invocation_config, create_chat_model


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
