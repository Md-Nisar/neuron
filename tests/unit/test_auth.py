from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError

from neuron_agent.api import main as api_main
from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import AuthenticationError, AuthenticationUnavailableError
from neuron_agent.security.auth import TokenVerifier


class FakeJWKClient:
    def __init__(self, key: Any) -> None:
        self.key = key

    def get_signing_key_from_jwt(self, token: str) -> Any:
        return SimpleNamespace(key=self.key)


def _settings() -> Settings:
    return Settings(
        env="test",
        auth_mode="jwt",
        auth_issuer="https://issuer.example.test",
        auth_audience="neuron-api",
        auth_jwks_url="https://issuer.example.test/.well-known/jwks.json",
        identity_hash_key="x" * 32,
        openai_api_key=None,
    )


def _key_pair() -> tuple[Any, Any]:
    private = rsa.generate_private_key(public_exponent=65_537, key_size=2048)
    return private, private.public_key()


def _token(private: Any, **overrides: Any) -> str:
    now = datetime.now(UTC)
    claims = {
        "iss": "https://issuer.example.test",
        "aud": "neuron-api",
        "sub": "user-123",
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(minutes=5),
        "jti": "opaque-id",
        "scope": "agent:invoke threads:read",
        **overrides,
    }
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": "key-1"})


@pytest.mark.anyio
async def test_verify_returns_principal_without_raw_claims_in_extra_state() -> None:
    private, public = _key_pair()
    verifier = TokenVerifier(_settings())
    verifier._client = FakeJWKClient(public)  # type: ignore[assignment]

    principal = await verifier.verify(f"Bearer {_token(private)}")

    assert principal.issuer == "https://issuer.example.test"
    assert principal.subject == "user-123"
    assert principal.scopes == {"agent:invoke", "threads:read"}
    assert principal.token_id == "opaque-id"  # noqa: S105


@pytest.mark.anyio
async def test_verify_rejects_missing_or_malformed_bearer_tokens() -> None:
    verifier = TokenVerifier(_settings())

    for header in [None, "Basic abc", "Bearer", "Bearer one two"]:
        with pytest.raises(AuthenticationError):
            await verifier.verify(header)


@pytest.mark.anyio
async def test_verify_rejects_expired_token() -> None:
    private, public = _key_pair()
    verifier = TokenVerifier(_settings())
    verifier._client = FakeJWKClient(public)  # type: ignore[assignment]

    with pytest.raises(AuthenticationError):
        await verifier.verify(
            f"Bearer {_token(private, exp=datetime.now(UTC) - timedelta(minutes=1))}"
        )


@pytest.mark.anyio
async def test_verify_rejects_wrong_issuer_audience_and_oversized_token() -> None:
    private, public = _key_pair()
    verifier = TokenVerifier(_settings())
    verifier._client = FakeJWKClient(public)  # type: ignore[assignment]

    for claims in [{"iss": "https://other.example.test"}, {"aud": "other-api"}]:
        with pytest.raises(AuthenticationError):
            await verifier.verify(f"Bearer {_token(private, **claims)}")
    with pytest.raises(AuthenticationError):
        await verifier.verify(f"Bearer {'x' * (_settings().auth_token_max_bytes + 1)}")


@pytest.mark.anyio
async def test_unknown_key_refresh_is_rate_limited() -> None:
    private, _ = _key_pair()
    verifier = TokenVerifier(_settings())

    class MissingKeyClient:
        calls = 0

        def get_signing_key_from_jwt(self, token: str) -> Any:
            self.calls += 1
            raise PyJWKClientError("unknown key")

    client = MissingKeyClient()
    verifier._client = client  # type: ignore[assignment]
    encoded = f"Bearer {_token(private)}"
    with pytest.raises(AuthenticationError):
        await verifier.verify(encoded)
    with pytest.raises(AuthenticationError):
        await verifier.verify(encoded)
    assert client.calls == 1


@pytest.mark.anyio
async def test_verify_fails_closed_when_jwks_is_unavailable() -> None:
    private, _ = _key_pair()
    verifier = TokenVerifier(_settings())

    class UnavailableClient:
        def get_signing_key_from_jwt(self, token: str) -> Any:
            raise PyJWKClientConnectionError("identity provider unavailable")

    verifier._client = UnavailableClient()  # type: ignore[assignment]

    with pytest.raises(AuthenticationUnavailableError):
        await verifier.verify(f"Bearer {_token(private)}")
    assert await verifier.ready() is False


def test_jwt_settings_require_identity_provider_configuration() -> None:
    with pytest.raises(ValueError, match="APP_AUTH_ISSUER"):
        Settings(env="test", auth_mode="jwt", openai_api_key=None)


@pytest.mark.parametrize("env", ["staging", "production"])
def test_jwt_settings_reject_unauthenticated_mode(env: str) -> None:
    with pytest.raises(ValueError, match="APP_AUTH_MODE=none"):
        Settings(env=env, auth_mode="none", openai_api_key="sk-test")


def test_api_requires_authentication_but_health_is_public(monkeypatch: pytest.MonkeyPatch) -> None:
    jwt_settings = _settings()
    monkeypatch.setattr(api_main, "settings", jwt_settings)
    monkeypatch.setattr(api_main, "auth_verifier", TokenVerifier(jwt_settings))
    client = TestClient(api_main.app)

    protected = client.get("/v1/threads/00000000-0000-0000-0000-000000000000/messages")

    assert protected.status_code == 401
    assert protected.json() == {"detail": "authentication_error"}
    assert protected.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert client.get("/health/live").status_code == 200
