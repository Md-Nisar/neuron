from __future__ import annotations

import pytest
from pydantic import ValidationError

from neuron_agent.config.settings import Settings


def test_settings_require_openai_key_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(env="production", default_model="openai:gpt-5.4-mini", openai_api_key=None)


def test_settings_allow_test_without_provider_key() -> None:
    settings = Settings(env="test", default_model="openai:gpt-5.4-mini", openai_api_key=None)
    assert settings.env == "test"


def test_settings_defaults_are_openai_production_safe() -> None:
    settings = Settings(env="test", openai_api_key=None)
    assert settings.default_model == "openai:gpt-5.4-mini"
    assert settings.request_timeout_seconds == 60
    assert settings.tool_timeout_seconds == 20
    assert settings.max_agent_iterations == 5
    assert settings.max_output_tokens == 2000
    assert settings.provider_max_retries == 2
    assert settings.max_request_body_bytes == 65_536
    assert settings.rate_limit_enabled is True
    assert settings.rate_limit_requests_per_window == 60
    assert settings.rate_limit_window_seconds == 60
    assert settings.rate_limit_burst == 20


def test_settings_rejects_provider_max_retries_out_of_bounds() -> None:
    with pytest.raises(ValidationError):
        Settings(env="test", openai_api_key=None, provider_max_retries=6)


def test_settings_rejects_max_request_body_bytes_out_of_bounds() -> None:
    with pytest.raises(ValidationError):
        Settings(env="test", openai_api_key=None, max_request_body_bytes=100)


def test_settings_rejects_rate_limit_burst_out_of_bounds() -> None:
    with pytest.raises(ValidationError):
        Settings(env="test", openai_api_key=None, rate_limit_burst=0)
