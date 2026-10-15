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
from fastapi import Depends, Header, HTTPException, Request
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
from neuron_agent.errors.base import (
    AuthenticationError,
    AuthenticationUnavailableError,
    AuthorizationError,
)
from neuron_agent.observability.audit import audit
from neuron_agent.security.authorization import (
    DEV_PERMISSIONS,
)
from neuron_agent.security.authorization import (
    require_permission as check_permission,
)

logger = structlog.get_logger(__name__)
# Readiness refreshes a failed JWKS at most this often per process, whoever probes.
_READINESS_PROBE_INTERVAL_SECONDS = 5.0
_shared_token_verifier: TokenVerifier | None = None


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
        self._clock = time.monotonic
        self._probe_lock = anyio.Lock()
        self._last_probe_at: float | None = None
        self._probe_timeout = float(settings.auth_jwks_timeout_seconds)

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
            # Pass the PyJWK itself, not its raw key: PyJWT then verifies with the key's
            # own algorithm and rejects a token whose `alg` names a different one.
            claims = jwt.decode(
                token,
                signing_key,
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
            audit(
                "auth_failed",
                outcome="error",
                issuer_id=self._settings.auth_issuer_id,
                reason="jwks_unavailable",
            )
            raise AuthenticationUnavailableError() from exc
        except PyJWKClientError as exc:
            audit(
                "auth_failed",
                outcome="denied",
                issuer_id=self._settings.auth_issuer_id,
                reason="unknown_signing_key",
            )
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
        """Report whether the JWKS is usable, refreshing it after a failure (throttled)."""
        if self._settings.auth_mode != "jwt":
            return True
        if self._last_unavailable_at is None:
            return True
        await self._probe_jwks()
        return self._last_unavailable_at is None

    async def _probe_jwks(self) -> None:
        """Refresh the JWKS once per window, shared by concurrent probes and time-bounded."""
        if self._client is None:
            return
        async with self._probe_lock:
            now = self._clock()
            last = self._last_probe_at
            if last is not None and now - last < _READINESS_PROBE_INTERVAL_SECONDS:
                return
            self._last_probe_at = now
            try:
                with anyio.fail_after(self._probe_timeout):
                    await anyio.to_thread.run_sync(
                        lambda: self._client.get_signing_keys(refresh=True),  # type: ignore[union-attr]
                        abandon_on_cancel=True,
                    )
            except (PyJWKClientError, TimeoutError):
                return
            self._last_unavailable_at = None

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

    def _extract_bearer_token(self, authorization: str | None) -> str:
        if authorization is None:
            audit(
                "auth_failed",
                outcome="denied",
                issuer_id=self._settings.auth_issuer_id,
                reason="missing_token",
            )
            raise AuthenticationError()
        scheme, separator, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not token or " " in token:
            audit(
                "auth_failed",
                outcome="denied",
                issuer_id=self._settings.auth_issuer_id,
                reason="invalid_scheme",
            )
            raise AuthenticationError()
        return token

    def _principal_from_claims(self, claims: dict[str, Any]) -> Principal:
        issuer = claims["iss"]
        subject = claims["sub"]
        expires_at = claims["exp"]
        if not isinstance(issuer, str) or not issuer or not isinstance(subject, str) or not subject:
            raise self._reject("invalid_claims")
        if not isinstance(expires_at, (int, float)):
            raise self._reject("invalid_claims")
        raw_scope = claims.get(
            self._settings.auth_scope_claim,
            claims.get("scp" if self._settings.auth_scope_claim != "scp" else "scope", ""),
        )
        if isinstance(raw_scope, str):
            scopes = frozenset(value for value in raw_scope.split() if value)
        elif isinstance(raw_scope, list) and all(isinstance(value, str) for value in raw_scope):
            scopes = frozenset(raw_scope)
        else:
            scopes = frozenset()
        role_claim = self._settings.auth_roles_claim
        roles = claims.get(role_claim, []) if role_claim else []
        if isinstance(roles, str):
            roles = [roles]
        if isinstance(roles, list):
            scopes = scopes | frozenset(
                permission
                for role in roles
                if isinstance(role, str)
                for permission in self._settings.auth_role_permissions.get(role, [])
            )
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

    def _reject(self, reason: str) -> AuthenticationError:
        audit(
            "auth_failed",
            outcome="denied",
            issuer_id=self._settings.auth_issuer_id,
            reason=reason,
        )
        return AuthenticationError()


def get_shared_token_verifier(settings: Settings) -> TokenVerifier:
    """Return the process-wide verifier shared by both deployment entrypoints."""
    global _shared_token_verifier
    if _shared_token_verifier is None:
        _shared_token_verifier = TokenVerifier(settings)
    return _shared_token_verifier


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
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> Principal | None:
    """FastAPI dependency used on every protected `/v1/*` route."""
    from neuron_agent.api import main as api_main

    if api_main.settings.auth_mode == "none":
        return None
    ip_key: str | None = None
    if api_main.settings.rate_limit_enabled and api_main._route_path(request.scope).startswith(
        api_main._RATE_LIMITED_PREFIXES
    ):
        ip_key = f"ip:{api_main._client_ip(request)}"
    try:
        principal = await api_main.auth_verifier.verify(authorization)
    except (AuthenticationError, AuthenticationUnavailableError) as exc:
        if ip_key is not None and isinstance(exc, AuthenticationError):
            decision = api_main.rate_limiter.check(ip_key)
            if not decision.allowed:
                retry_after = max(1, int(decision.retry_after_seconds + 0.999))
                logger.warning(
                    "user_limit_exceeded",
                    limit_type="authentication_attempts",
                    owner_key_prefix=api_main._opaque_identity_prefix(ip_key),
                    retry_after=retry_after,
                )
                audit(
                    "limit_exceeded",
                    outcome="denied",
                    issuer_id=api_main.settings.auth_issuer_id,
                    action="authentication",
                    resource_type="api",
                    reason="authentication_attempts",
                )
                raise HTTPException(
                    status_code=429,
                    detail="rate_limited",
                    headers={"Retry-After": str(retry_after)},
                ) from exc
        raise authentication_http_error(exc) from exc
    if api_main.settings.auth_audit_success_enabled:
        identity_key = api_main.settings.identity_hash_key
        actor = (
            principal_owner_key(principal, identity_key.get_secret_value())[:12]
            if principal is not None and identity_key is not None
            else None
        )
        audit(
            "auth_succeeded",
            outcome="allowed",
            actor=actor,
            issuer_id=api_main.settings.auth_issuer_id,
        )
    return principal


def require_permission(permission: str) -> Any:
    """Create the single route dependency that authenticates and authorizes a `/v1` route."""

    async def dependency(
        request: Request,
        principal: Principal | None = Depends(require_principal),  # noqa: B008
    ) -> Principal | None:
        from neuron_agent.api import main as api_main

        permissions = (
            DEV_PERMISSIONS
            if api_main.settings.auth_mode == "none"
            else (principal.scopes if principal is not None else frozenset())
        )
        if (
            api_main.settings.rate_limit_enabled
            and principal is not None
            and api_main._route_path(request.scope).startswith(api_main._RATE_LIMITED_PREFIXES)
        ):
            identity_hash_key = api_main.settings.identity_hash_key
            if identity_hash_key is None:
                raise RuntimeError(
                    "APP_IDENTITY_HASH_KEY is required for authenticated rate limits"
                )
            owner_key = principal_owner_key(principal, identity_hash_key.get_secret_value())
            decision = api_main.rate_limiter.check(f"principal:{owner_key}")
            if not decision.allowed:
                retry_after = max(1, int(decision.retry_after_seconds + 0.999))
                logger.warning(
                    "user_limit_exceeded",
                    limit_type="request_rate",
                    owner_key_prefix=owner_key[:12],
                    retry_after=retry_after,
                )
                audit(
                    "limit_exceeded",
                    outcome="denied",
                    actor=owner_key[:12],
                    issuer_id=api_main.settings.auth_issuer_id,
                    action=permission,
                    resource_type="api",
                    reason="request_rate",
                )
                raise HTTPException(
                    status_code=429,
                    detail="rate_limited",
                    headers={"Retry-After": str(retry_after)},
                )
        try:
            check_permission(permission, permissions)
        except AuthorizationError as exc:
            thread_id = request.path_params.get("thread_id")
            identity_key = api_main.settings.identity_hash_key
            actor = (
                principal_owner_key(principal, identity_key.get_secret_value())[:12]
                if principal is not None and identity_key is not None
                else None
            )
            audit(
                "authorization_denied",
                outcome="denied",
                actor=actor,
                issuer_id=api_main.settings.auth_issuer_id,
                action=permission,
                resource_type="thread" if thread_id else "agent",
                resource_id=str(thread_id) if thread_id else None,
                reason="insufficient_scope",
            )
            raise HTTPException(
                status_code=403,
                detail="authorization_error",
                headers={
                    "WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{permission}"'
                },
            ) from exc
        return principal

    dependency.required_permission = permission  # type: ignore[attr-defined]
    return dependency
