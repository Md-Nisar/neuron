"""The development Keycloak realm and its API settings (ADR 0010, decision 5)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from scripts import dev_keycloak
from tests.conftest import PRODUCTION_PROFILE

from neuron_agent.config.settings import Settings

REALM_PATH = Path(__file__).resolve().parents[2] / "deploy" / "keycloak" / "neuron-realm.json"
_FORBIDDEN_KEYS = ("secret", "privatekey", "certificate", "keystore", "smtp")


@pytest.fixture(scope="module")
def realm() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(REALM_PATH.read_text(encoding="utf-8"))
    return loaded


def _client(realm: dict[str, Any], client_id: str) -> dict[str, Any]:
    (client,) = (c for c in realm["clients"] if c["clientId"] == client_id)
    return client  # type: ignore[no-any-return]


def _mapper(client: dict[str, Any], kind: str) -> dict[str, Any]:
    (mapper,) = (m for m in client["protocolMappers"] if m["protocolMapper"] == kind)
    return mapper  # type: ignore[no-any-return]


def test_web_client_is_a_public_pkce_code_flow_client(realm: dict[str, Any]) -> None:
    client = _client(realm, "neuron-web")

    assert client["publicClient"] is True
    assert client["standardFlowEnabled"] is True
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    # No implicit, password or service-account grants for the browser client.
    assert not client["implicitFlowEnabled"]
    assert not client["directAccessGrantsEnabled"]
    assert not client["serviceAccountsEnabled"]
    # Exact origins and a loopback redirect: no wildcard host.
    assert client["webOrigins"] == ["http://localhost:5173"]
    # Fixed allow-list, no wildcard: the sign-in redirect and the sign-out redirect (#282).
    assert client["redirectUris"] == ["http://localhost:5173/"]
    assert client["attributes"]["post.logout.redirect.uris"] == "http://localhost:5173/"


@pytest.mark.parametrize("client_id", ["neuron-web", "neuron-dev-test"])
def test_tokens_carry_the_api_audience_and_a_top_level_roles_claim(
    realm: dict[str, Any], client_id: str
) -> None:
    client = _client(realm, client_id)

    audience = _mapper(client, "oidc-audience-mapper")["config"]
    assert audience["included.custom.audience"] == dev_keycloak.AUDIENCE == "neuron-api"
    assert audience["access.token.claim"] == "true"
    roles = _mapper(client, "oidc-usermodel-realm-role-mapper")["config"]
    assert roles["claim.name"] == "roles"
    assert roles["multivalued"] == "true"
    assert roles["access.token.claim"] == "true"


def test_two_users_have_different_roles_that_the_api_maps(realm: dict[str, Any]) -> None:
    roles_by_user = {user["username"]: user["realmRoles"] for user in realm["users"]}

    assert roles_by_user == {"alice": ["neuron-user"], "bob": ["neuron-reader"]}
    defined = {role["name"] for role in realm["roles"]["realm"]}
    assert defined == set(dev_keycloak.ROLE_PERMISSIONS)
    assert "agent:invoke" in dev_keycloak.ROLE_PERMISSIONS["neuron-user"]
    assert "agent:invoke" not in dev_keycloak.ROLE_PERMISSIONS["neuron-reader"]


def test_realm_export_holds_no_real_credentials(realm: dict[str, Any]) -> None:
    def walk(node: Any, path: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                assert not any(bad in key.lower() for bad in _FORBIDDEN_KEYS), f"{path}/{key}"
                walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(realm)
    passwords = [c["value"] for u in realm["users"] for c in u["credentials"]]
    assert passwords
    assert all(p.startswith("dev-only-") for p in passwords)
    assert all(u["email"].endswith(".invalid") for u in realm["users"])
    assert realm["registrationAllowed"] is False
    assert realm["sslRequired"] != "none"


def test_env_block_is_accepted_by_settings_in_development(monkeypatch: pytest.MonkeyPatch) -> None:
    for line in dev_keycloak.env_block().splitlines():
        if "=" in line and not line.startswith("#"):
            name, value = line.split("=", 1)
            monkeypatch.setenv(name, value)
    monkeypatch.setenv("APP_ENV", "development")

    settings = Settings()

    assert settings.auth_mode == "jwt"
    assert settings.auth_issuer == "http://localhost:8180/realms/neuron"
    assert settings.auth_audience == "neuron-api"
    assert settings.auth_algorithms == ["RS256"]
    assert settings.auth_role_permissions == dev_keycloak.ROLE_PERMISSIONS


def test_http_identity_provider_is_still_refused_outside_development() -> None:
    issuer = "http://localhost:8180/realms/neuron"
    with pytest.raises(ValidationError, match="APP_AUTH_JWKS_URL must use HTTPS"):
        Settings(
            env="production",
            auth_mode="jwt",
            auth_issuer=issuer,
            auth_audience="neuron-api",
            auth_jwks_url=f"{issuer}/protocol/openid-connect/certs",
            identity_hash_key="x" * 32,
            openai_api_key="sk-test",
            **PRODUCTION_PROFILE,
        )


@pytest.mark.parametrize("client_id", ["neuron-web", "neuron-dev-test"])
def test_realm_roles_can_reach_the_token(realm: dict[str, Any], client_id: str) -> None:
    """With full scope off and no scope mappings, Keycloak drops realm roles: `roles` is empty."""
    client = _client(realm, client_id)
    mapped = {
        role
        for mapping in realm.get("scopeMappings", [])
        if mapping["client"] == client_id
        for role in mapping["roles"]
    }

    assert client["fullScopeAllowed"] is True or mapped >= set(dev_keycloak.ROLE_PERMISSIONS)
