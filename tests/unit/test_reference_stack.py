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


@pytest.mark.parametrize("name", _API)
def test_browser_origins_are_configurable_and_closed_by_default(name: str) -> None:
    # The web app needs this to reach the stack; with nothing set no origin is allowed.
    assert _SERVICES[name]["environment"]["APP_CORS_ALLOWED_ORIGINS"] == (
        "${CORS_ALLOWED_ORIGINS:-[]}"
    )


def test_the_worker_runs_as_its_own_role_only_with_knowledge() -> None:
    worker = _SERVICES["worker"]
    assert worker["profiles"] == ["knowledge"]
    assert worker["command"] == ["neuron-worker"]
    assert worker["healthcheck"]["test"] == ["CMD", "neuron-worker", "health"]
    assert worker["environment"]["APP_POSTGRES_WORKER_DSN"].startswith(
        "postgresql://neuron_worker@"
    )
    assert worker["depends_on"]["setup"]["condition"] == "service_completed_successfully"
    # Docker's stop timeout outlasts the 30 s drain, so SIGKILL never cuts a drain short.
    assert int(worker["stop_grace_period"].rstrip("s")) > 30
    assert "ports" not in worker
    assert set(worker["environment"]) == {
        "APP_ENV",
        "APP_POSTGRES_WORKER_DSN",
        "APP_KNOWLEDGE_PARSER_URL",
        "APP_KNOWLEDGE_BLOB_ROOT",
        "APP_KNOWLEDGE_EMBEDDING_PROVIDER",
        "PGPASSWORD",
    }
    assert "neuron_worker" in (_ROOT / "deploy/reference/init-roles.sql").read_text("utf-8")


def test_replicas_and_worker_share_one_blob_volume() -> None:
    """RAG-08.04: a file uploaded through either replica is the one the worker reads."""
    mount = "knowledge-blobs:/var/lib/neuron/knowledge-blobs"
    for name in (*_API, "worker"):
        service = _SERVICES[name]
        assert service["volumes"] == [mount], name
        assert service["environment"]["APP_KNOWLEDGE_BLOB_ROOT"] == mount.split(":")[1], name
    assert "knowledge-blobs" in _COMPOSE["volumes"]


def test_the_parser_has_no_route_out() -> None:
    """RAG-02.02 AC5: docling-serve is only on an internal network, which has no egress."""
    docling, worker = _SERVICES["docling"], _SERVICES["worker"]
    assert docling["profiles"] == ["knowledge"]
    assert docling["networks"] == ["parser"]
    assert _COMPOSE["networks"]["parser"] == {"internal": True}
    assert "ports" not in docling
    assert "@sha256:" in docling["image"]
    for flag in ("ENABLE_REMOTE_SERVICES", "ALLOW_EXTERNAL_PLUGINS"):
        assert docling["environment"][f"DOCLING_SERVE_{flag}"] == "false", flag
    assert not {"network_mode", "extra_hosts", "expose"} & set(docling)
    assert (docling["read_only"], docling["cap_drop"]) == (True, ["ALL"])
    # Only the worker shares the parser's network, and it reaches docling-serve by name.
    others = [
        name for name, service in _SERVICES.items() if "parser" in service.get("networks", [])
    ]
    assert sorted(others) == ["docling", "worker"]
    assert worker["environment"]["APP_KNOWLEDGE_PARSER_URL"] == "http://docling:5001"
    assert worker["depends_on"]["docling"]["condition"] == "service_healthy"
    assert not {"ports", "expose"} & set(worker)  # nothing for a compromised parser to call
