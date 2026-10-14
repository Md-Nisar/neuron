"""Token attacks against the real verifier, end to end through the HTTP API (#61).

Every rejected token must produce the same `401 authentication_error` with an RFC 6750
challenge, expose no data, and never make the verifier fetch keys from anywhere but the
configured JWKS URL.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import jwt
import jwt.api_jwt
import pytest
import structlog.testing
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError
from tests.conftest import JWKS_URL, JwksServer, JwtApi, JwtClock, JwtKeys, bearer, jwt_settings

_PROTECTED = "/v1/me/threads"
# A well-formed key the identity provider never published.
_ATTACKER_KEY = rsa.generate_private_key(public_exponent=65_537, key_size=2048)
_ATTACKER_JWK = {
    **json.loads(jwt.get_algorithm_by_name("RS256").to_jwk(_ATTACKER_KEY.public_key())),
    "kid": "attacker-1",
}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _segments(header: dict[str, Any], claims: dict[str, Any]) -> str:
    return f"{_b64(json.dumps(header).encode())}.{_b64(json.dumps(claims).encode())}"


def _claims(token: str) -> dict[str, Any]:
    return dict(jwt.decode(token, options={"verify_signature": False}))


def _assert_rejected(api: JwtApi, token: str) -> None:
    with structlog.testing.capture_logs() as logs:
        response = api.client.get(_PROTECTED, headers=bearer(token))
    # Every rejection is audited, exactly once, and never crashes the request.
    assert [entry["event"] for entry in logs].count("auth_failed") == 1, logs
    assert response.status_code == 401, response.text
    assert response.json() == {"detail": "authentication_error"}
    assert response.headers["www-authenticate"] == 'Bearer error="invalid_token"'
    assert set(api.jwks.requested_urls) <= {JWKS_URL}


def _assert_accepted(api: JwtApi, token: str) -> None:
    response = api.client.get(_PROTECTED, headers=bearer(token))
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("alg", ["RS256", "ES256"])
def test_trusted_tokens_are_accepted(
    jwt_api: JwtApi, make_token: Callable[..., str], alg: str
) -> None:
    _assert_accepted(jwt_api, make_token(alg=alg))


def test_alg_none_is_rejected_before_key_lookup(
    jwt_api: JwtApi, make_token: Callable[..., str], jwt_keys: JwtKeys
) -> None:
    claims = _claims(make_token())
    for alg in ("none", "None", "NONE"):
        unsigned = _segments({"alg": alg, "typ": "JWT", "kid": jwt_keys.rsa_kid}, claims) + "."
        _assert_rejected(jwt_api, unsigned)
    assert jwt_api.jwks.requested_urls == []


def test_hs256_signed_with_the_public_key_is_rejected(
    jwt_api: JwtApi, make_token: Callable[..., str], jwt_keys: JwtKeys
) -> None:
    """Algorithm confusion: an HMAC 'signed' with the issuer's public key in any encoding."""
    claims = _claims(make_token())
    public = jwt_keys.rsa.public_key()
    encodings = [
        public.public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
        public.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
        json.dumps(jwt_api.jwks.keys[0]).encode(),
    ]
    for alg, digest in (("HS256", hashlib.sha256), ("HS512", hashlib.sha512)):
        for secret in encodings:
            signing_input = _segments({"alg": alg, "kid": jwt_keys.rsa_kid}, claims)
            signature = hmac.new(secret, signing_input.encode(), digest).digest()
            _assert_rejected(jwt_api, f"{signing_input}.{_b64(signature)}")
    assert jwt_api.jwks.requested_urls == []


@pytest.mark.parametrize("algorithms", [["HS256"], ["RS256", "HS256"], ["none"], ["PS256"]])
def test_symmetric_or_unvetted_algorithms_cannot_be_configured(algorithms: list[str]) -> None:
    with pytest.raises(ValidationError, match="allowed asymmetric algorithms"):
        jwt_settings(auth_algorithms=algorithms)


