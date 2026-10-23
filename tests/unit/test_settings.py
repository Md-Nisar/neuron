from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.conftest import PRODUCTION_PROFILE

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


@pytest.mark.parametrize("env", ["development", "test"])
def test_settings_auto_checkpointer_resolves_to_memory_in_dev_and_test(env: str) -> None:
    assert Settings(env=env, openai_api_key="sk-test").checkpointer == "memory"


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
        **{**PRODUCTION_PROFILE, **overrides},
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


# --- Production settings validation (ADR 0008 decision 9) -------------------------------


def _hardened(env: str, **overrides: object) -> Settings:
    """Valid staging/production settings; `overrides` replace, and `None` removes, a key."""
    values: dict[str, object] = {
        "env": env,
        "auth_mode": "jwt",
        "auth_issuer": "https://issuer.example.test",
        "auth_audience": "neuron-api",
        "auth_jwks_url": "https://issuer.example.test/.well-known/jwks.json",
        "identity_hash_key": "x" * 32,
        "openai_api_key": "sk-test",
        **PRODUCTION_PROFILE,
        **overrides,
    }
    return Settings(**{k: v for k, v in values.items() if v is not _UNSET})


_UNSET = object()
_BOTH = pytest.mark.parametrize("env", ["staging", "production"])


@_BOTH
def test_the_hardened_profile_is_accepted(env: str) -> None:
    assert _hardened(env).env == env


@_BOTH
def test_auto_checkpointer_is_refused(env: str) -> None:
    with pytest.raises(ValidationError, match="APP_CHECKPOINTER=auto"):
        _hardened(env, checkpointer="auto")


@_BOTH
def test_auto_limits_backend_is_refused(env: str) -> None:
    with pytest.raises(ValidationError, match="APP_LIMITS_BACKEND=auto"):
        _hardened(env, limits_backend="auto")


@_BOTH
def test_checkpointer_and_limits_backend_default_to_auto_and_are_refused(env: str) -> None:
    with pytest.raises(ValidationError, match="auto"):
        _hardened(env, checkpointer=_UNSET, limits_backend=_UNSET)


def test_memory_limits_are_refused_in_production_only() -> None:
    with pytest.raises(ValidationError, match="APP_LIMITS_BACKEND=memory"):
        _hardened("production", limits_backend="memory")
    assert _hardened("staging", limits_backend="memory").limits_backend == "memory"


@pytest.mark.parametrize("env", ["development", "test"])
def test_dev_and_test_keep_auto_defaults(env: str) -> None:
    settings = Settings(env=env)
    assert (settings.checkpointer, settings.limits_backend) == ("memory", "memory")


@_BOTH
def test_empty_allowed_hosts_are_refused(env: str) -> None:
    with pytest.raises(ValidationError, match="APP_ALLOWED_HOSTS"):
        _hardened(env, allowed_hosts=[])
    with pytest.raises(ValidationError, match="APP_ALLOWED_HOSTS"):
        _hardened(env, allowed_hosts=_UNSET)


@_BOTH
def test_an_unparsable_trusted_proxy_is_refused(env: str) -> None:
    with pytest.raises(ValidationError, match="APP_TRUSTED_PROXIES"):
        _hardened(env, trusted_proxies=["10.0.0.0/8", "not-a-cidr"])


@_BOTH
def test_unset_trusted_proxies_are_refused_but_an_explicit_empty_list_is_not(env: str) -> None:
    with pytest.raises(ValidationError, match="APP_TRUSTED_PROXIES must be set"):
        _hardened(env, trusted_proxies=_UNSET)
    assert _hardened(env, trusted_proxies=[]).trusted_proxies == []


def test_trusted_proxies_set_through_the_environment_count_as_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_TRUSTED_PROXIES", "[]")
    assert _hardened("production", trusted_proxies=_UNSET).trusted_proxies == []
    monkeypatch.delenv("APP_TRUSTED_PROXIES")
    with pytest.raises(ValidationError, match="APP_TRUSTED_PROXIES must be set"):
        _hardened("production", trusted_proxies=_UNSET)


@_BOTH
@pytest.mark.parametrize(
    "broad", ["0.0.0.0/0", "::/0", "0.0.0.0/1", "128.0.0.0/1", "::/1", "8000::/1", "10.0.0.0/7"]
)
def test_overly_broad_trusted_proxy_ranges_are_refused(env: str, broad: str) -> None:
    with pytest.raises(ValidationError, match="broader than"):
        _hardened(env, trusted_proxies=["10.0.0.0/8", broad])
    with pytest.raises(ValidationError, match="broader than"):
        _hardened(env, trusted_proxies=["0.0.0.0/1", "128.0.0.0/1"])
    assert _hardened(env, trusted_proxies=["10.0.0.0/8", "fd00::/16"])


