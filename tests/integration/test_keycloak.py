"""The API accepts tokens from the development Keycloak and refuses bad ones (ADR 0010).

Needs the compose `keycloak` profile running (`docker compose --profile keycloak up
keycloak`); set APP_TEST_KEYCLOAK_URL (default http://localhost:8180) to point elsewhere.
Excluded from `make test` by the `integration` marker.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request

import anyio
import pytest
from scripts import dev_keycloak

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import AuthenticationError
from neuron_agent.security.auth import Principal, TokenVerifier

pytestmark = pytest.mark.integration

_BASE = os.environ.get("APP_TEST_KEYCLOAK_URL", dev_keycloak.KEYCLOAK_URL).rstrip("/")
_ISSUER = f"{_BASE}/realms/{dev_keycloak.REALM}"


def _password_grant(username: str) -> str:
    body = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": "neuron-dev-test",
            "username": username,
            "password": f"dev-only-{username}",
        }
    ).encode()
    request = urllib.request.Request(  # noqa: S310 - fixed development URL
        f"{_ISSUER}/protocol/openid-connect/token", data=body, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            token = json.load(response)["access_token"]
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(f"development Keycloak is not reachable at {_BASE}: {exc}")
    assert isinstance(token, str)
    return token


def _settings(**overrides: object) -> Settings:
    return Settings(
        **{
            "env": "development",
            "auth_mode": "jwt",
            "auth_issuer": _ISSUER,
            "auth_audience": dev_keycloak.AUDIENCE,
            "auth_jwks_url": f"{_ISSUER}/protocol/openid-connect/certs",
            "auth_algorithms": ["RS256"],
            "auth_role_permissions": dev_keycloak.ROLE_PERMISSIONS,
            "identity_hash_key": "x" * 32,
            **overrides,
        }
    )


def _verify(settings: Settings, token: str) -> Principal:
    return anyio.run(TokenVerifier(settings).verify, f"Bearer {token}")


def _segment(data: object) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_users_get_permissions_from_their_realm_roles() -> None:
    alice = _verify(_settings(), _password_grant("alice"))
    bob = _verify(_settings(), _password_grant("bob"))

    assert "agent:invoke" in alice.scopes
    assert "threads:read" in bob.scopes
    assert "agent:invoke" not in bob.scopes
    assert alice.subject != bob.subject


def test_token_for_another_audience_is_refused() -> None:
    with pytest.raises(AuthenticationError):
        _verify(_settings(auth_audience="some-other-api"), _password_grant("alice"))


def test_unsigned_token_with_real_claims_is_refused() -> None:
    real = _password_grant("alice")
    claims = json.loads(base64.urlsafe_b64decode(real.split(".")[1] + "=="))
    forged = f"{_segment({'alg': 'none', 'typ': 'JWT', 'kid': 'x'})}.{_segment(claims)}."

    with pytest.raises(AuthenticationError):
        _verify(_settings(), forged)
    with pytest.raises(AuthenticationError):
        _verify(_settings(auth_algorithms=["RS256", "ES256"]), forged)
