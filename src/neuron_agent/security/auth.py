"""Bearer-token authentication and verified caller principals."""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import anyio
import jwt
import structlog
from fastapi import Header, HTTPException
from jwt import PyJWKClient
from jwt.exceptions import (
    DecodeError,
    ExpiredSignatureError,
    ImmatureSignatureError,
    InvalidAudienceError,
    InvalidIssuedAtError,
    InvalidIssuerError,
    InvalidSignatureError,
    MissingRequiredClaimError,
    PyJWKClientConnectionError,
    PyJWKClientError,
    PyJWTError,
)

from neuron_agent.config.settings import Settings
from neuron_agent.errors.base import AuthenticationError, AuthenticationUnavailableError

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Principal:
    """The small, verified identity contract shared by API and service layers."""

    issuer: str
    subject: str
    scopes: frozenset[str]
    token_id: str | None
    expires_at: datetime


def principal_owner_key(principal: Principal, identity_hash_key: str) -> str:
    """Derive the non-reversible thread owner key for a verified principal."""
    identity = f"{principal.issuer}\x1f{principal.subject}".encode()
    return hmac.new(identity_hash_key.encode("utf-8"), identity, hashlib.sha256).hexdigest()


class TokenVerifier:
    """Verify JWT bearer tokens without exposing token or claim values to logs."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = (
            PyJWKClient(
                settings.auth_jwks_url or "",
                cache_jwk_set=True,
                lifespan=settings.auth_jwks_cache_seconds,
                timeout=settings.auth_jwks_timeout_seconds,
            )
            if settings.auth_mode == "jwt"
            else None
        )
        self._refresh_lock = anyio.Lock()
        # One process-wide cooldown bounds refreshes for attacker-chosen kids.
        # A per-kid map would grow without bound and is trivially bypassed.
        self._last_unknown_kid_failure: float | None = None
        self._last_unavailable_at: float | None = None

    async def verify(self, authorization: str | None) -> Principal:
        """Verify an Authorization header and return a typed principal."""
        if self._settings.auth_mode != "jwt":
            raise RuntimeError("TokenVerifier.verify requires APP_AUTH_MODE=jwt")

        token = self._extract_bearer_token(authorization)
        if len(token.encode("utf-8")) > self._settings.auth_token_max_bytes:
            raise self._reject("token_too_large")

        try:
            header = jwt.get_unverified_header(token)
            algorithm = header.get("alg")
            kid = header.get("kid")
            if algorithm not in self._settings.auth_algorithms or not kid:
                raise self._reject("invalid_header")

            signing_key = await self._get_signing_key(token, kid)
            options = cast(Any, {"require": ["iss", "aud", "exp", "nbf", "iat", "sub"]})
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=self._settings.auth_algorithms,
                issuer=self._settings.auth_issuer,
                audience=self._settings.auth_audience,
                leeway=self._settings.auth_leeway_seconds,
                options=options,
            )
            if self._settings.auth_require_typ and header.get("typ") != "at+jwt":
                raise self._reject("invalid_type")
            return self._principal_from_claims(claims)
        except AuthenticationUnavailableError:
            raise
        except AuthenticationError:
            raise
        except PyJWKClientConnectionError as exc:
            self._last_unavailable_at = time.monotonic()
            logger.warning("auth_failed", reason="jwks_unavailable")
            raise AuthenticationUnavailableError() from exc
        except PyJWKClientError as exc:
            logger.warning("auth_failed", reason="unknown_signing_key")
            raise AuthenticationError() from exc
        except ExpiredSignatureError as exc:
            raise self._reject("expired") from exc
        except ImmatureSignatureError as exc:
            raise self._reject("not_yet_valid") from exc
        except InvalidAudienceError as exc:
            raise self._reject("wrong_audience") from exc
        except InvalidIssuerError as exc:
            raise self._reject("wrong_issuer") from exc
        except (InvalidIssuedAtError, MissingRequiredClaimError) as exc:
            raise self._reject("invalid_claims") from exc
        except (InvalidSignatureError, DecodeError, PyJWTError) as exc:
            raise self._reject("invalid_token") from exc

    async def ready(self) -> bool:
        """Report whether the verifier has seen a usable JWKS response."""
        if self._settings.auth_mode != "jwt":
            return True
        return self._last_unavailable_at is None

    async def _get_signing_key(self, token: str, kid: str) -> Any:
        if self._client is None:
            raise RuntimeError("JWT client is not configured")
        now = time.monotonic()
        async with self._refresh_lock:
            # Preserve valid tokens from the local JWKS cache during the
            # unknown-kid cooldown. PyJWKClient's public method uses its cache.
            get_signing_keys = getattr(self._client, "get_signing_keys", None)
            if get_signing_keys is not None:
                cached_keys = await anyio.to_thread.run_sync(get_signing_keys)
                for cached_key in cached_keys:
                    if cached_key.key_id == kid:
                        self._last_unavailable_at = None
                        return cached_key

            previous_failure = self._last_unknown_kid_failure
            if previous_failure is not None and now - previous_failure < 1.0:
                raise PyJWKClientError("signing-key refresh rate limited")
            try:
                key = await anyio.to_thread.run_sync(self._client.get_signing_key_from_jwt, token)
            except PyJWKClientConnectionError:
                raise
            except PyJWKClientError:
                self._last_unknown_kid_failure = time.monotonic()
                raise
            self._last_unavailable_at = None
            return key

    @staticmethod
    def _extract_bearer_token(authorization: str | None) -> str:
        if authorization is None:
            logger.warning("auth_failed", reason="missing_token")
            raise AuthenticationError()
        scheme, separator, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not token or " " in token:
            logger.warning("auth_failed", reason="invalid_scheme")
            raise AuthenticationError()
        return token

    @staticmethod
    def _principal_from_claims(claims: dict[str, Any]) -> Principal:
        issuer = claims["iss"]
        subject = claims["sub"]
        expires_at = claims["exp"]
        if not isinstance(issuer, str) or not issuer or not isinstance(subject, str) or not subject:
            raise AuthenticationError()
        if not isinstance(expires_at, (int, float)):
            raise AuthenticationError()
        raw_scope = claims.get("scope", claims.get("scp", ""))
        if isinstance(raw_scope, str):
            scopes = frozenset(value for value in raw_scope.split() if value)
        elif isinstance(raw_scope, list) and all(isinstance(value, str) for value in raw_scope):
            scopes = frozenset(raw_scope)
        else:
            scopes = frozenset()
        token_id = claims.get("jti")
        if token_id is not None and not isinstance(token_id, str):
            token_id = None
        return Principal(
            issuer=issuer,
            subject=subject,
            scopes=scopes,
            token_id=token_id,
            expires_at=datetime.fromtimestamp(expires_at, tz=UTC),
        )

    @staticmethod
    def _reject(reason: str) -> AuthenticationError:
        logger.warning("auth_failed", reason=reason)
        return AuthenticationError()


def authentication_http_error(
    error: AuthenticationError | AuthenticationUnavailableError,
) -> HTTPException:
    """Map internal authentication failures to stable RFC 6750 API responses."""
    if isinstance(error, AuthenticationUnavailableError):
        return HTTPException(status_code=503, detail="authentication_unavailable")
    return HTTPException(
        status_code=401,
        detail="authentication_error",
        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
    )


async def require_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Principal | None:
    """FastAPI dependency used on every protected `/v1/*` route."""
    from neuron_agent.api import main as api_main

    if api_main.settings.auth_mode == "none":
        return None
    try:
        return await api_main.auth_verifier.verify(authorization)
    except (AuthenticationError, AuthenticationUnavailableError) as exc:
        raise authentication_http_error(exc) from exc
