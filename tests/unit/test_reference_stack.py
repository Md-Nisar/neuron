"""`docker-compose.reference.yml` checks (ADR 0012 decision 3; #325). No network, no Docker."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
_COMPOSE = yaml.safe_load((_ROOT / "docker-compose.reference.yml").read_text(encoding="utf-8"))
_SERVICES: dict[str, dict[str, Any]] = _COMPOSE["services"]
_API = ("api1", "api2")


def test_two_api_replicas_run_a_passed_in_image() -> None:
    for name in (*_API, "setup"):
        service = _SERVICES[name]
        assert "build" not in service, name
        assert service["image"].startswith("${NEURON_IMAGE:?"), name
        assert service["pull_policy"] == "never", name


@pytest.mark.parametrize("name", ["postgres", "keycloak", *_API])
def test_every_published_port_binds_to_loopback(name: str) -> None:
    for port in _SERVICES[name]["ports"]:
        assert port.startswith("127.0.0.1:"), port


@pytest.mark.parametrize("name", _API)
def test_replicas_use_jwt_and_shared_postgres_backends(name: str) -> None:
    env = _SERVICES[name]["environment"]
    assert env["APP_AUTH_MODE"] == "jwt"
    assert env["APP_LIMITS_BACKEND"] == "postgres"
    assert env["APP_CHECKPOINTER"] == "postgres"
    assert env["APP_RATE_LIMIT_ENABLED"] == "true"
    assert "APP_CHECKPOINTER_SETUP_ON_STARTUP" not in env


def test_runtime_and_migration_use_different_database_roles() -> None:
    api = _SERVICES["api1"]["environment"]["APP_POSTGRES_DSN"]
    migration = _SERVICES["setup"]["environment"]["APP_POSTGRES_MIGRATION_DSN"]
    assert "neuron_app:" in api
    assert "neuron_migrator:" in migration
    assert "APP_POSTGRES_MIGRATION_DSN" not in _SERVICES["api1"]["environment"]


def test_replicas_wait_for_setup_and_the_identity_provider() -> None:
    depends = _SERVICES["api1"]["depends_on"]
    assert depends["setup"]["condition"] == "service_completed_successfully"
    assert depends["keycloak"]["condition"] == "service_healthy"


def test_the_stack_is_development_only() -> None:
    # The fake model's latency settings are refused in staging/production by design.
    assert _SERVICES["api1"]["environment"]["APP_ENV"] == "development"
    assert "OPENAI_API_KEY" not in _SERVICES["api1"]["environment"]
