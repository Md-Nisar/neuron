from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
import structlog
from cryptography.hazmat.primitives import serialization
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


def _token(
    private: Any, *, kid: str = "key-1", headers: dict[str, str] | None = None, **overrides: Any
) -> str:
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
    return jwt.encode(
        claims,
        private,
        algorithm="RS256",
        headers={"kid": kid, **(headers or {})},
    )


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
    encoded = f"Bearer {_token(private, kid='random-a')}"
    with pytest.raises(AuthenticationError):
        await verifier.verify(encoded)
    # A fresh attacker-controlled kid must not bypass the process-wide limit.
    with pytest.raises(AuthenticationError):
        await verifier.verify(f"Bearer {_token(private, kid='random-b')}")
    assert client.calls == 1


@pytest.mark.anyio
async def test_verify_rejects_none_and_hmac_algorithms_before_key_lookup() -> None:
    private, public = _key_pair()
    verifier = TokenVerifier(_settings())
    unsigned = jwt.encode(
        {"iss": "https://issuer.example.test", "sub": "user-123"},
        key="",
        algorithm="none",
        headers={"kid": "key-1"},
    )
    with pytest.raises(AuthenticationError):
        await verifier.verify(f"Bearer {unsigned}")

    hmac_token = jwt.encode(
        {"iss": "https://issuer.example.test", "sub": "user-123"},
        key="attacker-controlled-secret-material-longer-than-32-bytes",
        algorithm="HS256",
        headers={"kid": "key-1"},
    )
    with pytest.raises(AuthenticationError):
        await verifier.verify(f"Bearer {hmac_token}")

    # Construct the classic RSA-public-key-as-HMAC-secret confusion token;
    # the verifier rejects the algorithm before it ever consumes this key.
    public_pem = public.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    def encode(value: bytes) -> bytes:
        return base64.urlsafe_b64encode(value).rstrip(b"=")

    encoded_header = encode(b'{"alg":"HS256","kid":"key-1"}')
    encoded_payload = encode(b'{"iss":"https://issuer.example.test","sub":"user-123"}')
    signing_input = encoded_header + b"." + encoded_payload
    signature = encode(hmac.new(public_pem, signing_input, hashlib.sha256).digest())
    confusion_token = b".".join((signing_input, signature)).decode()
    with pytest.raises(AuthenticationError):
        await verifier.verify(f"Bearer {confusion_token}")


@pytest.mark.anyio
async def test_verify_rejects_bad_signature_and_not_yet_valid_token() -> None:
    signing_key, trusted_key = _key_pair()
    other_key, _ = _key_pair()
    verifier = TokenVerifier(_settings())
    verifier._client = FakeJWKClient(trusted_key)  # type: ignore[assignment]

    with pytest.raises(AuthenticationError):
        await verifier.verify(f"Bearer {_token(other_key)}")
    with pytest.raises(AuthenticationError):
        await verifier.verify(
            f"Bearer {_token(signing_key, nbf=datetime.now(UTC) + timedelta(minutes=5))}"
        )


@pytest.mark.anyio
async def test_verify_requires_subject_and_configured_access_token_type() -> None:
    private, public = _key_pair()
    settings = _settings().model_copy(update={"auth_require_typ": True})
    verifier = TokenVerifier(settings)
    verifier._client = FakeJWKClient(public)  # type: ignore[assignment]

    missing_subject = {
        "iss": "https://issuer.example.test",
        "aud": "neuron-api",
        "iat": datetime.now(UTC),
        "nbf": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }
    token_without_subject = jwt.encode(
        missing_subject, private, algorithm="RS256", headers={"kid": "key-1", "typ": "at+jwt"}
    )
    with pytest.raises(AuthenticationError):
        await verifier.verify(f"Bearer {token_without_subject}")

    with pytest.raises(AuthenticationError):
        await verifier.verify(f"Bearer {_token(private)}")


@pytest.mark.anyio
async def test_authentication_logs_never_contain_token_or_claim_values() -> None:
    private, public = _key_pair()
    verifier = TokenVerifier(_settings())
    verifier._client = FakeJWKClient(public)  # type: ignore[assignment]
    token = _token(private, sub="sensitive-subject-value")

    with structlog.testing.capture_logs() as events:
        with pytest.raises(AuthenticationError):
            await verifier.verify(f"Bearer {token[:-3]}bad")

    rendered = json.dumps(events)
    assert token not in rendered
    assert "sensitive-subject-value" not in rendered


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