@pytest.mark.parametrize(
    "kid",
    [
        "../../../../dev/null",
        "/etc/passwd",
        "rsa-1' OR '1'='1",
        "https://attacker.example/key.pem",
        "rsa-1\x00",
        "k" * 4096,
        "",
    ],
)
def test_kid_injection_is_rejected(
    jwt_api: JwtApi, make_token: Callable[..., str], kid: str
) -> None:
    _assert_rejected(jwt_api, make_token(kid=kid))


@pytest.mark.parametrize("kid", [1, ["rsa-1"], {"$ne": None}, None])
def test_non_string_kid_is_rejected_before_key_lookup(
    jwt_api: JwtApi, jwt_keys: JwtKeys, make_token: Callable[..., str], kid: Any
) -> None:
    # Signed by the trusted key, so the kid's type is the only defect.
    header = {"alg": "RS256", "kid": kid}
    signing_input = f"{_b64(json.dumps(header).encode())}.{make_token().split('.')[1]}"
    signature = jwt.get_algorithm_by_name("RS256").sign(signing_input.encode(), jwt_keys.rsa)
    _assert_rejected(jwt_api, f"{signing_input}.{_b64(signature)}")
    assert jwt_api.jwks.requested_urls == []


@pytest.mark.parametrize(
    "headers",
    [
        {"jku": "https://attacker.example/jwks.json"},
        {"x5u": "https://attacker.example/cert.pem"},
        {"jwk": _ATTACKER_JWK},
        {"jku": JWKS_URL},
    ],
)
@pytest.mark.parametrize("kid", ["attacker-1", "rsa-1"])
def test_attacker_supplied_key_locations_are_ignored(
    jwt_api: JwtApi, make_token: Callable[..., str], headers: dict[str, Any], kid: str
) -> None:
    """Keys come only from the configured JWKS URL, never from token headers."""
    token = make_token(key=_ATTACKER_KEY, kid=kid, headers=headers)
    _assert_rejected(jwt_api, token)
    assert "attacker.example" not in " ".join(jwt_api.jwks.requested_urls)


def test_typ_is_enforced_when_required(
    jwt_api_factory: Callable[..., JwtApi], make_token: Callable[..., str], echo_agent: Any
) -> None:
    api = jwt_api_factory(auth_require_typ=True)
    _assert_accepted(api, make_token(headers={"typ": "at+jwt"}))
    for typ in ("JWT", "id_token", "AT+JWT", "at+jwt "):
        _assert_rejected(api, make_token(headers={"typ": typ}))
    _assert_rejected(api, make_token(headers={"typ": None}))


def test_id_token_shaped_token_for_another_audience_is_rejected(
    jwt_api: JwtApi, make_token: Callable[..., str]
) -> None:
    _assert_rejected(jwt_api, make_token(aud="some-spa-client-id", headers={"typ": "JWT"}))


def test_token_replayed_after_expiry_is_rejected(
    jwt_api: JwtApi, make_token: Callable[..., str], jwt_clock: type[JwtClock]
) -> None:
    token = make_token(exp=timedelta(minutes=5))
    _assert_accepted(jwt_api, token)

    leeway = timedelta(seconds=jwt_api.settings.auth_leeway_seconds)
    jwt_clock.offset = timedelta(minutes=5) + leeway - timedelta(seconds=5)
    _assert_accepted(jwt_api, token)
    jwt_clock.offset = timedelta(minutes=5) + leeway + timedelta(seconds=1)
    _assert_rejected(jwt_api, token)


def test_not_yet_valid_token_is_rejected(jwt_api: JwtApi, make_token: Callable[..., str]) -> None:
    leeway = jwt_api.settings.auth_leeway_seconds
    _assert_rejected(jwt_api, make_token(nbf=timedelta(seconds=leeway + 60)))
    _assert_rejected(jwt_api, make_token(nbf=timedelta(hours=1), exp=timedelta(hours=2)))
    _assert_accepted(jwt_api, make_token(nbf=timedelta(seconds=leeway - 10)))