@_BOTH
def test_disabled_rate_limit_is_refused(env: str) -> None:
    with pytest.raises(ValidationError, match="APP_RATE_LIMIT_ENABLED"):
        _hardened(env, rate_limit_enabled=False)


@_BOTH
def test_startup_setup_is_refused(env: str) -> None:
    with pytest.raises(ValidationError, match="APP_CHECKPOINTER_SETUP_ON_STARTUP"):
        _hardened(env, checkpointer_setup_on_startup=True)


_DSN = "postgresql://svc:pw-secret-1@db.example.test/neuron"


@pytest.mark.parametrize(
    "dsn",
    [
        _DSN,
        _DSN + "?sslmode=disable",
        _DSN + "?sslmode=prefer",
        _DSN + "?sslmode=require",
        _DSN + "?sslmode=verify-ca",
        _DSN + "?application_name=x&sslmode=require",
        "host=db.example.test user=svc password=pw-secret-1 dbname=neuron sslmode=require",
        "host=db.example.test user=svc password=pw-secret-1 dbname=neuron",
        "postgresql://svc:pw-secret-1@db.example.test/neuron?sslmode=bogus",
    ],
)
def test_production_refuses_a_dsn_below_verify_full(dsn: str) -> None:
    for field in ("postgres_dsn", "postgres_migration_dsn"):
        with pytest.raises(ValidationError, match="sslmode=verify-full") as caught:
            _hardened("production", **{field: dsn})
        assert "pw-secret-1" not in str(caught.value)
        assert "db.example.test" not in str(caught.value)


@pytest.mark.parametrize(
    "dsn",
    [
        _DSN + "?sslmode=verify-full",
        _DSN + "?connect_timeout=5&sslmode=verify-full",
        "host=db.example.test user=svc dbname=neuron sslmode=verify-full",
        # `sslmode` inside the password is not an sslmode.
        "host=db.example.test user=svc password='sslmode=verify-full' sslmode=verify-full",
    ],
)
def test_production_accepts_verify_full_in_either_dsn_form(dsn: str) -> None:
    for field in ("postgres_dsn", "postgres_migration_dsn"):
        assert _hardened("production", **{field: dsn})


def test_a_dsn_that_only_mentions_sslmode_in_the_wrong_place_is_refused() -> None:
    dsn = "host=db.example.test user=svc password='sslmode=verify-full' dbname=neuron"
    with pytest.raises(ValidationError, match="sslmode=verify-full"):
        _hardened("production", postgres_dsn=dsn)


def test_staging_accepts_require_but_nothing_weaker() -> None:
    """ADR 0008 decision 17: free-plan Render staging cannot verify the server certificate."""
    assert _hardened("staging", postgres_dsn=_DSN + "?sslmode=require")
    assert _hardened("staging", postgres_migration_dsn=_DSN + "?sslmode=verify-ca")
    for weaker in ("", "?sslmode=disable", "?sslmode=allow", "?sslmode=prefer"):
        with pytest.raises(ValidationError, match="sslmode=require"):
            _hardened("staging", postgres_dsn=_DSN + weaker)


@_BOTH
def test_a_malformed_dsn_is_refused_without_echoing_it(env: str) -> None:
    with pytest.raises(ValidationError, match="is not valid") as caught:
        _hardened(env, postgres_dsn="postgresql://svc:pw-secret-1@[bad/neuron")
    assert "pw-secret-1" not in str(caught.value)


@pytest.mark.parametrize("env", ["development", "test"])
def test_dev_and_test_do_not_require_tls(env: str) -> None:
    assert Settings(env=env, postgres_dsn=_DSN, checkpointer="postgres")


def test_production_refuses_exposed_api_docs() -> None:
    with pytest.raises(ValidationError, match="APP_EXPOSE_API_DOCS"):
        _hardened("production", expose_api_docs=True)
    assert _hardened("production").expose_api_docs is False
    assert _hardened("staging", expose_api_docs=True).expose_api_docs is True


def test_production_requires_hsts_and_staging_does_not() -> None:
    with pytest.raises(ValidationError, match="APP_HSTS_MAX_AGE_SECONDS"):
        _hardened("production", hsts_max_age_seconds=0)
    assert _hardened("production").hsts_max_age_seconds > 0
    assert _hardened("staging", hsts_max_age_seconds=0).hsts_max_age_seconds == 0


