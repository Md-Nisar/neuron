from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from neuron_agent.config.settings import Settings
from neuron_agent.models.factory import _FakeChatModel, create_chat_model


def test_settings_require_openai_key_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(env="production", default_model="openai:gpt-5.4-mini", openai_api_key=None)


def test_settings_require_openai_key_in_staging() -> None:
    with pytest.raises(ValidationError):
        Settings(env="staging", default_model="openai:gpt-5.4-mini", openai_api_key=None)


def test_settings_require_nvidia_key_for_nvidia_models_in_production() -> None:
    with pytest.raises(ValidationError, match="NVIDIA_API_KEY"):
        Settings(
            env="production",
            default_model="nvidia:example/chat-model",
            openai_api_key="sk-test",
            nvidia_api_key=None,
        )


def test_nvidia_key_is_read_from_its_conventional_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    settings = Settings(env="test")

    assert settings.nvidia_api_key is not None
    assert settings.nvidia_api_key.get_secret_value() == "nvapi-test"


def test_settings_allow_test_without_provider_key() -> None:
    settings = Settings(env="test", default_model="openai:gpt-5.4-mini", openai_api_key=None)
    assert settings.env == "test"


def test_settings_defaults_are_openai_production_safe() -> None:
    settings = Settings(env="test", openai_api_key=None)
    assert settings.default_model == "openai:gpt-5.4-mini"
    assert settings.request_timeout_seconds == 60
    assert settings.tool_timeout_seconds == 20
    assert settings.max_agent_iterations == 8
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


def test_env_example_documents_every_setting_and_nothing_else() -> None:
    """Every `Settings` field has a (possibly commented-out) line in `.env.example`."""
    text = (Path(__file__).parents[2] / ".env.example").read_text()
    documented = set(re.findall(r"^#?\s*(APP_[A-Z0-9_]+)=", text, re.MULTILINE))
    # Some settings are documented under their conventional names, such as OPENAI_API_KEY.
    conventional = {
        "APP_OPENAI_API_KEY",
        "APP_NVIDIA_API_KEY",
        "APP_LANGSMITH_API_KEY",
        "APP_OTEL_EXPORTER_OTLP_ENDPOINT",
        "APP_OTEL_EXPORTER_OTLP_HEADERS",
    }
    expected = {f"APP_{name.upper()}" for name in Settings.model_fields} - conventional

    assert expected - documented == set(), "add these settings to .env.example"
    assert documented - expected == set(), "remove stale settings from .env.example"
    assert re.search(r"^OPENAI_API_KEY=", text, re.MULTILINE)
    assert re.search(r"^NVIDIA_API_KEY=", text, re.MULTILINE)
    assert re.search(r"^#?\s*OTEL_EXPORTER_OTLP_ENDPOINT=", text, re.MULTILINE)
    assert re.search(r"^#?\s*OTEL_EXPORTER_OTLP_HEADERS=", text, re.MULTILINE)


def test_empty_provider_key_from_env_example_means_no_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`cp .env.example .env` leaves `OPENAI_API_KEY=`; development still uses the fake model."""
    monkeypatch.setenv("OPENAI_API_KEY", "")
    settings = Settings(env="development")

    assert settings.openai_api_key is None
    assert isinstance(create_chat_model(settings), _FakeChatModel)


def _production(**overrides: object) -> Settings:
    return Settings(
        env="production",
        auth_mode="jwt",
        auth_issuer="https://issuer.example.test",
        auth_audience="neuron-api",
        auth_jwks_url="https://issuer.example.test/.well-known/jwks.json",
        identity_hash_key="x" * 32,
        openai_api_key="sk-test",
        **overrides,
    )


def test_otlp_credentials_require_https_off_loopback_in_production() -> None:
    with pytest.raises(ValidationError, match="must use HTTPS"):
        _production(
            OTEL_EXPORTER_OTLP_ENDPOINT="http://collector.internal:4318",
            OTEL_EXPORTER_OTLP_HEADERS="authorization=Bearer%20t",
        )


@pytest.mark.parametrize(
    "endpoint",
    ["https://collector.internal:4318", "http://localhost:4318", "http://127.0.0.1:4318"],
)
def test_otlp_credentials_allowed_over_https_or_loopback(endpoint: str) -> None:
    _production(
        OTEL_EXPORTER_OTLP_ENDPOINT=endpoint, OTEL_EXPORTER_OTLP_HEADERS="authorization=Bearer%20t"
    )


def test_plain_http_otlp_without_credentials_is_allowed_in_production() -> None:
    _production(OTEL_EXPORTER_OTLP_ENDPOINT="http://collector.internal:4318")


def test_limits_backend_auto_resolves_to_memory() -> None:
    assert Settings(env="test").limits_backend == "memory"


def test_settings_require_dsn_for_postgres_limits_backend_even_without_checkpointer() -> None:
    with pytest.raises(ValidationError, match="APP_LIMITS_BACKEND=postgres"):
        Settings(env="test", checkpointer="none", limits_backend="postgres")
    with pytest.raises(ValidationError, match="APP_POSTGRES_DSN"):
        Settings(env="test", checkpointer="none", limits_backend="postgres", postgres_dsn="")


def test_settings_reject_unknown_limits_backend() -> None:
    with pytest.raises(ValidationError):
        Settings(env="test", limits_backend="redis")
