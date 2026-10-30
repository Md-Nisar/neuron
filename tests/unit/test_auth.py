from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError
from tests.conftest import PRODUCTION_PROFILE

from neuron_agent.api import main as api_main
from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import AuthenticationError, AuthenticationUnavailableError
from neuron_agent.security.auth import TokenVerifier


class FakeJWKClient:
    def __init__(self, key: Any) -> None:
        self.key = key

    def get_signing_key_from_jwt(self, token: str) -> Any:
        jwk = json.loads(jwt.get_algorithm_by_name("RS256").to_jwk(self.key))
        return jwt.PyJWK({**jwk, "kid": "key-1"}, algorithm="RS256")


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
async def test_verify_maps_configured_scope_claim_and_roles_to_permissions() -> None:
    private, public = _key_pair()
    settings = _settings()
    settings.auth_scope_claim = "permissions"
    settings.auth_roles_claim = "groups"
    settings.auth_role_permissions = {"operators": ["threads:delete"]}
    verifier = TokenVerifier(settings)
    verifier._client = FakeJWKClient(public)  # type: ignore[assignment]

    token = _token(private, permissions=["agent:invoke"], groups=["operators"])
    principal = await verifier.verify(f"Bearer {token}")

    assert principal.scopes == {"agent:invoke", "threads:delete"}