@_BOTH
@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "app.localhost",
        "127.0.0.1",
        "127.1.2.3",
        "[::1]",
        "169.254.169.254",
        "[fe80::1]",
        "10.0.0.5",
        "172.16.0.1",
        "192.168.1.1",
        "[fd00::1]",
        "[::ffff:10.0.0.1]",
        # inet_aton-style spellings of loopback
        "2130706433",
        "0x7f.1",
        "127.1",
        "0x7f000001",
        "0177.0.0.1",
        # embedded IPv4: NAT64 and 6to4 around 127.0.0.1
        "[64:ff9b::7f00:1]",
        "[2002:7f00:1::]",
        "100.64.0.1",
        "224.0.0.1",
        "240.0.0.1",
        "0.0.0.0",  # noqa: S104
        "[::]",
    ],
)
def test_jwks_url_with_an_internal_host_is_refused(env: str, host: str) -> None:
    with pytest.raises(ValidationError, match="non-public"):
        _hardened(env, auth_jwks_url=f"https://{host}:8443/jwks.json")


def test_jwks_url_with_a_public_host_is_accepted_and_development_is_unchanged() -> None:
    assert _hardened("production", auth_jwks_url="https://1.1.1.1/jwks.json")
    assert Settings(
        env="development",
        auth_mode="jwt",
        auth_issuer="http://localhost:8765",
        auth_audience="neuron-api",
        auth_jwks_url="http://127.0.0.1:8765/jwks.json",
        identity_hash_key="x" * 32,
    )


def test_production_refuses_langsmith_content_without_an_approval_record() -> None:
    kwargs: dict[str, object] = {"langsmith_content_approved": True}
    with pytest.raises(ValidationError, match="APPROVAL_RECORD"):
        _hardened("production", **kwargs)
    with pytest.raises(ValidationError, match="APPROVAL_RECORD"):
        _hardened("production", langsmith_content_approval_record="  ", **kwargs)
    approved = _hardened(
        "production", langsmith_content_approval_record="ADR-0009 / ticket 42", **kwargs
    )
    assert approved.langsmith_content_approved is True
    assert _hardened("staging", **kwargs).langsmith_content_approved is True
    assert _hardened("production").langsmith_content_approved is False


def test_validation_errors_never_echo_the_input() -> None:
    with pytest.raises(ValidationError) as caught:
        _hardened("production", postgres_dsn=_DSN, allowed_hosts=[])
    assert "input_value" not in str(caught.value)
    assert "pw-secret-1" not in str(caught.value)


@_BOTH
@pytest.mark.parametrize("pattern", ["*", "*.com", "*.io"])
def test_wildcard_allowed_hosts_over_everything_or_a_tld_are_refused(
    env: str, pattern: str
) -> None:
    with pytest.raises(ValidationError, match="top-level domain"):
        _hardened(env, allowed_hosts=["api.example.test", pattern])
    assert _hardened(env, allowed_hosts=["*.example.test"])


def test_dev_keeps_wildcard_allowed_hosts() -> None:
    assert Settings(env="development", allowed_hosts=["*"]).allowed_hosts == ["*"]


@pytest.mark.parametrize("mode", ["VERIFY-FULL", "Verify-Full", "verify-full ", " verify-full"])
def test_uppercase_or_padded_sslmode_is_refused(mode: str) -> None:
    with pytest.raises(ValidationError, match="sslmode"):
        _hardened("production", postgres_dsn=_DSN + "?sslmode=" + mode.replace(" ", "%20"))
    with pytest.raises(ValidationError, match="sslmode"):
        _hardened("production", postgres_dsn=f"host=h user=svc dbname=n sslmode='{mode}'")


@_BOTH
def test_pgsslmode_in_the_environment_does_not_satisfy_the_rule(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    monkeypatch.setenv("PGSSLMODE", "verify-full")
    with pytest.raises(ValidationError, match="sslmode"):
        _hardened(env, postgres_dsn=_DSN)


def test_an_empty_trusted_proxies_variable_is_rejected_by_settings_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operators must write APP_TRUSTED_PROXIES=[]; an empty value is not an empty list."""
    monkeypatch.setenv("APP_TRUSTED_PROXIES", "")
    with pytest.raises(Exception, match="trusted_proxies|TRUSTED_PROXIES"):
        Settings(env="test")