def test_oversized_token_is_rejected_before_parsing(
    jwt_api: JwtApi, make_token: Callable[..., str]
) -> None:
    limit = jwt_api.settings.auth_token_max_bytes
    _assert_rejected(jwt_api, make_token(padding="x" * limit))
    _assert_rejected(jwt_api, make_token(headers={"padding": "x" * limit}))
    assert jwt_api.jwks.requested_urls == []


def test_oversized_authorization_header_is_rejected(jwt_api: JwtApi) -> None:
    response = jwt_api.client.get(_PROTECTED, headers={"Authorization": "Bearer " + "a" * 200_000})
    assert response.status_code == 401
    assert response.json() == {"detail": "authentication_error"}
    assert jwt_api.jwks.requested_urls == []


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param(
            lambda h, p, s: f"{h}.{_b64(json.dumps({**_payload(p), 'sub': 'bob'}).encode())}.{s}",
            id="claims",
        ),
        pytest.param(lambda h, p, s: f"{h}.{p}.{s}!!!!", id="non-base64url-signature"),
        pytest.param(lambda h, p, s: f"{h}.{p}.", id="stripped-signature"),
        pytest.param(lambda h, p, s: f"{h}.{p}", id="two-segments"),
        pytest.param(lambda h, p, s: f"{h}.{p}.{s}.{s}", id="extra-segment"),
        pytest.param(lambda h, p, s: f"{h}.{p}.{s[::-1]}", id="reversed-signature"),
    ],
)
def test_tampered_tokens_are_rejected(
    jwt_api: JwtApi, make_token: Callable[..., str], tamper: Callable[[str, str, str], str]
) -> None:
    header, payload, signature = make_token().split(".")
    _assert_rejected(jwt_api, tamper(header, payload, signature))


def _payload(segment: str) -> dict[str, Any]:
    return dict(json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))))


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://attacker.example"},
        {"iss": None},
        {"aud": "another-api"},
        {"aud": None},
        {"sub": None},
        {"sub": ""},
        {"sub": 123},
        {"exp": timedelta(seconds=-3600)},
        {"iat": None},
        {"iat": "yesterday"},
    ],
)
def test_tokens_with_wrong_or_missing_registered_claims_are_rejected(
    jwt_api: JwtApi, make_token: Callable[..., str], overrides: dict[str, Any]
) -> None:
    _assert_rejected(jwt_api, make_token(**overrides))


def test_trusted_kid_signed_with_other_algorithm_family_is_rejected(
    jwt_api: JwtApi, make_token: Callable[..., str], jwt_keys: JwtKeys
) -> None:
    """An ES256 signature presented under the RSA key's kid, and vice versa."""
    _assert_rejected(jwt_api, make_token(alg="ES256", kid=jwt_keys.rsa_kid))
    _assert_rejected(jwt_api, make_token(alg="RS256", kid=jwt_keys.ec_kid))


def test_allowed_alg_that_differs_from_the_keys_alg_is_rejected(
    jwt_api_factory: Callable[..., JwtApi],
    make_token: Callable[..., str],
    jwt_keys: JwtKeys,
    echo_agent: Any,
) -> None:
    """RS384 is allowed, and the RSA key's signature is valid, but the key is bound to RS256."""
    api = jwt_api_factory(auth_algorithms=["RS256", "RS384"])
    _assert_accepted(api, make_token(alg="RS256"))
    _assert_rejected(api, make_token(alg="RS384", kid=jwt_keys.rsa_kid))


def test_jwks_entries_without_alg_bind_the_algorithm_inferred_from_the_key(
    jwt_api_factory: Callable[..., JwtApi],
    jwks_server: JwksServer,
    make_token: Callable[..., str],
    jwt_keys: JwtKeys,
    echo_agent: Any,
) -> None:
    for key in jwks_server.keys:
        del key["alg"]
    api = jwt_api_factory(auth_algorithms=["RS256", "RS384", "ES256"])
    _assert_accepted(api, make_token(alg="RS256"))
    _assert_accepted(api, make_token(alg="ES256"))
    _assert_rejected(api, make_token(alg="RS384", kid=jwt_keys.rsa_kid))
