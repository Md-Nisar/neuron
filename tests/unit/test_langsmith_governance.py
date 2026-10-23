from __future__ import annotations

import importlib
from collections.abc import Iterator
from typing import Any, cast

import pytest
import structlog.testing
from langsmith import run_trees
from langsmith import utils as ls_utils
from tests.conftest import PRODUCTION_PROFILE

from neuron_agent.api import main as api_main
from neuron_agent.config.settings import Settings
from neuron_agent.graphs import main_graph
from neuron_agent.observability import langsmith_governance
from neuron_agent.observability.langsmith_governance import configure_langsmith

_TRACING_ALIASES = (
    "LANGSMITH_TRACING",
    "LANGSMITH_TRACING_V2",
    "LANGCHAIN_TRACING_V2",
    "LANGCHAIN_TRACING",
)
_HIDE_VARS = (
    "LANGSMITH_HIDE_INPUTS",
    "LANGSMITH_HIDE_OUTPUTS",
    "LANGCHAIN_HIDE_INPUTS",
    "LANGCHAIN_HIDE_OUTPUTS",
)


def _reset_langsmith_state() -> None:
    cast(Any, ls_utils.get_env_var).cache_clear()
    run_trees.configure(client=None)


@pytest.fixture(autouse=True)
def clean_langsmith_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Start from no LangSmith variables; monkeypatch restores whatever the process had."""
    for name in (*_TRACING_ALIASES, *_HIDE_VARS):
        monkeypatch.delenv(name, raising=False)
    _reset_langsmith_state()
    yield
    monkeypatch.undo()
    _reset_langsmith_state()


_PROD_LIKE = {
    **PRODUCTION_PROFILE,
    "auth_mode": "jwt",
    "auth_issuer": "https://issuer.example",
    "auth_audience": "neuron",
    "auth_jwks_url": "https://issuer.example/jwks.json",
    "identity_hash_key": "k" * 32,
}


def _settings(env: str = "development", **overrides: Any) -> Settings:
    overrides.setdefault("langsmith_api_key", "lsv2-test")
    if env in {"staging", "production"}:
        overrides = {**_PROD_LIKE, **overrides}
    if env == "production" and overrides.get("langsmith_content_approved"):
        overrides.setdefault("langsmith_content_approval_record", "ticket-1")
    return Settings(env=env, openai_api_key="sk-test", **overrides)


def _hidden() -> tuple[bool, bool]:
    """What a LangSmith client built now would do (it reads these exact lookups)."""
    return (
        ls_utils.get_env_var("HIDE_INPUTS") == "true",
        ls_utils.get_env_var("HIDE_OUTPUTS") == "true",
    )


def test_langsmith_is_off_by_default() -> None:
    configure_langsmith(_settings(enable_langsmith=False))

    assert ls_utils.tracing_is_enabled() is False


def test_app_switch_enables_tracing() -> None:
    configure_langsmith(_settings(enable_langsmith=True))

    assert ls_utils.tracing_is_enabled() is True


@pytest.mark.parametrize("alias", _TRACING_ALIASES)
def test_shell_tracing_variable_is_overridden_and_logged(
    monkeypatch: pytest.MonkeyPatch, alias: str
) -> None:
    monkeypatch.setenv(alias, "true")
    _reset_langsmith_state()

    with structlog.testing.capture_logs() as logs:
        configure_langsmith(_settings(enable_langsmith=False))

    assert ls_utils.tracing_is_enabled() is False
    overridden = [log for log in logs if log["event"] == "langsmith_tracing_overridden"]
    assert len(overridden) == 1
    assert overridden[0]["variables"] == [alias]


def test_override_is_logged_once_when_called_from_both_entry_points(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")

    with structlog.testing.capture_logs() as logs:
        configure_langsmith(_settings())
        configure_langsmith(_settings())

    assert [log["event"] for log in logs].count("langsmith_tracing_overridden") == 1


def test_no_override_log_when_nothing_was_set() -> None:
    with structlog.testing.capture_logs() as logs:
        configure_langsmith(_settings(enable_langsmith=False))

    assert "langsmith_tracing_overridden" not in [log["event"] for log in logs]


def test_stale_shell_false_does_not_disable_the_app_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING_V2", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    _reset_langsmith_state()

    configure_langsmith(_settings(enable_langsmith=True))

    assert ls_utils.tracing_is_enabled() is True


def test_cached_environment_lookups_do_not_defeat_the_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    _reset_langsmith_state()
    assert ls_utils.tracing_is_enabled() is True  # primes LangSmith's env cache

    configure_langsmith(_settings(enable_langsmith=False))

    assert ls_utils.tracing_is_enabled() is False


@pytest.mark.parametrize(
    ("env", "approved", "hidden"),
    [
        ("development", False, False),
        ("development", True, False),
        ("test", False, True),
        ("test", True, False),
        ("staging", False, True),
        ("staging", True, False),
        ("production", False, True),
        ("production", True, False),
    ],
)
def test_content_visibility_per_environment(env: str, approved: bool, hidden: bool) -> None:
    configure_langsmith(_settings(env, enable_langsmith=True, langsmith_content_approved=approved))

    assert _hidden() == (hidden, hidden)


@pytest.mark.parametrize("env", ["test", "staging", "production"])
def test_shell_show_content_variable_cannot_unhide_outside_development(
    monkeypatch: pytest.MonkeyPatch, env: str
) -> None:
    monkeypatch.setenv("LANGSMITH_HIDE_INPUTS", "false")
    monkeypatch.setenv("LANGCHAIN_HIDE_OUTPUTS", "false")
    _reset_langsmith_state()

    configure_langsmith(_settings(env, enable_langsmith=True))

    assert _hidden() == (True, True)


def test_development_leaves_a_shell_hide_choice_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_HIDE_INPUTS", "true")
    _reset_langsmith_state()

    configure_langsmith(_settings("development", enable_langsmith=True))

    assert _hidden() == (True, False)


def test_content_is_hidden_even_when_langsmith_is_disabled_outside_development() -> None:
    """A later `ls.configure`/shell enablement must still find content hidden."""
    configure_langsmith(_settings("production", enable_langsmith=False))

    assert _hidden() == (True, True)


@pytest.mark.parametrize("env", ["staging", "production"])
def test_enabled_langsmith_requires_api_key_in_staging_and_production(env: str) -> None:
    with pytest.raises(ValueError, match="LANGSMITH_API_KEY"):
        _settings(env, enable_langsmith=True, langsmith_api_key=None)


@pytest.mark.parametrize("env", ["development", "test"])
def test_api_key_is_not_required_in_development_and_test(env: str) -> None:
    settings = Settings(env=env, enable_langsmith=True, langsmith_api_key=None)

    assert settings.langsmith_api_key is None


@pytest.mark.parametrize("env", ["staging", "production"])
def test_api_key_is_not_required_when_langsmith_is_disabled(env: str) -> None:
    settings = _settings(env, enable_langsmith=False, langsmith_api_key=None)

    assert settings.langsmith_api_key is None


def test_api_key_is_read_under_its_conventional_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-from-env")

    settings = Settings(env="test")

    assert settings.langsmith_api_key is not None
    assert settings.langsmith_api_key.get_secret_value() == "lsv2-from-env"


def test_empty_api_key_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_API_KEY", "")

    with pytest.raises(ValueError, match="LANGSMITH_API_KEY"):
        Settings(env="production", openai_api_key="sk-test", enable_langsmith=True, **_PROD_LIKE)


def test_content_approval_defaults_to_false() -> None:
    assert Settings(env="test").langsmith_content_approved is False


def test_graph_module_and_api_both_apply_governance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Agent Server loads only the graph module, so it must configure LangSmith itself."""
    calls: list[Settings] = []
    monkeypatch.setattr(langsmith_governance, "configure_langsmith", calls.append)
    try:
        importlib.reload(main_graph)
    finally:
        monkeypatch.undo()
        importlib.reload(main_graph)

    assert len(calls) == 1
    assert api_main.configure_langsmith is configure_langsmith


def test_enabling_never_turns_on_the_removed_v1_tracer(monkeypatch: pytest.MonkeyPatch) -> None:
    """LangChain raises if `LANGCHAIN_TRACING` is set while v2 tracing is off for a run."""
    from langchain_core.callbacks.manager import CallbackManager
    from langsmith.run_helpers import tracing_context

    monkeypatch.setenv("LANGCHAIN_TRACING", "true")
    configure_langsmith(_settings(enable_langsmith=True))

    assert ls_utils.tracing_is_enabled() is True
    with tracing_context(enabled=False):
        CallbackManager.configure()
