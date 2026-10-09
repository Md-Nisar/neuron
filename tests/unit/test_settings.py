from __future__ import annotations

import pytest
from pydantic import ValidationError

from neuron_agent.config.settings import Settings


def test_settings_require_openai_key_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(env="production", default_model="openai:gpt-5.4-mini", openai_api_key=None)


def test_settings_require_openai_key_in_staging() -> None:
    with pytest.raises(ValidationError):
        Settings(env="staging", default_model="openai:gpt-5.4-mini", openai_api_key=None)


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
    assert settings.max_concurrent_runs_per_user == 2
    assert settings.user_token_budget == 100_000
    assert settings.user_token_budget_window_seconds == 3600


def test_settings_rejects_provider_max_retries_out_of_bounds() -> None:
    with pytest.raises(ValidationError):
        Settings(env="test", openai_api_key=None, provider_max_retries=6)


def test_settings_rejects_max_request_body_bytes_out_of_bounds() -> None:
    with pytest.raises(ValidationError):
        Settings(env="test", openai_api_key=None, max_request_body_bytes=100)


def test_settings_rejects_rate_limit_burst_out_of_bounds() -> None:
    with pytest.raises(ValidationError):
        Settings(env="test", openai_api_key=None, rate_limit_burst=0)


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_concurrent_runs_per_user": 0},
        {"user_token_budget": 0},
        {"user_token_budget_window_seconds": 0},
    ],
)
def test_settings_rejects_resource_limits_out_of_bounds(
    overrides: dict[str, int],
) -> None:
    with pytest.raises(ValidationError):
        Settings(env="test", openai_api_key=None, **overrides)


@pytest.mark.parametrize(
    ("env", "expected"),
    [("development", "memory"), ("test", "memory"), ("staging", "none"), ("production", "none")],
)
def test_settings_auto_checkpointer_resolves_per_environment(env: str, expected: str) -> None:
    overrides: dict[str, object] = {"env": env, "openai_api_key": "sk-test"}
    if env in {"staging", "production"}:
        overrides.update(
            {
                "auth_mode": "jwt",
                "auth_issuer": "https://issuer.example.test",
                "auth_audience": "neuron-api",
                "auth_jwks_url": "https://issuer.example.test/jwks.json",
                "identity_hash_key": "x" * 32,
            }
        )
    assert Settings(**overrides).checkpointer == expected


@pytest.mark.parametrize("env", ["staging", "production"])
def test_settings_reject_memory_checkpointer_outside_dev(env: str) -> None:
    with pytest.raises(ValidationError, match="not durable"):
        Settings(env=env, openai_api_key="sk-test", checkpointer="memory")


@pytest.mark.parametrize("env", ["development", "test"])
def test_settings_allow_memory_checkpointer_in_dev(env: str) -> None:
    assert Settings(env=env, checkpointer="memory").checkpointer == "memory"


def test_settings_require_dsn_for_postgres_checkpointer() -> None:
    with pytest.raises(ValidationError, match="APP_POSTGRES_DSN"):
        Settings(env="test", checkpointer="postgres", postgres_dsn=None)


def test_settings_reject_unknown_checkpointer() -> None:
    with pytest.raises(ValidationError):
        Settings(env="test", checkpointer="sqlite")


def test_settings_reject_postgres_pool_size_out_of_bounds() -> None:
    with pytest.raises(ValidationError):
        Settings(env="test", postgres_pool_max_size=0)
    with pytest.raises(ValidationError):
        Settings(env="test", postgres_pool_max_size=101)


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_history_tokens": 255},
        {"max_history_tokens": 200_001},
        {"max_thread_messages": 1},
        {"max_thread_messages": 10_001},
    ],
)
def test_settings_reject_history_limits_out_of_bounds(overrides: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        Settings(env="test", **overrides)