@pytest.mark.anyio
async def test_verify_unknown_permission_claim_grants_nothing() -> None:
    private, public = _key_pair()
    verifier = TokenVerifier(_settings())
    verifier._client = FakeJWKClient(public)  # type: ignore[assignment]

    principal = await verifier.verify(f"Bearer {_token(private, scope=None, scp=None)}")

    assert principal.scopes == frozenset()


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
    token = _token(private, sub="audit.person@example.test")

    with structlog.testing.capture_logs() as events:
        with pytest.raises(AuthenticationError):
            await verifier.verify(f"Bearer {token[:-3]}bad")

    rendered = json.dumps(events)
    assert token not in rendered
    assert "audit.person@example.test" not in rendered
    assert not re.search(r"\bsub\b", rendered)
    assert not re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", rendered)
    assert not re.search(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", rendered)
    assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", rendered)
    assert [entry["event"] for entry in events].count("auth_failed") == 1


@pytest.mark.anyio
async def test_verify_fails_closed_when_jwks_is_unavailable() -> None:
    private, _ = _key_pair()
    verifier = TokenVerifier(_settings())

    class UnavailableClient:
        def get_signing_key_from_jwt(self, token: str) -> Any:
            raise PyJWKClientConnectionError("identity provider unavailable")

        def get_signing_keys(self, refresh: bool = False) -> list[Any]:
            raise PyJWKClientConnectionError("identity provider unavailable")

    verifier._client = UnavailableClient()  # type: ignore[assignment]

    with pytest.raises(AuthenticationUnavailableError):
        await verifier.verify(f"Bearer {_token(private)}")
    assert await verifier.ready() is False


class FlakyJWKSClient:
    """Fails fetches while `down`, counting every forced refresh the probe makes."""

    def __init__(self) -> None:
        self.down = True
        self.fetches = 0

    def get_signing_keys(self, refresh: bool = False) -> list[Any]:
        self.fetches += 1
        if self.down:
            raise PyJWKClientConnectionError("identity provider unavailable")
        return []


def _unready_verifier(client: Any, clock: list[float]) -> TokenVerifier:
    verifier = TokenVerifier(_settings())
    verifier._client = client
    verifier._clock = lambda: clock[0]
    verifier._last_unavailable_at = 1.0
    return verifier


@pytest.mark.anyio
async def test_ready_stays_unready_during_outage_and_recovers_after_refresh() -> None:
    client = FlakyJWKSClient()
    clock = [100.0]
    verifier = _unready_verifier(client, clock)

    assert await verifier.ready() is False
    assert client.fetches == 1

    client.down = False
    clock[0] += 10.0
    assert await verifier.ready() is True
    assert await verifier.ready() is True
    assert client.fetches == 2  # a healthy verifier no longer probes


@pytest.mark.anyio
async def test_ready_probe_is_throttled_to_one_fetch_per_window() -> None:
    client = FlakyJWKSClient()
    clock = [100.0]
    verifier = _unready_verifier(client, clock)

    results = [await verifier.ready() for _ in range(5)]
    assert results == [False] * 5
    assert client.fetches == 1

    clock[0] += 5.0
    assert await verifier.ready() is False
    assert client.fetches == 2


@pytest.mark.anyio
async def test_concurrent_ready_probes_share_one_fetch() -> None:
    import anyio

    client = FlakyJWKSClient()
    verifier = _unready_verifier(client, [100.0])
    results: list[bool] = []

    async def probe() -> None:
        results.append(await verifier.ready())

    async with anyio.create_task_group() as group:
        for _ in range(10):
            group.start_soon(probe)

    assert results == [False] * 10
    assert client.fetches == 1


@pytest.mark.anyio
async def test_ready_probe_is_bounded_by_the_jwks_timeout() -> None:
    import threading

    release = threading.Event()

    class HangingClient:
        def get_signing_keys(self, refresh: bool = False) -> list[Any]:
            release.wait(10)
            return []

    verifier = _unready_verifier(HangingClient(), [100.0])
    verifier._probe_timeout = 0.05
    try:
        assert await verifier.ready() is False
    finally:
        release.set()


@pytest.mark.anyio
async def test_ready_probe_does_not_fetch_when_verifier_is_healthy() -> None:
    client = FlakyJWKSClient()
    verifier = TokenVerifier(_settings())
    verifier._client = client  # type: ignore[assignment]

    assert await verifier.ready() is True
    assert client.fetches == 0


def test_jwt_settings_require_identity_provider_configuration() -> None:
    with pytest.raises(ValueError, match="APP_AUTH_ISSUER"):
        Settings(env="test", auth_mode="jwt", openai_api_key=None)


@pytest.mark.parametrize("env", ["staging", "production"])
def test_jwt_settings_reject_unauthenticated_mode(env: str) -> None:
    with pytest.raises(ValueError, match="APP_AUTH_MODE=none"):
        Settings(env=env, auth_mode="none", openai_api_key="sk-test", **PRODUCTION_PROFILE)


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


@pytest.mark.anyio
async def test_ready_probe_reports_unready_for_a_malformed_jwks() -> None:
    from jwt.exceptions import PyJWKSetError

    class MalformedClient:
        def get_signing_keys(self, refresh: bool = False) -> list[Any]:
            raise PyJWKSetError("The JWK Set did not contain any keys")

    verifier = _unready_verifier(MalformedClient(), [100.0])

    assert await verifier.ready() is False


class SwitchableJWKSClient(jwt.PyJWKClient):
    """A real PyJWKClient (real cache) whose network fetch can be switched off."""

    def __init__(self, public: Any) -> None:
        super().__init__("https://issuer.example.test/.well-known/jwks.json", lifespan=300)
        jwk = json.loads(jwt.get_algorithm_by_name("RS256").to_jwk(public))
        self._data = {"keys": [{**jwk, "kid": "key-1", "use": "sig", "alg": "RS256"}]}
        self.down = False

    def fetch_data(self) -> Any:
        if self.down:
            raise PyJWKClientConnectionError("identity provider unavailable")
        return self._data


@pytest.mark.anyio
async def test_health_ready_alone_recovers_after_a_jwks_outage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private, public = _key_pair()
    client = SwitchableJWKSClient(public)
    client.down = True
    verifier = TokenVerifier(_settings())
    verifier._client = client
    clock = [100.0]
    verifier._clock = lambda: clock[0]
    monkeypatch.setattr(api_main, "settings", _settings())
    monkeypatch.setattr(api_main, "auth_verifier", verifier)

    async def persistence_ready(self: object) -> bool:
        return True

    monkeypatch.setattr(api_main.AgentService, "is_ready", persistence_ready)
    http = TestClient(api_main.app)

    with pytest.raises(AuthenticationUnavailableError):  # the outage is noticed once
        await verifier.verify(f"Bearer {_token(private)}")
    assert http.get("/health/ready").status_code == 503

    clock[0] += 5.0  # still down: probes keep failing
    assert http.get("/health/ready").status_code == 503

    client.down = False  # the IdP answers again; no /v1 traffic from here on
    clock[0] += 5.0
    assert http.get("/health/ready").status_code == 200
    assert http.get("/health/ready").json()["status"] == "ready"


@pytest.mark.anyio
async def test_cached_keys_keep_instance_ready_and_verifying_during_a_jwks_outage() -> None:
    private, public = _key_pair()
    client = SwitchableJWKSClient(public)
    verifier = TokenVerifier(_settings())
    verifier._client = client
    await verifier.verify(f"Bearer {_token(private)}")  # fills the key cache
    client.down = True

    principal = await verifier.verify(f"Bearer {_token(private)}")  # signed with a cached key

    assert principal.subject == "user-123"
    assert await verifier.ready() is True


@pytest.mark.anyio
async def test_uncached_kid_during_an_outage_keeps_an_instance_with_cached_keys_ready() -> None:
    private, public = _key_pair()
    client = SwitchableJWKSClient(public)
    verifier = TokenVerifier(_settings())
    verifier._client = client
    await verifier.verify(f"Bearer {_token(private)}")
    client.down = True

    with pytest.raises(AuthenticationUnavailableError):  # still not accepted
        await verifier.verify(f"Bearer {_token(private, kid='not-published')}")

    assert await verifier.ready() is True
    assert (await verifier.verify(f"Bearer {_token(private)}")).subject == "user-123"


@pytest.mark.anyio
async def test_instance_with_no_cached_keys_goes_unready_when_the_jwks_is_down() -> None:
    private, public = _key_pair()
    client = SwitchableJWKSClient(public)
    client.down = True
    verifier = TokenVerifier(_settings())
    verifier._client = client

    with pytest.raises(AuthenticationUnavailableError):
        await verifier.verify(f"Bearer {_token(private)}")

    assert await verifier.ready() is False
