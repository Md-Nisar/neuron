"""`render.yaml` Blueprint checks (ADR 0008 decisions 1, 10 and 15; #150). No network.

The file is parsed as data. Render's own validation and a real staging deploy are separate
acceptance steps that need a Render account.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import AliasChoices

from neuron_agent.config.settings import Settings

_BLUEPRINT = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "render.yaml").read_text(encoding="utf-8")
)
_SERVICES: list[dict[str, Any]] = _BLUEPRINT["services"]
_GROUPS: dict[str, dict[str, str]] = {
    g["name"]: {e["key"]: str(e["value"]) for e in g["envVars"]} for g in _BLUEPRINT["envVarGroups"]
}
_WEB = [s for s in _SERVICES if s["type"] == "web"]
_CRON = [s for s in _SERVICES if s["type"] == "cron"]
_COLLECTORS = [s for s in _SERVICES if s["type"] == "pserv"]
_IMAGE_PLACEHOLDER = "ghcr.io/md-nisar/neuron"
_CLI = "python -m neuron_agent.persistence.cli"
# Secrets the web service holds and no other role may reference.
_WEB_ONLY_SECRETS = {"APP_POSTGRES_MIGRATION_DSN"}
_SECRET_KEY = re.compile(r"(DSN|KEY|TOKEN|SECRET|PASSWORD|HEADER|BACKEND_ENDPOINT)")


def _settings_names() -> set[str]:
    names: set[str] = set()
    for name, field in Settings.model_fields.items():
        alias = field.validation_alias
        if isinstance(alias, AliasChoices):
            names.update(str(choice) for choice in alias.choices)
        elif isinstance(alias, str):
            names.add(alias)
        else:
            names.add(f"APP_{name.upper()}")
    return names


def _groups_of(service: dict[str, Any]) -> list[str]:
    return [e["fromGroup"] for e in service["envVars"] if "fromGroup" in e]


def _env(service: dict[str, Any]) -> dict[str, str]:
    """The non-secret values a service sees: its groups, then its own `value` entries."""
    values: dict[str, str] = {}
    for group in _groups_of(service):
        values.update(_GROUPS[group])
    values.update({e["key"]: str(e["value"]) for e in service["envVars"] if "value" in e})
    return values


def _secret_keys(service: dict[str, Any]) -> set[str]:
    return {e["key"] for e in service["envVars"] if e.get("sync") is False}


def _by_env(services: list[dict[str, Any]], env: str) -> list[dict[str, Any]]:
    return [s for s in services if _env(s).get("APP_ENV") == env or s["name"].endswith(env)]


def _timeout_floor(env: dict[str, str]) -> float:
    settings_defaults = Settings.model_fields
    run = int(env.get("APP_RUN_TIMEOUT_SECONDS", settings_defaults["run_timeout_seconds"].default))
    drain = float(
        env.get("APP_SHUTDOWN_DRAIN_SECONDS", settings_defaults["shutdown_drain_seconds"].default)
    )
    flush = 0.0
    if env.get("APP_OTEL_ENABLED", "false") == "true":
        export = float(
            env.get(
                "APP_OTEL_EXPORT_TIMEOUT_SECONDS",
                settings_defaults["otel_export_timeout_seconds"].default,
            )
        )
        flush = 2 * export  # the telemetry flush when the Collector is down
    return drain + run + 10 + flush


def test_one_blueprint_defines_both_environments() -> None:
    assert sorted(s["name"] for s in _WEB) == ["neuron-production", "neuron-staging"]
    assert len(_BLUEPRINT["databases"]) == 2
    assert len(_CRON) == 2
    assert len(_COLLECTORS) == 2


@pytest.mark.parametrize("service", _WEB, ids=lambda s: s["name"])
def test_web_service_shape(service: dict[str, Any]) -> None:
    env = _env(service)
    assert service["runtime"] == "image"
    assert service["image"]["url"].startswith("ghcr.io/md-nisar/neuron")
    url = service["image"]["url"]
    # Deploy by digest. The shipped file carries the untagged placeholder and must be replaced
    # with `@sha256:<digest>` before the first sync; a mutable tag is never acceptable.
    assert "@sha256:" in url or url == _IMAGE_PLACEHOLDER
    assert service["healthCheckPath"] == "/health/ready"
    assert service["preDeployCommand"] == f"{_CLI} setup"
    assert env["APP_ENV"] in {"staging", "production"}
    assert "APP_POSTGRES_MIGRATION_DSN" in {e["key"] for e in service["envVars"] if "key" in e}
    assert env["APP_AUTH_MODE"] == "jwt"
    assert env["APP_EXPOSE_API_DOCS"] == "false"
    assert env["APP_CHECKPOINTER"] == "postgres"
    assert "APP_TRUSTED_PROXIES" in env
    assert env["APP_ALLOWED_HOSTS"]
    assert "APP_CHECKPOINTER_SETUP_ON_STARTUP" not in env
    assert service["numInstances"] == (2 if env["APP_ENV"] == "production" else 1)
    assert service["maxShutdownDelaySeconds"] > _timeout_floor(env)
    assert service["maxShutdownDelaySeconds"] <= 300  # Render's documented maximum


def test_limits_backend_and_production_settings() -> None:
    for service in _WEB:
        env = _env(service)
        if env["APP_ENV"] == "production":
            assert env["APP_LIMITS_BACKEND"] == "postgres"
            assert int(env["APP_HSTS_MAX_AGE_SECONDS"]) > 0
        elif env["APP_LIMITS_BACKEND"] == "memory":
            assert service["numInstances"] == 1  # per-process guards need one instance
        else:
            assert env["APP_LIMITS_BACKEND"] == "postgres"


def test_audiences_differ_between_environments() -> None:
    audiences = {_env(s)["APP_AUTH_AUDIENCE"] for s in _WEB}
    assert len(audiences) == len(_WEB) == 2


@pytest.mark.parametrize("service", _CRON, ids=lambda s: s["name"])
def test_cron_service_shape(service: dict[str, Any]) -> None:
    assert service["dockerCommand"] == f"{_CLI} prune"
    assert service["schedule"].split()[2:] == ["*", "*", "*"]  # daily
    assert "preDeployCommand" not in service


def test_databases_accept_no_outside_connections() -> None:
    for database in _BLUEPRINT["databases"]:
        assert database["ipAllowList"] == []


def test_every_app_key_is_a_known_setting() -> None:
    known = _settings_names()
    keys = {k for group in _GROUPS.values() for k in group}
    for service in _SERVICES:
        keys |= {e["key"] for e in service["envVars"] if "key" in e}
    unknown = {k for k in keys if k.startswith("APP_") and k not in known}
    assert not unknown


def test_no_secret_value_in_the_blueprint() -> None:
    entries = [e for g in _BLUEPRINT["envVarGroups"] for e in g["envVars"]]
    entries += [e for s in _SERVICES for e in s["envVars"] if "key" in e]
    for entry in entries:
        if _SECRET_KEY.search(entry["key"]) and not entry["key"].endswith("_SECONDS"):
            assert entry.get("sync") is False
            assert "value" not in entry
            assert "fromDatabase" not in entry
            assert "generateValue" not in entry
        if "sync" in entry:
            assert entry["sync"] is False
        assert "fromDatabase" not in entry  # the runtime DSN is the app role's, never the owner's
    # Render rejects sync:false in a group, so a group can never hold a secret.
    for group in _BLUEPRINT["envVarGroups"]:
        assert all("sync" not in e for e in group["envVars"])
    text = (Path(__file__).resolve().parents[2] / "render.yaml").read_text(encoding="utf-8")
    assert not re.search(r"postgres(ql)?://|sk-|-----BEGIN", text)


def test_cron_and_collector_reference_no_web_group_or_secret() -> None:
    web_groups = {g for s in _WEB for g in _groups_of(s)}
    for service in _CRON + _COLLECTORS:
        assert not web_groups & set(_groups_of(service)), service["name"]
        assert not _WEB_ONLY_SECRETS & _secret_keys(service), service["name"]
    for service in _COLLECTORS:
        # The Collector never sees the database or the provider key.
        assert all(
            not k.startswith("APP_") and k != "OPENAI_API_KEY" for k in _secret_keys(service)
        )
        assert all(not k.startswith("APP_") for g in _groups_of(service) for k in _GROUPS[g])


def test_each_environment_uses_its_own_groups() -> None:
    for env in ("staging", "production"):
        names = {g for s in _by_env(_SERVICES, env) for g in _groups_of(s)}
        assert names == {f"neuron-{role}-{env}" for role in ("web", "cron", "collector")}


_FAKE_SECRETS = {
    "OPENAI_API_KEY": "sk-test-not-real",
    "APP_IDENTITY_HASH_KEY": "h" * 32,
    "APP_AUTH_ISSUER": "https://issuer.example.test/",
    "APP_AUTH_JWKS_URL": "https://issuer.example.test/.well-known/jwks.json",
}


@pytest.mark.parametrize("env", ["staging", "production"])
def test_blueprint_values_pass_settings_validation(
    env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Web, migration (pre-deploy) and cron processes each load valid `Settings`."""
    sslmode = "verify-full" if env == "production" else "require"
    dsn = f"postgresql://{{user}}:pw@db.example.test/neuron?sslmode={sslmode}"
    roles = {"APP_POSTGRES_DSN": dsn.format(user="neuron_app")}
    migration = {"APP_POSTGRES_MIGRATION_DSN": dsn.format(user="neuron_migrator")}
    for service in _by_env(_WEB + _CRON, env):
        for name in [n for n in list(os.environ) if n.startswith("APP_")]:
            monkeypatch.delenv(name)
        values = {**_env(service), **_FAKE_SECRETS, **roles}
        if service["type"] == "web":
            values.update(migration)  # the pre-deploy command shares this environment
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        settings = Settings(_env_file=None)  # type: ignore[call-arg]
        assert settings.env == env
        assert settings.limits_backend == "postgres"
        assert settings.checkpointer == "postgres"
        assert settings.expose_api_docs is False
        assert settings.auth_mode == "jwt"
